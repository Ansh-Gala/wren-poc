import json
from dataclasses import replace

import pytest

from llm_api.cli_provider import build_command, parse_stream_json

# The MCP path is optional: a lean-only deployment ships no wren_setup. Only
# the cases that exercise MCP configuration and tool allowlists depend on it,
# so they carry @needs_mcp and skip there. The stream-parser and
# command-builder cases in this file run everywhere, which is the point --
# they cover code that answers every question.
try:
    from wren_setup.mcp_config import (
        DISALLOWED_TOOLS, allowed_tools, write_mcp_config,
    )
except ModuleNotFoundError:
    DISALLOWED_TOOLS = allowed_tools = write_mcp_config = None

needs_mcp = pytest.mark.skipif(
    write_mcp_config is None,
    reason="wren_setup is not shipped in a lean-only deployment",
)


@needs_mcp
def test_command_is_headless_and_strict(tmp_settings, tmp_path):
    cmd = build_command("Show all users", tmp_path / "mcp.json", "strict", tmp_settings)
    assert "-p" in cmd
    assert "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in cmd


@needs_mcp
def test_command_always_disallows_row_returning_tools(tmp_settings, tmp_path):
    for mode in ("strict", "validated"):
        cmd = build_command("q", tmp_path / "mcp.json", mode, tmp_settings)
        tail = cmd[cmd.index("--disallowedTools") + 1:]
        for tool in DISALLOWED_TOOLS:
            assert tool in tail, f"{tool} not denied in {mode}"


# Both paths, because a secret leaking into argv is not less bad on the one
# this deployment happens not to use. The lean case is the one production runs,
# so it is the case that must never be the skipped one.
LEAN_MODES = [
    pytest.param(True, id="lean"),
    pytest.param(False, id="mcp", marks=needs_mcp),
]


@pytest.mark.parametrize("lean", LEAN_MODES)
def test_command_carries_no_api_key(tmp_settings, tmp_path, lean):
    settings = replace(tmp_settings, cli_lean=lean)
    joined = " ".join(build_command("q", tmp_path / "m.json", "strict", settings))
    assert "ANTHROPIC" not in joined.upper()


@pytest.mark.parametrize("lean", LEAN_MODES)
def test_command_never_contains_database_password(tmp_settings, tmp_path, lean):
    settings = replace(tmp_settings, cli_lean=lean)
    joined = " ".join(build_command("q", tmp_path / "m.json", "validated", settings))
    assert settings.pg_password not in joined
    assert settings.pg_readonly_password not in joined


@needs_mcp
def test_allowlist_and_denylist_do_not_overlap():
    for mode in ("strict", "validated"):
        assert not set(allowed_tools(mode)) & set(DISALLOWED_TOOLS)


@needs_mcp
def test_dry_run_only_offered_when_wren_is_connected():
    assert "mcp__wren__dry_run" not in allowed_tools("strict")
    assert "mcp__wren__dry_run" in allowed_tools("validated")


@needs_mcp
def test_strict_mode_passes_no_connect(tmp_settings):
    cfg = json.loads(write_mcp_config("D", "strict", tmp_settings).read_text())
    args = cfg["mcpServers"]["wren"]["args"]
    assert "serve" in args and "mcp" in args
    assert "--no-connect" in args


@needs_mcp
def test_validated_mode_omits_no_connect(tmp_settings):
    cfg = json.loads(write_mcp_config("D", "validated", tmp_settings).read_text())
    assert "--no-connect" not in cfg["mcpServers"]["wren"]["args"]


@needs_mcp
def test_config_env_isolates_project_and_memory(tmp_settings):
    a = json.loads(write_mcp_config("A", "strict", tmp_settings).read_text())
    d = json.loads(write_mcp_config("D", "strict", tmp_settings).read_text())
    ea = a["mcpServers"]["wren"]["env"]
    ed = d["mcpServers"]["wren"]["env"]
    assert ea["WREN_PROJECT_HOME"] != ed["WREN_PROJECT_HOME"]
    assert ea["WREN_MEMORY_DIR"] != ed["WREN_MEMORY_DIR"]


@needs_mcp
def test_mcp_config_sets_utf8_for_windows(tmp_settings):
    cfg = json.loads(write_mcp_config("D", "strict", tmp_settings).read_text())
    assert cfg["mcpServers"]["wren"]["env"]["PYTHONUTF8"] == "1"


def test_parse_stream_json_collects_tools_and_result():
    stream = "\n".join(
        json.dumps(e)
        for e in [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "mcp__wren__get_mdl"},
                {"type": "tool_use", "name": "mcp__wren__recall_queries"},
            ]}},
            {"type": "result", "subtype": "success", "is_error": False,
             "result": '{"sql": "SELECT 1"}', "duration_ms": 4200,
             "total_cost_usd": 0.01, "session_id": "abc", "num_turns": 3},
        ]
    )
    run = parse_stream_json(stream)
    assert run.tools_used == ["mcp__wren__get_mdl", "mcp__wren__recall_queries"]
    assert "SELECT 1" in run.result_text
    assert run.cost_usd == 0.01
    assert run.session_id == "abc"
    assert run.ok


def test_parse_stream_json_survives_non_json_noise():
    run = parse_stream_json(
        'warning: something happened\n'
        '{"type":"result","is_error":false,"result":"SELECT 1","duration_ms":10}'
    )
    assert run.result_text == "SELECT 1"
    assert run.ok


def test_parse_stream_json_records_mcp_tool_errors():
    stream = "\n".join(
        json.dumps(e)
        for e in [
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "is_error": True,
                 "content": "wren: model 'orders' not found"},
            ]}},
            {"type": "result", "is_error": False, "result": "SELECT 1",
             "duration_ms": 5},
        ]
    )
    run = parse_stream_json(stream)
    assert run.mcp_errors and "orders" in run.mcp_errors[0]


def test_parse_stream_json_marks_error_results():
    run = parse_stream_json(
        '{"type":"result","is_error":true,"subtype":"error_max_turns",'
        '"result":"","duration_ms":9}'
    )
    assert not run.ok
    assert run.error == "error_max_turns"


def test_parse_stream_json_on_empty_output():
    run = parse_stream_json("")
    assert not run.ok
    assert run.tools_used == []
