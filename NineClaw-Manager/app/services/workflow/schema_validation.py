"""Safe JSON Schema checks for workflow input and output contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from jsonschema import Draft202012Validator, SchemaError


_DRAFT_2020_12_URI = "https://json-schema.org/draft/2020-12/schema"
_SINGLE_SUBSCHEMA_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "contains",
        "contentSchema",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)
_ARRAY_SUBSCHEMA_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_MAP_SUBSCHEMA_KEYWORDS = frozenset(
    {"$defs", "dependentSchemas", "patternProperties", "properties"}
)
_SAME_INSTANCE_SINGLE_SUBSCHEMA_KEYWORDS = frozenset({"else", "if", "not", "then"})
_SAME_INSTANCE_ARRAY_SUBSCHEMA_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf"})
_SAME_INSTANCE_MAP_SUBSCHEMA_KEYWORDS = frozenset({"dependentSchemas"})


class SchemaDefinitionError(ValueError):
    """A workflow definition contains an unsupported JSON Schema."""


@dataclass(frozen=True)
class SchemaValidationIssue:
    """A public validation failure that deliberately omits the instance value."""

    instance_path: str
    keyword: str

    def as_dict(self) -> dict[str, str]:
        return {
            "instance_path": self.instance_path,
            "keyword": self.keyword,
            "message": f"不符合 JSON Schema 规则：{self.keyword}",
        }


def check_schema(schema: dict[str, Any] | None) -> None:
    """Validate a supported schema definition without resolving external resources."""
    if not schema:
        return
    if not isinstance(schema, dict):
        raise SchemaDefinitionError("JSON Schema 必须是对象")
    _reject_unsupported_references(schema)
    declared_draft = schema.get("$schema")
    if declared_draft not in (None, _DRAFT_2020_12_URI):
        raise SchemaDefinitionError("仅支持 Draft 2020-12 JSON Schema")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise SchemaDefinitionError("JSON Schema 定义无效") from exc
    _validate_local_references(schema)


def validate_instance(
    schema: dict[str, Any] | None, instance: Any, *, max_errors: int = 20
) -> tuple[SchemaValidationIssue, ...]:
    """Return bounded, value-free validation failures for one JSON instance."""
    if not schema:
        return ()
    check_schema(schema)
    try:
        errors = sorted(
            Draft202012Validator(schema).iter_errors(instance),
            key=lambda error: (
                _json_pointer(error.absolute_path),
                str(error.validator or "validation"),
                _json_pointer(error.absolute_schema_path),
            ),
        )[: max(0, max_errors)]
        return tuple(
            SchemaValidationIssue(
                instance_path=_json_pointer(error.absolute_path),
                keyword=str(error.validator or "validation"),
            )
            for error in errors
        )
    except Exception as exc:
        # A malformed local reference can escape check_schema only when the
        # instance is evaluated.  Never expose its text or trigger a 500.
        raise SchemaDefinitionError("JSON Schema 引用无效") from exc


def _schema_locations(
    root: dict[str, Any],
) -> tuple[list[tuple[str, dict[str, Any] | bool]], dict[str, str]]:
    """Return only locations where Draft 2020-12 permits a subschema.

    Annotation and instance-valued keywords (for example ``const`` and
    ``default``) can legally contain dictionaries with keys named ``$ref`` or
    ``$id``.  They are values, not schemas, so reference policy must not scan
    them.
    """

    locations: list[tuple[str, dict[str, Any] | bool]] = []
    same_instance_parents: dict[str, str] = {}

    def visit(value: Any, path: str, *, same_instance_parent: str | None) -> None:
        if same_instance_parent is not None:
            same_instance_parents[path] = same_instance_parent
        if isinstance(value, bool):
            locations.append((path, value))
            return
        if not isinstance(value, dict):
            return
        locations.append((path, value))
        for keyword in _SINGLE_SUBSCHEMA_KEYWORDS:
            if keyword in value:
                visit(
                    value[keyword],
                    _pointer_child(path, keyword),
                    same_instance_parent=(
                        path
                        if keyword in _SAME_INSTANCE_SINGLE_SUBSCHEMA_KEYWORDS
                        else None
                    ),
                )
        for keyword in _ARRAY_SUBSCHEMA_KEYWORDS:
            children = value.get(keyword)
            if not isinstance(children, list):
                continue
            for index, child in enumerate(children):
                visit(
                    child,
                    _pointer_child(path, keyword, str(index)),
                    same_instance_parent=(
                        path
                        if keyword in _SAME_INSTANCE_ARRAY_SUBSCHEMA_KEYWORDS
                        else None
                    ),
                )
        for keyword in _MAP_SUBSCHEMA_KEYWORDS:
            children = value.get(keyword)
            if not isinstance(children, dict):
                continue
            for name, child in children.items():
                if isinstance(name, str):
                    visit(
                        child,
                        _pointer_child(path, keyword, name),
                        same_instance_parent=(
                            path
                            if keyword in _SAME_INSTANCE_MAP_SUBSCHEMA_KEYWORDS
                            else None
                        ),
                    )

    visit(root, "", same_instance_parent=None)
    return locations, same_instance_parents


def _reject_unsupported_references(root: dict[str, Any]) -> None:
    locations, _ = _schema_locations(root)
    for _, value in locations:
        if not isinstance(value, dict):
            continue
        declared_draft = value.get("$schema")
        if declared_draft not in (None, _DRAFT_2020_12_URI):
            raise SchemaDefinitionError("仅支持 Draft 2020-12 JSON Schema")
        reference = value.get("$ref")
        if reference is not None and (
            not isinstance(reference, str) or not reference.startswith("#")
        ):
            raise SchemaDefinitionError("JSON Schema 仅支持本地 $ref")
        if "$dynamicRef" in value:
            raise SchemaDefinitionError("暂不支持 JSON Schema $dynamicRef")
        if "$recursiveRef" in value:
            raise SchemaDefinitionError("暂不支持 JSON Schema $recursiveRef")
        if "$id" in value:
            raise SchemaDefinitionError("暂不支持 JSON Schema $id")


def _validate_local_references(root: dict[str, Any]) -> None:
    """Ensure every supported local reference resolves before publication.

    A ``#`` prefix alone prevents network access but does not prove that a
    JSON Pointer or local anchor exists.  Resolving both here keeps malformed
    schemas out of durable workflow versions and out of the scheduler path.
    """

    locations, same_instance_parents = _schema_locations(root)
    schema_paths = {path for path, _ in locations}
    anchors: dict[str, str] = {}
    references: list[tuple[str, str]] = []
    for path, value in locations:
        if not isinstance(value, dict):
            continue
        anchor = value.get("$anchor")
        if isinstance(anchor, str) and anchor:
            if anchor in anchors:
                raise SchemaDefinitionError("JSON Schema $anchor 重复")
            anchors[anchor] = path
        reference = value.get("$ref")
        if isinstance(reference, str):
            references.append((path, reference))

    reference_edges: dict[str, set[str]] = {}
    for source_path, reference in references:
        fragment = unquote(reference[1:])
        if not fragment:
            target_path = ""
        elif fragment.startswith("/"):
            _, target_path = _resolve_json_pointer(root, fragment)
        elif fragment in anchors:
            target_path = anchors[fragment]
        else:
            raise SchemaDefinitionError("JSON Schema 本地 $ref 不存在")
        if target_path not in schema_paths:
            raise SchemaDefinitionError("JSON Schema 本地 $ref 未指向 Schema")
        for context_path in _same_instance_contexts(source_path, same_instance_parents):
            reference_edges.setdefault(context_path, set()).add(target_path)
    _reject_reference_cycles(reference_edges)


def _same_instance_contexts(
    source_path: str, same_instance_parents: dict[str, str]
) -> tuple[str, ...]:
    contexts = [source_path]
    current_path = source_path
    while current_path in same_instance_parents:
        current_path = same_instance_parents[current_path]
        contexts.append(current_path)
    return tuple(contexts)


def _reject_reference_cycles(reference_edges: dict[str, set[str]]) -> None:
    """Reject same-instance $ref loops that jsonschema cannot evaluate safely."""

    visited: set[str] = set()
    active: set[str] = set()

    def visit(path: str) -> None:
        if path in active:
            raise SchemaDefinitionError("暂不支持 JSON Schema 无约束 $ref 循环")
        if path in visited:
            return
        active.add(path)
        for target_path in reference_edges.get(path, ()):
            visit(target_path)
        active.remove(path)
        visited.add(path)

    for start in reference_edges:
        visit(start)


def _resolve_json_pointer(root: Any, pointer: str) -> tuple[Any, str]:
    value = root
    canonical_parts: list[str] = []
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and part in value:
            value = value[part]
            canonical_parts.append(_escape_json_pointer_part(part))
            continue
        if isinstance(value, list) and part.isdigit():
            index = int(part)
            if 0 <= index < len(value):
                value = value[index]
                canonical_parts.append(str(index))
                continue
        raise SchemaDefinitionError("JSON Schema 本地 $ref 不存在")
    return value, "/" + "/".join(canonical_parts)


def _pointer_child(path: str, *parts: str) -> str:
    return path + "".join(f"/{_escape_json_pointer_part(part)}" for part in parts)


def _escape_json_pointer_part(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def _json_pointer(path: Any) -> str:
    parts = [str(part).replace("~", "~0").replace("/", "~1") for part in path]
    return "/" + "/".join(parts) if parts else ""
