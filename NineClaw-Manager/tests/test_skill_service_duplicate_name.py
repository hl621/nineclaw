"""Tests for SkillService duplicate-name handling.

create_skill must strictly reject a name whose slug already exists,
returning 409 instead of silently picking a ``-2``/``-3`` suffix.
"""

import pytest

from app.services.skill_service import SkillError, SkillService


def _service(tmp_path) -> SkillService:
    return SkillService(storage_root=tmp_path, max_upload_size=10 * 1024 * 1024)


class TestCreateSkillDuplicateName:
    def test_first_create_succeeds(self, tmp_path):
        svc = _service(tmp_path)
        record = svc.create_skill("my-skill", "first skill")
        assert record["id"] == "my-skill"
        assert record["name"] == "my-skill"
        assert (tmp_path / "my-skill" / "SKILL.md").is_file()

    def test_duplicate_name_is_rejected_with_409(self, tmp_path):
        svc = _service(tmp_path)
        svc.create_skill("my-skill", "first skill")

        with pytest.raises(SkillError) as exc:
            svc.create_skill("my-skill", "another skill with same name")
        assert exc.value.status_code == 409
        assert "my-skill" in exc.value.detail
        # No -2/-3 suffix directory should have been created.
        assert not (tmp_path / "my-skill-2").exists()
        assert not (tmp_path / "my-skill-3").exists()

    def test_identical_name_after_slug_normalization_collides(self, tmp_path):
        # slugify replaces forbidden chars with "-" and strips trailing dots;
        # two names that normalize to the same slug must collide.
        svc = _service(tmp_path)
        svc.create_skill("my skill", "desc")
        # "my skill" and "my skill" map to the same slug "my skill"
        with pytest.raises(SkillError) as exc:
            svc.create_skill("my skill", "desc")
        assert exc.value.status_code == 409

    def test_different_names_coexist(self, tmp_path):
        svc = _service(tmp_path)
        svc.create_skill("alpha", "desc")
        svc.create_skill("beta", "desc")
        assert (tmp_path / "alpha").is_dir()
        assert (tmp_path / "beta").is_dir()
