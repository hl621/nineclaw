"""Integration tests for HermesService against a live Hermes dashboard.

Target: http://127.0.0.1:33002

Run with:
    pytest tests/test_hermes_service.py -v

All tests hit the real Hermes instance. They are read-heavy by design so they
don't mutate production state. The few write tests (cron, env, config, skills)
clean up after themselves.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.services.hermes_dashboard_service import HermesError, HermesService

HERMES_URL = "http://127.0.0.1:33002"
HERMES_TOKEN = "sk-qiyuan"


# ─── Shared fixture ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def svc():
    """A connected HermesService pointed at the live dashboard."""
    async with HermesService(base_url=HERMES_URL, api_key=HERMES_TOKEN) as client:
        yield client


# ─── Status ───────────────────────────────────────────────────────────────────


class TestStatus:
    """GET /api/status"""

    @pytest.mark.asyncio
    async def test_get_status_returns_dict(self, svc: HermesService):
        result = await svc.get_status()
        assert isinstance(result, dict), "Expected a dict response"

    @pytest.mark.asyncio
    async def test_get_status_has_expected_keys(self, svc: HermesService):
        result = await svc.get_status()
        # Hermes always returns at least one of these top-level keys
        known_keys = {"version", "gateway", "platform", "sessions", "status", "agent"}
        assert known_keys & result.keys(), (
            f"None of the expected keys found. Got: {list(result.keys())}"
        )


# ─── Sessions ─────────────────────────────────────────────────────────────────


class TestSessions:
    """GET /api/sessions and related endpoints"""

    @pytest.mark.asyncio
    async def test_get_sessions_returns_dict(self, svc: HermesService):
        result = await svc.get_sessions()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_sessions_has_sessions_key(self, svc: HermesService):
        result = await svc.get_sessions()
        assert "sessions" in result
        assert isinstance(result["sessions"], list)

    @pytest.mark.asyncio
    async def test_get_sessions_has_pagination_keys(self, svc: HermesService):
        result = await svc.get_sessions()
        for key in ("total", "limit", "offset"):
            assert key in result, f"Missing pagination key: {key}"

    @pytest.mark.asyncio
    async def test_get_session_single(self, svc: HermesService):
        result = await svc.get_sessions()
        sessions = result.get("sessions", [])
        if not sessions:
            pytest.skip("No sessions available to test get_session()")
        session_id = sessions[0]["id"]
        detail = await svc.get_session(session_id)
        assert isinstance(detail, dict)
        assert detail.get("id") == session_id

    @pytest.mark.asyncio
    async def test_get_session_not_found_raises(self, svc: HermesService):
        with pytest.raises(HermesError) as exc_info:
            await svc.get_session("nonexistent-session-id-00000000")
        assert exc_info.value.status_code in (404, 400)

    @pytest.mark.asyncio
    async def test_get_session_messages(self, svc: HermesService):
        result = await svc.get_sessions()
        sessions = result.get("sessions", [])
        if not sessions:
            pytest.skip("No sessions available to test get_session_messages()")
        session_id = sessions[0]["id"]
        messages = await svc.get_session_messages(session_id)
        assert isinstance(messages, list)

    @pytest.mark.asyncio
    async def test_search_sessions_returns_dict(self, svc: HermesService):
        result = await svc.search_sessions(q="the")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_search_sessions_has_results_key(self, svc: HermesService):
        result = await svc.search_sessions(q="the")
        assert "results" in result
        assert isinstance(result["results"], list)

    @pytest.mark.asyncio
    async def test_search_sessions_empty_query(self, svc: HermesService):
        result = await svc.search_sessions(q="")
        assert isinstance(result, dict)
        assert "results" in result


# ─── Config ───────────────────────────────────────────────────────────────────


class TestConfig:
    """GET /api/config and related endpoints"""

    @pytest.mark.asyncio
    async def test_get_config_returns_dict(self, svc: HermesService):
        result = await svc.get_config()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_config_defaults_returns_dict(self, svc: HermesService):
        result = await svc.get_config_defaults()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_config_schema_returns_dict(self, svc: HermesService):
        result = await svc.get_config_schema()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_put_config_roundtrip(self, svc: HermesService):
        """Read current config, write it back unchanged, verify no error."""
        current = await svc.get_config()
        result = await svc.put_config(current)
        # Hermes typically echoes the saved config or returns {"ok": true}
        assert isinstance(result, dict)


# ─── Environment Variables ────────────────────────────────────────────────────


class TestEnv:
    """GET/PUT/DELETE /api/env"""

    _TEST_KEY = "KIRO_HERMES_TEST_VAR"
    _TEST_VALUE = "kiro_integration_test"

    @pytest.mark.asyncio
    async def test_get_env_returns_dict(self, svc: HermesService):
        # Response is a dict keyed by variable name
        result = await svc.get_env()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_env_values_have_metadata(self, svc: HermesService):
        result = await svc.get_env()
        # Each value is a schema dict — check for known metadata fields
        for var_name, meta in result.items():
            assert isinstance(meta, dict), f"{var_name} value is not a dict"
            known_fields = {"description", "category", "is_password", "advanced", "set"}
            assert known_fields & meta.keys(), (
                f"{var_name} has no recognised metadata fields, got: {list(meta.keys())}"
            )
            break  # checking one entry is enough

    @pytest.mark.asyncio
    async def test_put_and_delete_env(self, svc: HermesService):
        """Verify put_env and delete_env complete without error.

        Hermes /api/env returns a static schema dict (variable definitions),
        not live values — so we can't verify the written value via GET.
        We just confirm both operations return 200 without raising.
        """
        env = await svc.get_env()
        if not env:
            pytest.skip("No env variables available")

        # Pick the first non-password key that's safe to touch
        target_key = next(
            (k for k, meta in env.items() if not meta.get("is_password", True)),
            None,
        )
        if target_key is None:
            pytest.skip("No safe non-password env variable found")

        # Both operations should succeed without raising HermesError
        await svc.put_env(target_key, "kiro_test_value")
        await svc.delete_env(target_key)


# ─── Logs ─────────────────────────────────────────────────────────────────────


class TestLogs:
    """GET /api/logs"""

    @pytest.mark.asyncio
    async def test_get_logs_returns_dict(self, svc: HermesService):
        result = await svc.get_logs()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_logs_has_lines_key(self, svc: HermesService):
        result = await svc.get_logs()
        assert "lines" in result
        assert isinstance(result["lines"], list)

    @pytest.mark.asyncio
    async def test_get_logs_with_lines_param(self, svc: HermesService):
        result = await svc.get_logs(lines=10)
        assert isinstance(result, dict)
        assert len(result.get("lines", [])) <= 10

    @pytest.mark.asyncio
    async def test_get_logs_agent_file(self, svc: HermesService):
        result = await svc.get_logs(file="agent")
        assert isinstance(result, dict)
        assert result.get("file") == "agent"

    @pytest.mark.asyncio
    async def test_get_logs_errors_file(self, svc: HermesService):
        result = await svc.get_logs(file="errors")
        assert isinstance(result, dict)
        assert result.get("file") == "errors"

    @pytest.mark.asyncio
    async def test_get_logs_gateway_file(self, svc: HermesService):
        result = await svc.get_logs(file="gateway")
        assert isinstance(result, dict)
        assert result.get("file") == "gateway"


# ─── Analytics ────────────────────────────────────────────────────────────────


class TestAnalytics:
    """GET /api/analytics/usage"""

    @pytest.mark.asyncio
    async def test_get_usage_analytics_default(self, svc: HermesService):
        result = await svc.get_usage_analytics()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_usage_analytics_custom_days(self, svc: HermesService):
        result = await svc.get_usage_analytics(days=7)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_usage_analytics_single_day(self, svc: HermesService):
        result = await svc.get_usage_analytics(days=1)
        assert isinstance(result, dict)


# ─── Cron Jobs ────────────────────────────────────────────────────────────────


class TestCronJobs:
    """Full CRUD cycle for /api/cron/jobs"""

    @pytest.mark.asyncio
    async def test_get_cron_jobs_returns_list(self, svc: HermesService):
        result = await svc.get_cron_jobs()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_cron_job_lifecycle(self, svc: HermesService):
        """Create → pause → resume → trigger → delete."""
        # Create
        job = await svc.create_cron_job(
            prompt="Say hello",
            schedule="0 0 1 1 *",  # once a year — won't fire during tests
            name="kiro-test-job",
            deliver="local",
        )
        assert isinstance(job, dict)
        job_id = job.get("id") or job.get("job_id")
        assert job_id, f"No job id in response: {job}"

        try:
            # Pause
            paused = await svc.pause_cron_job(job_id)
            assert isinstance(paused, dict)

            # Resume
            resumed = await svc.resume_cron_job(job_id)
            assert isinstance(resumed, dict)

            # Trigger
            triggered = await svc.trigger_cron_job(job_id)
            assert isinstance(triggered, dict)

        finally:
            # Always clean up
            await svc.delete_cron_job(job_id)

        # Verify deletion
        jobs = await svc.get_cron_jobs()
        ids = [j.get("id") or j.get("job_id") for j in jobs]
        assert job_id not in ids, "Job still present after delete_cron_job"


# ─── Skills ───────────────────────────────────────────────────────────────────


class TestSkills:
    """GET /api/skills and PUT /api/skills/toggle"""

    @pytest.mark.asyncio
    async def test_get_skills_returns_list(self, svc: HermesService):
        result = await svc.get_skills()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_skills_items_have_name(self, svc: HermesService):
        result = await svc.get_skills()
        for item in result:
            assert "name" in item, f"Skill item missing 'name': {item}"

    @pytest.mark.asyncio
    async def test_toggle_skill_roundtrip(self, svc: HermesService):
        """Flip a skill's enabled state then restore it."""
        skills = await svc.get_skills()
        if not skills:
            pytest.skip("No skills available to test toggle_skill()")

        skill = skills[0]
        name = skill["name"]
        original_state: bool = skill.get("enabled", True)

        # Toggle off (or on)
        await svc.toggle_skill(name, not original_state)

        # Restore
        await svc.toggle_skill(name, original_state)

        # Verify restored
        updated = await svc.get_skills()
        for s in updated:
            if s["name"] == name:
                assert s.get("enabled") == original_state
                break


# ─── Toolsets ─────────────────────────────────────────────────────────────────


class TestToolsets:
    """GET /api/tools/toolsets"""

    @pytest.mark.asyncio
    async def test_get_toolsets_returns_list(self, svc: HermesService):
        result = await svc.get_toolsets()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_toolsets_items_have_label(self, svc: HermesService):
        result = await svc.get_toolsets()
        for item in result:
            assert "label" in item or "name" in item, (
                f"Toolset item missing 'label'/'name': {item}"
            )
