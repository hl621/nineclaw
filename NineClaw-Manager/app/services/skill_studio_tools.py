"""Skill-aware, root-bound tools used by the Skill Studio agent."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

import yaml
from agno.tools import Toolkit

MAX_SKILL_CONTENT_CHARS = 100_000
MAX_SUPPORT_FILE_BYTES = 1_048_576
MAX_READ_FILE_BYTES = 50_000
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ALLOWED_NEW_FILE_DIRS = {"assets", "references", "scripts", "templates"}
KNOWN_FRONTMATTER_FIELDS = {
    "allowed-tools",
    "author",
    "compatibility",
    "description",
    "license",
    "metadata",
    "name",
    "platforms",
    "prerequisites",
    "tags",
    "version",
}


def validate_skill_content(content: str) -> dict[str, Any]:
    """Validate the structural contract of a NineClaw ``SKILL.md``."""
    errors: list[str] = []
    warnings: list[str] = []
    frontmatter: dict[str, Any] = {}
    text = str(content or "")

    if len(text) > MAX_SKILL_CONTENT_CHARS:
        errors.append(
            f"SKILL.md 超过 {MAX_SKILL_CONTENT_CHARS:,} 字符；请拆分到 supporting files。"
        )
    normalized = text.lstrip("\ufeff")
    if not normalized.startswith("---"):
        errors.append("SKILL.md 必须从 YAML frontmatter 的 '---' 开始。")
        return {"valid": False, "errors": errors, "warnings": warnings}

    match = re.match(r"^---\r?\n(.*?)\r?\n---\s*\r?\n([\s\S]*)$", normalized, re.DOTALL)
    if not match:
        errors.append("YAML frontmatter 未正确闭合，结束标记应单独占一行。")
        return {"valid": False, "errors": errors, "warnings": warnings}

    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        errors.append(f"YAML frontmatter 解析失败：{exc}")
        return {"valid": False, "errors": errors, "warnings": warnings}
    if not isinstance(parsed, dict):
        errors.append("Frontmatter 必须是 YAML mapping。")
        return {"valid": False, "errors": errors, "warnings": warnings}
    frontmatter = parsed

    name = frontmatter.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("Frontmatter 必须包含非空字符串 name。")
    else:
        clean_name = name.strip()
        if len(clean_name) > MAX_NAME_LENGTH:
            errors.append(f"name 不能超过 {MAX_NAME_LENGTH} 个字符。")
        if not VALID_NAME_RE.fullmatch(clean_name):
            errors.append("name 必须使用小写字母、数字和单连字符组成的 kebab-case。")
        if "--" in clean_name or clean_name.endswith("-"):
            errors.append("name 不能以连字符结尾或包含连续连字符。")

    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("Frontmatter 必须包含非空字符串 description。")
    else:
        clean_description = description.strip()
        if len(clean_description) > MAX_DESCRIPTION_LENGTH:
            errors.append(f"description 不能超过 {MAX_DESCRIPTION_LENGTH} 个字符。")
        if "<" in clean_description or ">" in clean_description:
            errors.append("description 不能包含尖括号。")
        if len(clean_description) > 300:
            warnings.append("description 较长；触发条件应尽量前置并保持紧凑。")

    if not match.group(2).strip():
        errors.append("SKILL.md 在 frontmatter 后必须包含正文。")

    unknown = sorted(set(frontmatter) - KNOWN_FRONTMATTER_FIELDS)
    if unknown:
        warnings.append("存在未识别的 frontmatter 字段：" + ", ".join(unknown))

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "frontmatter": {
            "name": frontmatter.get("name"),
            "description": frontmatter.get("description"),
        },
        "chars": len(text),
    }


class SkillManageToolkit(Toolkit):
    """Manage one already-bound Skill without exposing its root path to the model."""

    def __init__(
        self,
        skill_root: Path,
        *,
        is_canceled: Callable[[], bool] | None = None,
    ) -> None:
        self.skill_root = skill_root.resolve()
        self.is_canceled = is_canceled or (lambda: False)
        self._read_paths: set[str] = set()
        super().__init__(
            name="skill_manage",
            tools=[self.skill_manage],
            instructions=(
                "Use skill_manage for all Skill file reads and writes. "
                "Read an existing target before patching or replacing it. "
                "Prefer patch for small edits and validate before finishing."
            ),
            add_instructions=True,
            auto_register=False,
        )
        self.register(self.skill_manage)

    @staticmethod
    def _result(**payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _resolve(self, file_path: str) -> tuple[Path | None, str | None, str]:
        raw = str(file_path or "").strip().replace("\\", "/")
        if not raw:
            return None, "file_path 不能为空。", raw
        posix = PurePosixPath(raw)
        windows = PureWindowsPath(raw)
        if posix.is_absolute() or windows.is_absolute() or windows.drive:
            return None, "file_path 必须是当前 Skill 内的相对路径。", raw
        if ".." in posix.parts or any(part in {"", "."} for part in posix.parts):
            return None, "file_path 不能包含路径穿越或空路径段。", raw
        target = (self.skill_root / Path(*posix.parts)).resolve()
        try:
            target.relative_to(self.skill_root)
        except ValueError:
            return None, "file_path 越过了当前 Skill 根目录。", raw
        return target, None, posix.as_posix()

    @staticmethod
    def _allow_new_file(relative_path: str) -> bool:
        parts = PurePosixPath(relative_path).parts
        return len(parts) >= 2 and parts[0] in ALLOWED_NEW_FILE_DIRS

    def _require_read(self, target: Path) -> str | None:
        if str(target) not in self._read_paths:
            return "修改已有文件前必须先使用 skill_manage(action='read') 读取该文件。"
        return None

    def _atomic_write(self, target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        previous_mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, previous_mode if previous_mode is not None else 0o644)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def skill_manage(
        self,
        action: str,
        file_path: str = "SKILL.md",
        content: str | None = None,
        old_text: str | None = None,
        new_text: str | None = None,
        replace_all: bool = False,
    ) -> str:
        """Read, patch, replace, write, or validate files in the current Skill.

        Args:
            action: One of read, patch, edit, write_file, or validate.
            file_path: Relative path in the current Skill. Defaults to SKILL.md.
            content: Full content for edit or write_file.
            old_text: Exact text to find for patch.
            new_text: Replacement text for patch; empty text deletes the match.
            replace_all: Allow patch to replace multiple matches. Defaults to false.
        """
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"read", "patch", "edit", "write_file", "validate"}:
            return self._result(
                success=False,
                error="action 必须是 read、patch、edit、write_file 或 validate。",
            )
        target, error, relative_path = self._resolve(file_path)
        if error or target is None:
            return self._result(success=False, error=error)

        if normalized_action == "read":
            if not target.is_file():
                return self._result(success=False, error=f"文件不存在：{relative_path}")
            size = target.stat().st_size
            if size > MAX_READ_FILE_BYTES:
                return self._result(
                    success=False,
                    error=f"文件为 {size:,} bytes，超过单次读取上限 {MAX_READ_FILE_BYTES:,} bytes；请使用 grep 定位。",
                )
            try:
                file_content = target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return self._result(success=False, error=f"文件不是 UTF-8 文本：{relative_path}")
            self._read_paths.add(str(target))
            return self._result(
                success=True,
                action="read",
                file_path=relative_path,
                content=file_content,
                chars=len(file_content),
            )

        if normalized_action == "validate":
            skill_md = self.skill_root / "SKILL.md"
            if not skill_md.is_file():
                return self._result(success=False, error="当前 Skill 缺少 SKILL.md。")
            try:
                validation = validate_skill_content(skill_md.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                return self._result(success=False, error="SKILL.md 不是 UTF-8 文本。")
            return self._result(success=validation["valid"], action="validate", **validation)

        if self.is_canceled():
            return self._result(success=False, error="运行已取消，文件写入被阻止。")

        if normalized_action == "patch":
            if not target.is_file():
                return self._result(success=False, error=f"文件不存在：{relative_path}")
            read_error = self._require_read(target)
            if read_error:
                return self._result(success=False, error=read_error, file_path=relative_path)
            if not old_text:
                return self._result(success=False, error="patch 的 old_text 不能为空。")
            if new_text is None:
                return self._result(success=False, error="patch 的 new_text 不能为空；删除匹配内容时传空字符串。")
            current = target.read_text(encoding="utf-8")
            matches = current.count(old_text)
            if matches == 0:
                return self._result(success=False, error="old_text 没有匹配任何内容。", matches=0)
            if matches != 1 and not replace_all:
                return self._result(
                    success=False,
                    error=f"old_text 匹配了 {matches} 处；默认只允许唯一匹配，请补充上下文或显式启用 replace_all。",
                    matches=matches,
                )
            updated = current.replace(old_text, new_text, -1 if replace_all else 1)
        elif normalized_action == "edit":
            if relative_path != "SKILL.md":
                return self._result(success=False, error="edit 只用于完整重写 SKILL.md；支持文件请使用 write_file。")
            if not target.is_file():
                return self._result(success=False, error="当前 Skill 缺少 SKILL.md。")
            read_error = self._require_read(target)
            if read_error:
                return self._result(success=False, error=read_error, file_path=relative_path)
            if content is None:
                return self._result(success=False, error="edit 的 content 不能为空。")
            updated = content
        else:
            if relative_path == "SKILL.md":
                return self._result(success=False, error="完整重写 SKILL.md 请使用 edit。")
            if target.exists():
                read_error = self._require_read(target)
                if read_error:
                    return self._result(success=False, error=read_error, file_path=relative_path)
            elif not self._allow_new_file(relative_path):
                allowed = "、".join(sorted(ALLOWED_NEW_FILE_DIRS))
                return self._result(
                    success=False,
                    error=f"新支持文件只能创建在 {allowed} 目录中。",
                )
            if content is None:
                return self._result(success=False, error="write_file 的 content 不能为空。")
            if len(content.encode("utf-8")) > MAX_SUPPORT_FILE_BYTES:
                return self._result(success=False, error="支持文件超过 1 MiB 上限。")
            updated = content

        validation: dict[str, Any] | None = None
        if relative_path == "SKILL.md":
            validation = validate_skill_content(updated)
            if not validation["valid"]:
                return self._result(
                    success=False,
                    error="SKILL.md 校验失败，未写入文件。",
                    validation=validation,
                )
        elif len(updated) > MAX_SKILL_CONTENT_CHARS:
            return self._result(success=False, error="文本支持文件超过 100,000 字符上限。")

        self._atomic_write(target, updated)
        self._read_paths.add(str(target))
        payload: dict[str, Any] = {
            "success": True,
            "action": normalized_action,
            "file_path": relative_path,
            "chars": len(updated),
        }
        if normalized_action == "patch":
            payload["matches_replaced"] = matches if replace_all else 1
        if validation is not None:
            payload["validation"] = validation
        return self._result(**payload)
