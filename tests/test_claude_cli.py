import json

from llm_api.cli_provider import build_command, parse_stream_json
from wren_setup.mcp_config import DISALLOWED_TOOLS, allowed_tools, write_mcp_config


def test_command_is_headless_and_strict(tmp_settings, tmp_path):
    cmd = build_command("Show all users", tmp_path / "mcp.json", "strict", tmp_settings)
    assert "-p" in cmd
    assert "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in cmd


def test_command_always_disallows_row_returning_tools(tmp_settings, tmp_path):
    for mode in ("strict", "validated"):
        cmd = build_command("q", tmp_path / "mcp.json", mode, tmp_settings)
        tail = cmd[cmd.index("--disallowedTools") + 1:]
        for tool in DISALLOWED_TOOLS:
            assert tool in tail, f"{tool} not denied in {mode}"


def test_command_carries_no_api_key(tmp_settings, tmp_path):
    joined = " ".join(build_command("q", tmp_path / "m.json", "strict", tmp_settings))
    assert "ANTHROPIC" not in joined.upper()


def test_command_never_contains_database_password(tmp_settings, tmp_path):
    joined = " ".join(build_command("q", tmp_path / "m.json", "validated", tmp_settings))
    assert tmp_settings.pg_password not in joined
    assert tmp_settings.pg_readonly_password not in joined


def test_allowlist_and_denylist_do_not_overlap():
    for mode in ("strict", "validated"):
        assert not set(allowed_tools(mode)) & set(DISALLOWED_TOOLS)


def test_dry_run_only_offered_when_wren_is_connected():
    assert "mcp__wren__dry_run" not in allowed_tools("strict")
    assert "mcp__wren__dry_run" in allowed_tools("validated")


def test_strict_mode_passes_no_connect(tmp_settings):
    cfg = json.loads(write_mcp_config("D", "strict", tmp_settings).read_text())
    args = cfg["mcpServers"]["wren"]["args"]
    assert "serve" in args and "mcp" in args
    assert "--no-connect" in args


def test_validated_mode_omits_no_connect(tmp_settings):
    cfg = json.loads(write_mcp_config("D", "validated", tmp_settings).read_text())
    assert "--no-connect" not in cfg["mcpServers"]["wren"]["args"]


def test_config_env_isolates_project_and_memory(tmp_settings):
    a = json.loads(write_mcp_config("A", "strict", tmp_settings).read_text())
    d = json.loads(write_mcp_config("D", "strict", tmp_settings).read_text())
    ea = a["mcpServers"]["wren"]["env"]
    ed = d["mcpServers"]["wren"]["env"]
    assert ea["WREN_PROJECT_HOME"] != ed["WREN_PROJECT_HOME"]
    assert ea["WREN_MEMORY_DIR"] != ed["WREN_MEMORY_DIR"]


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
