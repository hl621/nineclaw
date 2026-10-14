"""Tests that SkillService tolerates case variants of ``SKILL.md`` /
``README.md`` (``skill.md`` / ``SKILL.MD`` / ``Skill.Md`` …) both in zip
uploads and for skills already on disk, and normalizes extracted files to
the canonical names.
"""

import io
import zipfile

from app.services.skill_service import SkillService

SKILL_MD_BODY = """---
name: Case Skill
description: a skill whose SKILL.md was cased wrongly
---

Body text.
"""


def _service(tmp_path) -> SkillService:
    return SkillService(storage_root=tmp_path, max_upload_size=10 * 1024 * 1024)


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


class TestSkillMdCaseVariants:
    def test_zip_upload_accepts_lowercase_skill_md(self, tmp_path):
        svc = _service(tmp_path)
        record = svc.save_zip_upload(
            _zip_bytes({"skill.md": SKILL_MD_BODY}), overwrite=True
        )
        assert record["name"] == "Case Skill"
        installed_dir = tmp_path / record["id"]
        # Normalized to the canonical name regardless of the zip casing.
        assert "SKILL.md" in {p.name for p in installed_dir.iterdir()}

    def test_zip_upload_accepts_uppercase_extension_and_readme_variant(
        self, tmp_path
    ):
        svc = _service(tmp_path)
        record = svc.save_zip_upload(
            _zip_bytes({"SKILL.MD": SKILL_MD_BODY, "Readme.md": "readme"}),
            overwrite=True,
        )
        installed_dir = tmp_path / record["id"]
        names = {p.name for p in installed_dir.iterdir()}
        assert "SKILL.md" in names
        assert "README.md" in names
        assert record["has_readme"] is True

    def test_detect_skills_in_zip_case_variant_in_subdir(self, tmp_path):
        svc = _service(tmp_path)
        detected = svc.detect_skills_in_zip(
            _zip_bytes({"bundle/Skill.Md": SKILL_MD_BODY})
        )
        assert len(detected) == 1
        assert detected[0]["error"] is None

    def test_list_skills_finds_case_variant_on_disk(self, tmp_path):
        svc = _service(tmp_path)
        skill_dir = tmp_path / "variant-skill"
        skill_dir.mkdir()
        (skill_dir / "Skill.md").write_text(SKILL_MD_BODY, encoding="utf-8")
        listed = svc.list_skills()
        assert [s["id"] for s in listed] == ["variant-skill"]
        assert listed[0]["name"] == "Case Skill"
