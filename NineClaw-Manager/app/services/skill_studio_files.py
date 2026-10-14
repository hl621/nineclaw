"""Filesystem operations for the skill studio file browser."""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, status

from app.services.skill_service import SkillError, SkillService, is_safe_slug

logger = logging.getLogger(__name__)

_TEXT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".py", ".sh", ".bat", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".js", ".ts", ".tsx", ".jsx", ".html", ".css",
    ".xml", ".csv", ".env", ".sql",
}
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class SkillStudioFileError(HTTPException):
    pass


def _skill_root(service: SkillService, slug: str) -> Path:
    if not is_safe_slug(slug):
        raise SkillStudioFileError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"非法的 skill 标识：{slug!r}",
        )
    root = service.storage_root / slug
    if not root.is_dir() or service.find_skill_md(root) is None:
        raise SkillStudioFileError(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到 skill：{slug}",
        )
    return root.resolve()


def _resolve_relative(root: Path, relative_path: str) -> Path:
    rel = relative_path.strip().replace("\\", "/").lstrip("/")
    if not rel or rel in (".", "..") or ".." in rel.split("/"):
        raise SkillStudioFileError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="非法的文件路径",
        )
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SkillStudioFileError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件路径越界",
        ) from exc
    return target


def _mtime(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return datetime.now(tz=timezone.utc)


def list_skill_files(service: SkillService, slug: str) -> list[dict]:
    root = _skill_root(service, slug)
    entries: list[dict] = []
    seen_dirs: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        rel_dir = Path(dirpath).relative_to(root)
        dir_key = rel_dir.as_posix()
        if dir_key and dir_key not in seen_dirs and dir_key != ".":
            seen_dirs.add(dir_key)
            p = root / rel_dir
            entries.append({
                "path": dir_key,
                "name": rel_dir.name,
                "type": "folder",
                "size_bytes": 0,
                "updated_at": _mtime(p),
            })

        for name in filenames:
            if name.startswith("."):
                continue
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            try:
                size = full.stat().st_size
            except OSError:
                size = 0
            entries.append({
                "path": rel,
                "name": name,
                "type": "file",
                "size_bytes": size,
                "updated_at": _mtime(full),
            })

    entries.sort(key=lambda e: (e["type"] != "folder", e["path"].lower()))
    return entries


def read_skill_file(service: SkillService, slug: str, relative_path: str) -> dict:
    root = _skill_root(service, slug)
    target = _resolve_relative(root, relative_path)
    if not target.is_file():
        raise SkillStudioFileError(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到文件：{relative_path}",
        )
    size = target.stat().st_size
    suffix = target.suffix.lower()
    is_binary = suffix not in _TEXT_EXTENSIONS and suffix != ""
    if is_binary:
        # Binary files are previewed via the raw endpoint (streamed), so the
        # text-content size cap does not apply here.
        return {
            "slug": slug,
            "path": relative_path.replace("\\", "/"),
            "content": "",
            "is_binary": True,
            "size_bytes": size,
            "updated_at": _mtime(target),
        }
    if size > _MAX_FILE_BYTES:
        raise SkillStudioFileError(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="文件过大，无法在线预览",
        )
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SkillStudioFileError(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="无法以文本方式读取该文件",
        ) from exc
    return {
        "slug": slug,
        "path": relative_path.replace("\\", "/"),
        "content": content,
        "is_binary": False,
        "size_bytes": size,
        "updated_at": _mtime(target),
    }


def save_skill_file(
    service: SkillService, slug: str, relative_path: str, content: str
) -> dict:
    root = _skill_root(service, slug)
    target = _resolve_relative(root, relative_path)
    if len(content.encode("utf-8")) > _MAX_FILE_BYTES:
        raise SkillStudioFileError(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="文件内容过大",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        logger.exception("Failed to save skill file %s/%s", slug, relative_path)
        raise SkillStudioFileError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存失败：{exc}",
        ) from exc
    return read_skill_file(service, slug, relative_path)


def upload_skill_file(
    service: SkillService, slug: str, relative_path: str, data: bytes
) -> dict:
    """Upload one binary/text file into the skill folder (overwrite if exists)."""
    root = _skill_root(service, slug)
    target = _resolve_relative(root, relative_path)
    if target.is_dir():
        raise SkillStudioFileError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"目标是已存在的文件夹：{relative_path}",
        )
    if len(data) > _MAX_UPLOAD_BYTES:
        raise SkillStudioFileError(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="文件过大（单个文件上限 20MB）",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_bytes(data)
    except OSError as exc:
        logger.exception("Failed to upload skill file %s/%s", slug, relative_path)
        raise SkillStudioFileError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上传失败：{exc}",
        ) from exc
    return read_skill_file(service, slug, relative_path)


def _is_root_skill_md(service: SkillService, root: Path, target: Path) -> bool:
    """根目录下的 SKILL.md 是 skill 的标识文件，删除/移动会导致 skill 消失。"""
    skill_md = service.find_skill_md(root)
    if skill_md is None:
        return False
    try:
        return target.resolve() == skill_md.resolve()
    except OSError:
        return False


def delete_skill_path(service: SkillService, slug: str, relative_path: str) -> dict:
    """删除 skill 目录内的文件或文件夹（文件夹递归删除）。"""
    root = _skill_root(service, slug)
    target = _resolve_relative(root, relative_path)
    if not target.exists():
        raise SkillStudioFileError(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"路径不存在：{relative_path}",
        )
    if _is_root_skill_md(service, root, target):
        raise SkillStudioFileError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SKILL.md 是技能标识文件，不能删除",
        )
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as exc:
        logger.exception("Failed to delete skill path %s/%s", slug, relative_path)
        raise SkillStudioFileError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除失败：{exc}",
        ) from exc
    return {
        "slug": slug,
        "path": relative_path.replace("\\", "/").lstrip("/"),
        "deleted": True,
    }


def move_skill_path(
    service: SkillService, slug: str, src_path: str, dest_path: str
) -> dict:
    """移动/重命名 skill 目录内的文件或文件夹。

    ``dest_path`` 为目标相对路径（含文件名），父目录自动创建；目标已存在时报错。
    """
    root = _skill_root(service, slug)
    src = _resolve_relative(root, src_path)
    dest = _resolve_relative(root, dest_path)
    if not src.exists():
        raise SkillStudioFileError(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"源路径不存在：{src_path}",
        )
    if _is_root_skill_md(service, root, src):
        raise SkillStudioFileError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SKILL.md 是技能标识文件，不能移动或重命名",
        )
    if dest.exists() or dest.is_symlink():
        raise SkillStudioFileError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"目标路径已存在：{dest_path}",
        )
    if src.is_dir():
        try:
            dest.relative_to(src)
        except ValueError:
            pass
        else:
            raise SkillStudioFileError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能把文件夹移动到它自身内部",
            )
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(src), str(dest))
    except OSError as exc:
        logger.exception(
            "Failed to move skill path %s/%s -> %s", slug, src_path, dest_path
        )
        raise SkillStudioFileError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"移动失败：{exc}",
        ) from exc
    return {
        "slug": slug,
        "from": src_path.replace("\\", "/").lstrip("/"),
        "to": dest_path.replace("\\", "/").lstrip("/"),
    }
