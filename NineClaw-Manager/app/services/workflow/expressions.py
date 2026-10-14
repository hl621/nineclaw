"""Small deterministic expression evaluator for Condition and Loop nodes.

The DSL deliberately has no script execution.  Expressions operate only on
the supplied immutable context and support a compact JSON AST.
"""

from __future__ import annotations

import math
from typing import Any


class ExpressionError(ValueError):
    pass


_COMPARISON_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "in"}
_BOOLEAN_LIST_OPERATORS = {"and", "or"}


def validate_expression(
    expression: Any, *, allowed_path_roots: set[str] | None = None
) -> None:
    """Validate the JSON-AST shape without resolving runtime-dependent paths.

    Condition and Loop expressions can refer to data produced only after a
    workflow starts.  Validation therefore rejects malformed syntax and
    operator arity at save time, while leaving path existence and value-type
    checks to the evaluator with its real execution context.
    """
    if expression is None or isinstance(expression, (str, int, bool)):
        return
    if isinstance(expression, float):
        if math.isfinite(expression):
            return
        raise ExpressionError("表达式中的数字必须是有限值")
    if isinstance(expression, list):
        for item in expression:
            validate_expression(item, allowed_path_roots=allowed_path_roots)
        return
    if not isinstance(expression, dict):
        raise ExpressionError("表达式必须是 JSON 值或对象")
    if len(expression) != 1:
        raise ExpressionError("表达式对象必须且只能包含一个操作")

    operator, value = next(iter(expression.items()))
    if operator == "path":
        _validate_path(value, allowed_path_roots=allowed_path_roots)
        return
    if operator in _COMPARISON_OPERATORS:
        left, right = _pair(value, operator)
        validate_expression(left, allowed_path_roots=allowed_path_roots)
        validate_expression(right, allowed_path_roots=allowed_path_roots)
        return
    if operator in _BOOLEAN_LIST_OPERATORS:
        if not isinstance(value, list):
            raise ExpressionError(f"{operator} 必须是数组")
        for item in value:
            validate_expression(item, allowed_path_roots=allowed_path_roots)
        return
    if operator == "not":
        validate_expression(value, allowed_path_roots=allowed_path_roots)
        return
    if operator == "exists":
        _validate_exists(value, allowed_path_roots=allowed_path_roots)
        return
    raise ExpressionError("不支持的表达式操作")


def evaluate(expression: Any, context: dict[str, Any]) -> Any:
    if isinstance(expression, (str, int, float, bool)) or expression is None:
        return expression
    if isinstance(expression, list):
        return [evaluate(item, context) for item in expression]
    if not isinstance(expression, dict):
        raise ExpressionError("表达式必须是 JSON 值或对象")
    if "path" in expression:
        return resolve_path(context, expression["path"])
    if "eq" in expression:
        left, right = _pair(expression["eq"], "eq")
        return evaluate(left, context) == evaluate(right, context)
    if "ne" in expression:
        left, right = _pair(expression["ne"], "ne")
        return evaluate(left, context) != evaluate(right, context)
    if "gt" in expression:
        left, right = _pair(expression["gt"], "gt")
        return evaluate(left, context) > evaluate(right, context)
    if "gte" in expression:
        left, right = _pair(expression["gte"], "gte")
        return evaluate(left, context) >= evaluate(right, context)
    if "lt" in expression:
        left, right = _pair(expression["lt"], "lt")
        return evaluate(left, context) < evaluate(right, context)
    if "lte" in expression:
        left, right = _pair(expression["lte"], "lte")
        return evaluate(left, context) <= evaluate(right, context)
    if "and" in expression:
        values = expression["and"]
        if not isinstance(values, list):
            raise ExpressionError("and 必须是数组")
        return all(bool(evaluate(item, context)) for item in values)
    if "or" in expression:
        values = expression["or"]
        if not isinstance(values, list):
            raise ExpressionError("or 必须是数组")
        return any(bool(evaluate(item, context)) for item in values)
    if "not" in expression:
        return not bool(evaluate(expression["not"], context))
    if "exists" in expression:
        path = expression["exists"]
        if isinstance(path, dict):
            path = path.get("path")
        try:
            resolve_path(context, path)
        except ExpressionError:
            return False
        return True
    if "in" in expression:
        needle, haystack = _pair(expression["in"], "in")
        return evaluate(needle, context) in evaluate(haystack, context)
    raise ExpressionError("不支持的表达式操作")


def resolve_path(value: Any, path: Any) -> Any:
    _validate_path(path)
    current = value
    for part in path.removeprefix("$").strip(".").split("."):
        if not part:
            continue
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ExpressionError(f"路径不存在：{path}")
    return current


def _pair(value: Any, name: str) -> tuple[Any, Any]:
    if not isinstance(value, list) or len(value) != 2:
        raise ExpressionError(f"{name} 必须恰有两个操作数")
    return value[0], value[1]


def _validate_exists(value: Any, *, allowed_path_roots: set[str] | None) -> None:
    if isinstance(value, str):
        _validate_path(value, allowed_path_roots=allowed_path_roots)
        return
    if isinstance(value, dict) and set(value) == {"path"}:
        _validate_path(value["path"], allowed_path_roots=allowed_path_roots)
        return
    raise ExpressionError("exists 必须是 path 字符串或仅含 path 的对象")


def _validate_path(path: Any, *, allowed_path_roots: set[str] | None = None) -> None:
    if not isinstance(path, str) or not path.strip():
        raise ExpressionError("path 必须是非空字符串")
    if allowed_path_roots is None:
        return
    normalized = path.removeprefix("$").strip(".")
    root = normalized.split(".", 1)[0]
    if root not in allowed_path_roots:
        raise ExpressionError("表达式路径不在允许的上下文中")
