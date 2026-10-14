"""File-based skill registry service.

Design notes
------------

* The filesystem is the **only** source of truth. We don't keep a DB
  index, so admin actions like "scp a skill folder into the storage
  path" are first-class.

* Each immediate subdirectory of ``settings.skills_storage_path`` that
  contains a ``SKILL.md`` is one skill. Other subdirectories are
  ignored (this keeps things like ``.archive/`` or category folders
  from getting reported as broken skills).

* Uploads are zip archives. We accept either layout:

  - The zip's root **is** the skill (``SKILL.md`` lives at the root of
    the archive); we use the slug supplied by the caller, falling back
    to the ``name`` field in frontmatter.

  - The zip contains exactly one top-level directory which itself
    holds ``SKILL.md``. We use that directory name as the slug.

* Validation is intentionally strict: a SKILL.md with valid YAML
  frontmatter, including non-empty ``name`` and ``description``, must
  exist. Path-traversal entries (``..`` or absolute) and symlinks are
  rejected.

* Downloads are zipped in-memory. Skill bundles are small (text +
  scripts), so streaming directly from a ``BytesIO`` is fine.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


# ─── Frontmatter parser ───────────────────────────────────────────────────────


_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*(?:\n|$)",
    re.DOTALL,
)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return ``(metadata, body)`` from a Markdown file with YAML frontmatter.

    If no frontmatter block is found, returns ``({}, text)``.
    Raises ``ValueError`` when the YAML is malformed.
    """

    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw_yaml = match.group(1)
    try:
        meta = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValueError("Frontmatter must be a YAML mapping.")
    body = text[match.end() :]
    return meta, body


# ─── Slug helpers ─────────────────────────────────────────────────────────────


# Characters forbidden in file/directory names on common platforms.
_FORBIDDEN_SLUG_CHARS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *{f"COM{i}" for i in range(1, 10)},
        *{f"LPT{i}" for i in range(1, 10)},
    }
)


def is_safe_slug(value: str) -> bool:
    """Reject path traversal and filesystem-unsafe directory names.

    Slugs are used directly as folder names under ``skills_storage_path``.
    Unicode display names (including CJK) are allowed; we only block
    characters that break paths or OS filename rules.
    """

    if not value or len(value) > 128:
        return False
    if value.startswith("."):
        return False
    if value.strip() != value:
        return False
    if _FORBIDDEN_SLUG_CHARS.search(value):
        return False
    if ".." in value:
        return False
    if value.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        return False
    return True


def slugify(value: str) -> str:
    """Derive an on-disk folder name from a human-readable skill name.

    Keeps Unicode text (e.g. Chinese) as-is and only replaces characters
    that are illegal in file paths. This is **not** a transliteration to
    ASCII — the folder name can match the display name.
    """
    cleaned = value.strip()
    if not cleaned:
        return ""
    cleaned = _FORBIDDEN_SLUG_CHARS.sub("-", cleaned)
    cleaned = cleaned.rstrip(". ")
    return cleaned[:128]


def _coerce_tags(meta: dict[str, Any]) -> list[str]:
    """Pull a tag list out of a parsed SKILL.md frontmatter.

    Looks at the top-level ``tags`` field first, falling back to
    ``metadata.hermes.tags`` to match the convention used by the
    Hermes skill packs.
    """
    raw = meta.get("tags")
    if isinstance(raw, list):
        return [str(t) for t in raw if isinstance(t, (str, int))]
    nested = meta.get("metadata")
    if isinstance(nested, dict):
        hermes = nested.get("hermes")
        if isinstance(hermes, dict) and isinstance(hermes.get("tags"), list):
            return [
                str(t)
                for t in hermes["tags"]
                if isinstance(t, (str, int))
            ]
    return []


# ─── Service ──────────────────────────────────────────────────────────────────


class SkillError(HTTPException):
    """Translates to a tidy HTTP error from any caller."""


