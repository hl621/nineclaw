"""Tests for WebSearch deploy helpers."""

from __future__ import annotations

from app.api.routes.web_sources import _websearch_deploy_config, _websearch_deploy_env
from app.services.nineclaw_bootstrap import build_dashboard_base_url


def test_websearch_deploy_env_uses_traefik_bridge(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "public_traefik_url", "")
    monkeypatch.setattr(settings, "manager_traefik_url", "")
    monkeypatch.setattr(settings, "traefik_internal_url", "http://traefik:80/")

    env = _websearch_deploy_env(["bing", "baidu_news"])

    assert env["HERMES_ENABLE_PROJECT_PLUGINS"] == "1"
    assert env["NINECLAW_WEBSEARCH_BASE_URL"] == "http://traefik:80/ws-api"
    assert env["NINECLAW_WEBSEARCH_INCLUDE_SOURCES"] == "bing,baidu_news"


def test_websearch_deploy_env_prefers_public_traefik_url(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "public_traefik_url", "http://127.0.0.1:8510/")
    monkeypatch.setattr(settings, "manager_traefik_url", "")
    monkeypatch.setattr(settings, "traefik_internal_url", "http://traefik:80/")

    env = _websearch_deploy_env(["bing"])

    assert env["NINECLAW_WEBSEARCH_BASE_URL"] == "http://127.0.0.1:8510/ws-api"


def test_dashboard_base_url_prefers_manager_traefik_url(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "public_traefik_url", "http://127.0.0.1:8510/")
    monkeypatch.setattr(settings, "manager_traefik_url", "http://traefik:80/")
    monkeypatch.setattr(settings, "traefik_internal_url", "http://traefik:80/")

    assert (
        build_dashboard_base_url("abc")
        == "http://traefik:80/traefik/nineclaw/abc/dashboard"
    )


def test_websearch_deploy_config_sets_nineclaw_web_backend() -> None:
    config = _websearch_deploy_config(
        {
            "model": {"provider": "custom"},
            "web": {
                "backend": "default",
                "search_backend": "default",
                "extract_backend": "default",
                "use_gateway": True,
                "timeout": 30,
            },
            "toolsets": ["existing", "web"],
        }
    )

    assert config["model"] == {"provider": "custom"}
    assert config["toolsets"] == ["existing", "web", "hermes-cli"]
    assert config["web"] == {
        "backend": "nineclaw",
        "search_backend": "nineclaw",
        "extract_backend": "nineclaw",
        "use_gateway": False,
        "timeout": 30,
    }
