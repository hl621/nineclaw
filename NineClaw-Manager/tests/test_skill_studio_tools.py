from __future__ import annotations

import json

from app.services.skill_studio_tools import SkillManageToolkit, validate_skill_content


VALID_SKILL = """---
name: demo-skill
description: Use for demonstrating Skill Studio management.
---

# Demo

Follow the requested workflow.
"""


def call(toolkit: SkillManageToolkit, **kwargs):
    return json.loads(toolkit.skill_manage(**kwargs))


def test_validate_skill_content_rejects_invalid_frontmatter() -> None:
    result = validate_skill_content("# Missing frontmatter")

    assert result["valid"] is False
    assert "frontmatter" in result["errors"][0]


def test_patch_requires_read_and_unique_match(tmp_path) -> None:
    (tmp_path / "SKILL.md").write_text(VALID_SKILL, encoding="utf-8")
    toolkit = SkillManageToolkit(tmp_path)

    rejected = call(
        toolkit,
        action="patch",
        old_text="Demo",
        new_text="Example",
    )
    assert rejected["success"] is False
    assert "必须先" in rejected["error"]

    assert call(toolkit, action="read")["success"] is True
    ambiguous = call(
        toolkit,
        action="patch",
        old_text="e",
        new_text="E",
    )
    assert ambiguous["success"] is False
    assert ambiguous["matches"] > 1

    patched = call(
        toolkit,
        action="patch",
        old_text="# Demo",
        new_text="# Example",
    )
    assert patched["success"] is True
    assert "# Example" in (tmp_path / "SKILL.md").read_text(encoding="utf-8")


def test_invalid_skill_edit_rolls_back_without_touching_file(tmp_path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(VALID_SKILL, encoding="utf-8")
    toolkit = SkillManageToolkit(tmp_path)
    call(toolkit, action="read")

    result = call(toolkit, action="edit", content="invalid")

    assert result["success"] is False
    assert skill_md.read_text(encoding="utf-8") == VALID_SKILL


def test_new_support_file_must_use_standard_directory(tmp_path) -> None:
    (tmp_path / "SKILL.md").write_text(VALID_SKILL, encoding="utf-8")
    toolkit = SkillManageToolkit(tmp_path)

    rejected = call(
        toolkit,
        action="write_file",
        file_path="notes.md",
        content="notes",
    )
    accepted = call(
        toolkit,
        action="write_file",
        file_path="references/notes.md",
        content="notes",
    )

    assert rejected["success"] is False
    assert accepted["success"] is True
    assert (tmp_path / "references" / "notes.md").read_text(encoding="utf-8") == "notes"


def test_path_traversal_is_rejected(tmp_path) -> None:
    (tmp_path / "SKILL.md").write_text(VALID_SKILL, encoding="utf-8")
    toolkit = SkillManageToolkit(tmp_path)

    result = call(toolkit, action="read", file_path="../outside.txt")

    assert result["success"] is False
    assert "路径" in result["error"]