class SkillService:
    """Encapsulates filesystem operations against ``storage_root``.

    The instance is cheap; create one per request via dependency
    injection. ``ensure_storage`` creates the root on demand so the
    first request after deployment doesn't fail.
    """

    SKILL_FILE = "SKILL.md"
    README_FILE = "README.md"
    META_FILE = "_meta.json"
    REQUIRED_KEYS = ("name", "description")

    def __init__(self, storage_root: Path | str, max_upload_size: int) -> None:
        self.storage_root = Path(storage_root).expanduser().resolve()
        self.max_upload_size = max_upload_size

    # ── Storage root ──────────────────────────────────────────────────────────

    def ensure_storage(self) -> None:
        """Create the storage root if it is missing.

        Best-effort: a permission error here surfaces as a 500 to the
        caller. We do not chmod the directory, so the operator chooses
        the perms.
        """
        try:
            self.storage_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.exception("Cannot create skill storage root %s", self.storage_root)
            raise SkillError(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"无法创建 skill 存储目录：{exc}",
            ) from exc

    def _resolve_slug(self, slug: str) -> Path:
        """Return the absolute path of a slug, guarding against traversal."""
        if not is_safe_slug(slug):
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"非法的 skill 名称：{slug!r}",
            )
        path = (self.storage_root / slug).resolve()
        # ``resolve()`` collapses ``..`` so a forged slug would still escape;
        # double-check that path stays inside the storage root.
        try:
            path.relative_to(self.storage_root)
        except ValueError as exc:
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="skill 路径越界",
            ) from exc
        return path

    # ── Listing / metadata ────────────────────────────────────────────────────

    @staticmethod
    def _is_skill_md_basename(name: str) -> bool:
        """Case-insensitive ``SKILL.md`` match (accepts ``Skill.md`` /
        ``SKILL.MD`` / ``skill.Md`` …)."""
        return name.lower() == SkillService.SKILL_FILE.lower()

    def find_skill_md(self, directory: Path) -> Path | None:
        """Locate the skill markdown file inside ``directory``,
        case-insensitively. Exact ``SKILL.md`` wins; otherwise the first
        case variant (e.g. ``Skill.md``) is returned."""
        exact = directory / self.SKILL_FILE
        if exact.is_file():
            return exact
        try:
            children = sorted(directory.iterdir())
        except OSError:
            return None
        for child in children:
            if child.is_file() and self._is_skill_md_basename(child.name):
                return child
        return None

    def _canonical_known_name(self, name: str) -> str | None:
        """Return the canonical name when ``name`` is a case variant of a
        well-known skill file (``SKILL.md`` / ``README.md``)."""
        lowered = name.lower()
        if lowered == self.SKILL_FILE.lower() and name != self.SKILL_FILE:
            return self.SKILL_FILE
        if lowered == self.README_FILE.lower() and name != self.README_FILE:
            return self.README_FILE
        return None

    def list_skills(self) -> list[dict[str, Any]]:
        """Scan the storage root and return one entry per valid skill."""

        self.ensure_storage()
        results: list[dict[str, Any]] = []
        for entry in self.storage_root.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if not is_safe_slug(entry.name):
                logger.debug("Skipping skill dir with unsafe name: %s", entry)
                continue
            if self.find_skill_md(entry) is None:
                continue
            try:
                results.append(self._build_metadata(entry))
            except (OSError, ValueError) as exc:
                logger.warning("Skipping malformed skill %s: %s", entry, exc)
                continue
        results.sort(key=lambda r: r["updated_at"], reverse=True)
        return results

    def get_skill(self, slug: str) -> dict[str, Any]:
        path = self._resolve_slug(slug)
        if not path.is_dir() or self.find_skill_md(path) is None:
            raise SkillError(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"未找到 skill：{slug}",
            )
        return self._build_metadata(path, with_body=True)

    def create_skill(self, name: str, description: str) -> dict[str, Any]:
        """Create a new skill directory with a minimal ``SKILL.md``."""

        name = name.strip()
        description = description.strip()
        if not name:
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="name 不能为空",
            )
        if not description:
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="description 不能为空",
            )

        self.ensure_storage()
        base_slug = slugify(name)
        if not base_slug or not is_safe_slug(base_slug):
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "名称无效或包含不允许的字符"
                    "（不能含 / \\ : * ? \" < > |，不能以 . 开头）"
                ),
            )

        slug = base_slug
        if (self.storage_root / slug).exists():
            raise SkillError(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"skill '{slug}' 已存在",
            )

        path = self.storage_root / slug

        frontmatter = yaml.safe_dump(
            {"name": name, "description": description},
            allow_unicode=True,
            sort_keys=False,
        ).strip()
        body = f"# {name}\n\n{description}\n"
        skill_md = f"---\n{frontmatter}\n---\n\n{body}"

        try:
            path.mkdir(parents=False, exist_ok=False)
            (path / self.SKILL_FILE).write_text(skill_md, encoding="utf-8")
        except FileExistsError as exc:
            raise SkillError(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"skill 已存在：{slug}",
            ) from exc
        except OSError as exc:
            logger.exception("Failed to create skill %s", slug)
            raise SkillError(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"创建 skill 失败：{exc}",
            ) from exc

        return self._build_metadata(path)

    def _build_metadata(
        self, path: Path, *, with_body: bool = False
    ) -> dict[str, Any]:
        skill_md = self.find_skill_md(path) or (path / self.SKILL_FILE)
        text = skill_md.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)

        # Optional sibling _meta.json — used by hub-published skills to
        # carry version/owner info that isn't in the SKILL.md frontmatter.
        # Frontmatter still wins when both declare a field; we only fill
        # in the gaps from _meta.json.
        meta_json_path = path / self.META_FILE
        meta_json: dict[str, Any] = {}
        if meta_json_path.is_file():
            try:
                meta_json = json.loads(meta_json_path.read_text(encoding="utf-8"))
                if not isinstance(meta_json, dict):
                    meta_json = {}
            except (OSError, ValueError) as exc:
                logger.debug("Ignoring malformed %s: %s", meta_json_path, exc)
                meta_json = {}

        # Compute folder stats. ``walk`` is fine — bundles are small.
        file_count = 0
        size_bytes = 0
        latest_mtime = skill_md.stat().st_mtime
        files: list[str] = []
        for root, _dirs, names in os.walk(path, followlinks=False):
            for name in names:
                p = Path(root) / name
                try:
                    info = p.stat()
                except OSError:
                    continue
                file_count += 1
                size_bytes += info.st_size
                latest_mtime = max(latest_mtime, info.st_mtime)
                files.append(str(p.relative_to(path)))

        tags: list[str] = _coerce_tags(meta)

        platforms = meta.get("platforms")
        platforms_list: list[str] = (
            [str(p) for p in platforms if isinstance(p, str)]
            if isinstance(platforms, list)
            else []
        )

        record: dict[str, Any] = {
            "id": path.name,
            "name": str(meta.get("name") or meta_json.get("slug") or path.name),
            "description": str(meta.get("description") or ""),
            "author": str(meta.get("author") or ""),
            "license": str(meta.get("license") or ""),
            "platforms": platforms_list,
            "tags": tags,
            "metadata": meta.get("metadata") or {},
            "file_count": file_count,
            "size_bytes": size_bytes,
            "updated_at": datetime.fromtimestamp(latest_mtime, tz=timezone.utc),
            "has_readme": (
                (path / self.README_FILE).is_file()
                or any(
                    child.is_file()
                    and child.name.lower() == self.README_FILE.lower()
                    for child in path.iterdir()
                )
            ),
        }
        if with_body:
            record["skill_md"] = text
            record["files"] = sorted(files)
        return record

    # ── Download ──────────────────────────────────────────────────────────────

    def build_zip(self, slug: str) -> tuple[str, bytes]:
        """Zip the skill folder into memory and return ``(filename, bytes)``."""
        path = self._resolve_slug(slug)
        if not path.is_dir() or self.find_skill_md(path) is None:
            raise SkillError(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"未找到 skill：{slug}",
            )

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(path, followlinks=False):
                for name in files:
                    full = Path(root) / name
                    arcname = Path(slug) / full.relative_to(path)
                    zf.write(full, arcname.as_posix())
        return f"{slug}.zip", buffer.getvalue()

    # ── Upload ────────────────────────────────────────────────────────────────

    def save_zip_upload(
        self,
        data: bytes,
        *,
        overwrite: bool = False,
        suggested_slug: str | None = None,
    ) -> dict[str, Any]:
        """Validate and atomically install a zipped skill.

        Returns the metadata dict of the installed skill on success.
        """

        if len(data) > self.max_upload_size:
            raise SkillError(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"上传文件超过上限 {self.max_upload_size / (1024 * 1024):.0f}MiB"
                ),
            )

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                members = zf.infolist()
                if not members:
                    raise SkillError(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="上传的 zip 是空的。",
                    )
                self._reject_unsafe_members(members)
                root_prefix, skill_md_member = self._locate_skill_md(members)
                skill_md_text = zf.read(skill_md_member).decode("utf-8", errors="replace")
                meta, _body = parse_frontmatter(skill_md_text)
                self._validate_frontmatter(meta)

                # Decide the on-disk slug.
                slug = self._pick_slug(suggested_slug, root_prefix, meta)

                target = self._resolve_slug(slug)
                if target.exists():
                    if not overwrite:
                        raise SkillError(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"skill '{slug}' 已存在，未启用覆盖",
                        )

                # Stage into <root>/.<slug>.tmp-<pid> to keep partial
                # extracts off the listing, then atomically rename.
                self.ensure_storage()
                staging = self.storage_root / f".{slug}.tmp-{os.getpid()}"
                if staging.exists():
                    shutil.rmtree(staging)
                staging.mkdir(parents=True)

                try:
                    self._extract_zip(zf, members, root_prefix, staging)
                    if target.exists():
                        backup = target.with_name(f".{slug}.bak-{os.getpid()}")
                        target.rename(backup)
                        try:
                            staging.rename(target)
                        except OSError:
                            backup.rename(target)
                            raise
                        shutil.rmtree(backup, ignore_errors=True)
                    else:
                        staging.rename(target)
                except Exception:
                    shutil.rmtree(staging, ignore_errors=True)
                    raise
        except zipfile.BadZipFile as exc:
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无法解析 zip：{exc}",
            ) from exc

        return self._build_metadata(target)

    @staticmethod
    def _reject_unsafe_members(members: list[zipfile.ZipInfo]) -> None:
        for info in members:
            name = info.filename
            if not name:
                continue
            if name.startswith("/") or "\\" in name:
                raise SkillError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"zip 包含非法路径：{name}",
                )
            parts = name.split("/")
            if any(part in {"..", ""} and idx != len(parts) - 1
                   for idx, part in enumerate(parts) if part != ""):
                # Allow trailing empty for directory entries; any '..' is bad.
                pass
            if any(part == ".." for part in parts):
                raise SkillError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"zip 包含非法路径：{name}",
                )
            # Reject symlinks (high bit of external_attr means file type).
            mode = (info.external_attr >> 16) & 0xFFFF
            if mode and (mode & 0o170000) == 0o120000:
                raise SkillError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"zip 包含 symlink，不允许：{name}",
                )

    def _locate_skill_md(
        self, members: list[zipfile.ZipInfo]
    ) -> tuple[str, str]:
        """Find the ``SKILL.md`` inside the zip.

        Returns ``(root_prefix, full_member_name)`` where ``root_prefix``
        is the leading directory to strip on extraction (may be empty).
        """
        # Prefer SKILL.md at the zip root (case-insensitive: users often
        # upload skill.md / SKILL.MD / Skill.Md by mistake).
        files = [m.filename for m in members if not m.is_dir()]
        for name in files:
            if self._is_skill_md_basename(name):
                return "", name
        # Else look for exactly one top-level dir that contains SKILL.md.
        candidates: dict[str, str] = {}
        for name in files:
            parts = name.split("/")
            if len(parts) >= 2 and self._is_skill_md_basename(parts[1]):
                candidates.setdefault(parts[0] + "/", name)
        if len(candidates) == 1:
            prefix, member = next(iter(candidates.items()))
            return prefix, member
        if len(candidates) > 1:
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="zip 顶层包含多个 skill 目录，请只打包一个。",
            )
        raise SkillError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="zip 中找不到 SKILL.md。",
        )

    def _validate_frontmatter(self, meta: dict[str, Any]) -> None:
        if not meta:
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SKILL.md 缺少 YAML frontmatter。",
            )
        for key in self.REQUIRED_KEYS:
            value = meta.get(key)
            if not isinstance(value, str) or not value.strip():
                raise SkillError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"SKILL.md frontmatter 缺少必填字段：{key}",
                )

    def _pick_slug(
        self,
        suggested: str | None,
        root_prefix: str,
        meta: dict[str, Any],
    ) -> str:
        candidates: list[str] = []
        if suggested:
            candidates.append(suggested.strip())
        if root_prefix:
            candidates.append(root_prefix.rstrip("/"))
        name = meta.get("name")
        if isinstance(name, str):
            candidates.append(slugify(name))
        for candidate in candidates:
            if candidate and is_safe_slug(candidate):
                return candidate
        # Last resort: try to slugify the first non-empty candidate.
        for candidate in candidates:
            slug = slugify(candidate)
            if is_safe_slug(slug):
                return slug
        raise SkillError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无法从 zip 推断合法的 skill 名称。",
        )

    def _extract_zip(
        self,
        zf: zipfile.ZipFile,
        members: list[zipfile.ZipInfo],
        root_prefix: str,
        target: Path,
    ) -> None:
        target_resolved = target.resolve()
        for info in members:
            if info.is_dir():
                continue
            name = info.filename
            if root_prefix and not name.startswith(root_prefix):
                # Foreign top-level entries when we picked a single-root
                # zip — defensive, _locate_skill_md should have rejected
                # it. Skip rather than fail to avoid surprising behavior.
                continue
            relative = name[len(root_prefix):] if root_prefix else name
            if not relative:
                continue
            dest = (target / relative).resolve()
            try:
                dest.relative_to(target_resolved)
            except ValueError as exc:
                raise SkillError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"zip 试图写入越界路径：{name}",
                ) from exc
            # Normalize case variants of well-known files (Skill.md /
            # SKILL.MD / Readme.md …) to canonical names so downstream
            # consumers (metadata, studio, Linux container runtime) find
            # them regardless of how the zip author cased them.
            canonical = self._canonical_known_name(dest.name)
            if canonical is not None:
                dest = dest.with_name(canonical)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)

    # ── Multi-skill detection & per-skill install ────────────────────────────

    def detect_skills_in_zip(self, data: bytes) -> list[dict[str, Any]]:
        """Recursively scan a zip and return one entry per detected skill.

        Any directory containing a ``SKILL.md`` is one skill. When
        SKILL.md files nest (e.g. an outer skill's
        ``references/example/SKILL.md``), the *outer* SKILL.md wins
        and the inner one is treated as a resource so we never split
        an outer skill into pieces.

        Per-skill metadata problems (malformed YAML, missing required
        frontmatter, duplicate slugs within the zip) are reported via
        the entry's ``error`` field rather than aborting the batch —
        the modal UI then lets the user see exactly what's wrong with
        each entry. The whole upload is only rejected when the zip is
        oversized/corrupt or when zero SKILL.md exist anywhere inside.
        """

        if len(data) > self.max_upload_size:
            raise SkillError(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"上传文件超过上限 {self.max_upload_size / (1024 * 1024):.0f}MiB"
                ),
            )

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                members = zf.infolist()
                if not members:
                    raise SkillError(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="上传的 zip 是空的。",
                    )
                self._reject_unsafe_members(members)

                files = [m for m in members if not m.is_dir()]
                # Posix-only paths — _reject_unsafe_members already
                # rejected backslash separators.
                # Case-insensitive: accept skill.md / SKILL.MD / Skill.Md …
                skill_md_files = [
                    m for m in files
                    if self._is_skill_md_basename(m.filename.split("/")[-1])
                ]
                if not skill_md_files:
                    raise SkillError(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "zip 中递归检索后未找到任何 SKILL.md，"
                            "判定为非 skill 包。"
                        ),
                    )

                # Shallowest first so an outer SKILL.md claims its
                # subtree before any nested SKILL.md gets a chance.
                skill_md_files.sort(
                    key=lambda m: (m.filename.count("/"), m.filename)
                )

                detected: list[dict[str, Any]] = []
                claimed_prefixes: list[str] = []
                slug_first_seen: dict[str, str] = {}

                for info in skill_md_files:
                    path = info.filename
                    parent = path[: -len(self.SKILL_FILE)].rstrip("/")
                    parent_with_slash = f"{parent}/" if parent else ""

                    # Skip nested SKILL.md inside an already-claimed skill.
                    if any(
                        parent_with_slash.startswith(claimed)
                        for claimed in claimed_prefixes
                    ):
                        continue

                    raw_text = zf.read(info).decode("utf-8", errors="replace")
                    error: str | None = None
                    meta: dict[str, Any] = {}
                    try:
                        meta, _body = parse_frontmatter(raw_text)
                        self._validate_frontmatter(meta)
                    except SkillError as exc:
                        error = str(exc.detail)
                    except ValueError as exc:
                        error = str(exc)

                    # Optional sibling _meta.json inside the zip — gives us
                    # version metadata for hub-published skills whose
                    # SKILL.md frontmatter intentionally omits it.
                    meta_json: dict[str, Any] = {}
                    meta_member_name = f"{parent_with_slash}{self.META_FILE}"
                    try:
                        meta_member = zf.getinfo(meta_member_name)
                    except KeyError:
                        meta_member = None
                    if meta_member is not None and not meta_member.is_dir():
                        try:
                            meta_json_raw = zf.read(meta_member).decode(
                                "utf-8", errors="replace"
                            )
                            parsed = json.loads(meta_json_raw)
                            if isinstance(parsed, dict):
                                meta_json = parsed
                        except (OSError, ValueError) as exc:
                            logger.debug(
                                "Ignoring malformed %s inside zip: %s",
                                meta_member_name,
                                exc,
                            )

                    # Slug derivation: a skill's identity comes from its
                    # frontmatter `name` first (this is what the SKILL
                    # spec calls out), and only falls back to the
                    # parent folder name when the frontmatter is
                    # missing or unusable. This way re-uploading the
                    # same skill from a different wrapper folder still
                    # collides with the existing on-disk slug.
                    fm_slug = slugify(str(meta.get("name") or ""))
                    if fm_slug and not is_safe_slug(fm_slug):
                        fm_slug = ""
                    folder_basename = parent.split("/")[-1] if parent else ""
                    candidate = fm_slug or folder_basename
                    if candidate and not is_safe_slug(candidate):
                        candidate = slugify(candidate)
                    if candidate and not is_safe_slug(candidate):
                        candidate = ""

                    duplicate_of = (
                        slug_first_seen.get(candidate) if candidate else None
                    )
                    if candidate and duplicate_of is None:
                        slug_first_seen[candidate] = path

                    if not candidate:
                        slug_error = "无法从 zip 推断合法 slug"
                    elif duplicate_of and duplicate_of != path:
                        slug_error = f"zip 内重复 slug：与 {duplicate_of} 冲突"
                    else:
                        slug_error = None

                    record: dict[str, Any] = {
                        "slug": candidate,
                        "zip_root_prefix": parent_with_slash,
                        "skill_md_path": path,
                        "name": str(
                            meta.get("name")
                            or meta_json.get("slug")
                            or candidate
                            or path
                        ),
                        "description": str(meta.get("description") or ""),
                        "author": str(meta.get("author") or ""),
                        "license": str(meta.get("license") or ""),
                        "tags": _coerce_tags(meta),
                        "conflicts": bool(
                            candidate
                            and is_safe_slug(candidate)
                            and (self.storage_root / candidate).exists()
                        ),
                        "error": error or slug_error,
                    }
                    detected.append(record)
                    if candidate and not slug_error and not error:
                        claimed_prefixes.append(parent_with_slash)
        except zipfile.BadZipFile as exc:
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无法解析 zip：{exc}",
            ) from exc

        if not detected:
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="zip 中未识别到任何独立 skill。",
            )
        return detected

    def install_skill_from_zip_bytes(
        self,
        zip_bytes: bytes,
        *,
        slug: str,
        zip_root_prefix: str,
        overwrite: bool,
    ) -> dict[str, Any]:
        """Install one detected skill out of a multi-skill zip.

        ``zip_root_prefix`` is the directory inside the zip whose
        children make up the skill (empty string when the skill is at
        the zip root). Members outside that prefix are ignored, so
        importing one skill out of a multi-skill bundle never touches
        the others. We re-parse + re-validate frontmatter here so the
        cached preview data can never push a half-validated skill to
        disk even if the session record was tampered with.
        """

        if not is_safe_slug(slug):
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"非法的 skill 名称：{slug!r}",
            )

        target = self._resolve_slug(slug)
        if target.exists() and not overwrite:
            raise SkillError(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"skill '{slug}' 已存在，未启用覆盖",
            )

        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                members = zf.infolist()
                self._reject_unsafe_members(members)
                expected_skill_md = f"{zip_root_prefix}{self.SKILL_FILE}"
                skill_md_member = next(
                    (
                        m for m in members
                        if not m.is_dir()
                        and m.filename.lower() == expected_skill_md.lower()
                    ),
                    None,
                )
                if skill_md_member is None:
                    raise SkillError(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"zip 中找不到 {expected_skill_md}",
                    )
                skill_md_text = zf.read(skill_md_member).decode(
                    "utf-8", errors="replace"
                )
                meta, _body = parse_frontmatter(skill_md_text)
                self._validate_frontmatter(meta)

                self.ensure_storage()
                staging = self.storage_root / f".{slug}.tmp-{os.getpid()}"
                if staging.exists():
                    shutil.rmtree(staging)
                staging.mkdir(parents=True)

                try:
                    self._extract_zip(zf, members, zip_root_prefix, staging)
                    if target.exists():
                        backup = target.with_name(f".{slug}.bak-{os.getpid()}")
                        target.rename(backup)
                        try:
                            staging.rename(target)
                        except OSError:
                            backup.rename(target)
                            raise
                        shutil.rmtree(backup, ignore_errors=True)
                    else:
                        staging.rename(target)
                except Exception:
                    shutil.rmtree(staging, ignore_errors=True)
                    raise
        except zipfile.BadZipFile as exc:
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无法解析 zip：{exc}",
            ) from exc

        return self._build_metadata(target)

    def stage_skill_from_zip_bytes(
        self,
        zip_bytes: bytes,
        *,
        slug: str,
        zip_root_prefix: str,
        dest_parent: Path,
    ) -> dict[str, Any]:
        """Extract one detected skill from a multi-skill zip into
        ``dest_parent/{slug}/`` WITHOUT installing it into the shared
        skill library.

        Used by instance-scoped deploy: the skill goes straight from the
        upload session to the target instance and never mixes with the
        public library. Validation mirrors ``install_skill_from_zip_bytes``.
        """

        if not is_safe_slug(slug):
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"非法的 skill 名称：{slug!r}",
            )

        target = (dest_parent / slug).resolve()
        try:
            target.relative_to(dest_parent.resolve())
        except ValueError as exc:
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="目标目录越界",
            ) from exc

        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                members = zf.infolist()
                self._reject_unsafe_members(members)
                expected_skill_md = f"{zip_root_prefix}{self.SKILL_FILE}"
                skill_md_member = next(
                    (
                        m for m in members
                        if not m.is_dir()
                        and m.filename.lower() == expected_skill_md.lower()
                    ),
                    None,
                )
                if skill_md_member is None:
                    raise SkillError(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"zip 中找不到 {expected_skill_md}",
                    )
                skill_md_text = zf.read(skill_md_member).decode(
                    "utf-8", errors="replace"
                )
                meta, _body = parse_frontmatter(skill_md_text)
                self._validate_frontmatter(meta)

                if target.exists():
                    shutil.rmtree(target)
                target.mkdir(parents=True)
                self._extract_zip(zf, members, zip_root_prefix, target)
        except zipfile.BadZipFile as exc:
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无法解析 zip：{exc}",
            ) from exc

        return self._build_metadata(target)

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete_skill(self, slug: str) -> None:
        path = self._resolve_slug(slug)
        if not path.exists():
            raise SkillError(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"未找到 skill：{slug}",
            )
        if not path.is_dir():
            raise SkillError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"路径不是目录：{slug}",
            )
        shutil.rmtree(path)
