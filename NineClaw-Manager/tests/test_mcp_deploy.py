"""Tests for MCP deployment helpers."""

from types import SimpleNamespace

from app.api.routes.mcp_servers import (
    _build_hermes_mcp_entry,
    _format_gateway_restart_failure,
    _is_sse_url,
    _normalize_stdio_args,
    _merge_hermes_mcp_servers,
    _merge_discovered_tool_settings,
    _set_tool_enabled,
)
from app.services.instance_setup_service import (
    _build_hermes_mcp_entry as _build_hermes_mcp_entry_setup,
)
from app.services.instance_setup_service import (
    _is_sse_url as _is_sse_url_setup,
)


def _url_server(url: str) -> SimpleNamespace:
    return SimpleNamespace(
        transport="url",
        url=url,
        headers={},
        timeout=None,
        connect_timeout=None,
        enabled=True,
        tools=None,
        tool_settings=None,
    )


def test_merge_hermes_mcp_servers_overwrites_selected_names():
    merged, updated = _merge_hermes_mcp_servers(
        {
            "github": {"url": "https://old.example/mcp"},
            "filesystem": {"command": "npx", "args": ["old"]},
        },
        {
            "github": {"url": "https://new.example/mcp"},
            "linear": {"url": "https://linear.example/mcp"},
        },
    )

    assert updated == ["github"]
    assert merged == {
        "github": {"url": "https://new.example/mcp"},
        "filesystem": {"command": "npx", "args": ["old"]},
        "linear": {"url": "https://linear.example/mcp"},
    }


def test_merge_hermes_mcp_servers_treats_invalid_existing_as_empty():
    merged, updated = _merge_hermes_mcp_servers(
        [],
        {"github": {"url": "https://new.example/mcp"}},
    )

    assert updated == []
    assert merged == {"github": {"url": "https://new.example/mcp"}}


def test_normalize_stdio_args_splits_shell_like_lines():
    assert _normalize_stdio_args(["-y @amap/amap-maps-mcp-server"]) == [
        "-y",
        "@amap/amap-maps-mcp-server",
    ]


def test_normalize_stdio_args_preserves_quoted_spaces():
    assert _normalize_stdio_args(['--label "foo bar"', "--enabled"]) == [
        "--label",
        "foo bar",
        "--enabled",
    ]


def test_build_hermes_url_mcp_entry_disables_sampling_by_default():
    entry = _build_hermes_mcp_entry(
        SimpleNamespace(
            transport="url",
            url="https://mcp.example.com/mcp",
            headers={},
            timeout=None,
            connect_timeout=None,
            enabled=True,
            tools=None,
            tool_settings=None,
        )
    )

    assert entry == {
        "url": "https://mcp.example.com/mcp",
        "sampling": {"enabled": False},
    }


def test_is_sse_url_detects_sse_endpoints():
    assert _is_sse_url("http://172.24.122.72:18082/sse") is True
    assert _is_sse_url("http://host/sse/") is True
    assert _is_sse_url("http://host/sse?token=abc") is True
    assert _is_sse_url("http://host/SSE") is True
    assert _is_sse_url("https://mcp.amap.com/mcp?key=x") is False
    assert _is_sse_url("http://host/sse-extra") is False
    assert _is_sse_url("") is False
    assert _is_sse_url(None) is False


def test_is_sse_url_setup_variant_matches_route_helper():
    for url in (
        "http://172.24.122.72:18082/sse",
        "http://host/sse/",
        "http://host/sse?token=abc",
        "https://mcp.amap.com/mcp?key=x",
        "http://host/sse-extra",
        "",
        None,
    ):
        assert _is_sse_url_setup(url) == _is_sse_url(url)


def test_build_hermes_url_mcp_entry_declares_sse_transport():
    entry = _build_hermes_mcp_entry(_url_server("http://172.24.122.72:18082/sse"))
    assert entry == {
        "url": "http://172.24.122.72:18082/sse",
        "sampling": {"enabled": False},
        "transport": "sse",
    }


def test_build_hermes_url_mcp_entry_no_transport_for_streamable_http():
    entry = _build_hermes_mcp_entry(_url_server("https://mcp.amap.com/mcp?key=x"))
    assert "transport" not in entry


def test_build_hermes_stdio_entry_has_no_transport():
    entry = _build_hermes_mcp_entry(
        SimpleNamespace(
            transport="stdio",
            command="npx",
            args=["-y", "some-mcp"],
            env={},
            url="",
            headers={},
            timeout=None,
            connect_timeout=None,
            enabled=True,
            tools=None,
            tool_settings=None,
        )
    )
    assert "transport" not in entry
    assert entry["command"] == "npx"


def test_build_hermes_mcp_entry_setup_declares_sse_transport_too():
    entry = _build_hermes_mcp_entry_setup(_url_server("http://host:18082/sse/"))
    assert entry["transport"] == "sse"
    entry_plain = _build_hermes_mcp_entry_setup(_url_server("https://x.example/mcp"))
    assert "transport" not in entry_plain


def test_merge_discovered_tool_settings_preserves_disabled_tools():
    settings = _merge_discovered_tool_settings(
        {"maps_weather": False},
        [{"name": "maps_weather"}, {"name": "maps_geo"}],
    )

    assert settings == {"maps_weather": False, "maps_geo": True}


def test_set_tool_enabled_returns_new_settings_dict():
    original = {"maps_weather": True}

    updated = _set_tool_enabled(original, "maps_weather", False)

    assert updated == {"maps_weather": False}
    assert original == {"maps_weather": True}
    assert updated is not original


def test_format_gateway_restart_failure_includes_exit_code_and_log_tail():
    message = _format_gateway_restart_failure(
        "gateway-restart",
        {
            "exit_code": 1,
            "lines": ["line 1", "line 2", "line 3", "line 4", "line 5", "line 6"],
        },
    )

    assert "Gateway 重启失败 (gateway-restart, exit_code=1)" in message
    assert "line 1" not in message
    assert "line 2" in message
    assert "line 6" in message
