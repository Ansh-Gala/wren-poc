"""Serve the pipeline over HTTP, so the QA console can ask real questions.

    python scripts/serve_api.py
    python scripts/serve_api.py --port 8000 --context-mode state

Then open http://localhost:8000/ -- the console is served from here too, which
keeps it same-origin and means there is no CORS to think about.

There is no second pipeline. Every request goes through benchmark.lean_runner
.run_turn, the same function the four benchmark suites run, with no expected
SQL to compare against. That is the whole design: a console that exercised its
own copy of the logic would drift from the thing being measured, and would
then be showing you something other than what the benchmark says.

Deliberately no web framework. This is a local debugging tool for one person
at a time, and http.server is in the standard library, so the dependency list
stays as short as the rest of the project's.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import _bootstrap  # noqa: F401

from benchmark.context import ConversationState
from benchmark.followup import ACTION_TYPES, Action, apply_action
from benchmark.lean_runner import TurnResult, load_gazetteer, run_turn
from benchmark.lean_suite import SuiteTurn
from benchmark.models import Session
from config.logging import get_logger, register_secrets
from config.settings import load_settings
from wren_setup.mcp_config import write_mcp_config

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"

log = get_logger("serve_api")


# --------------------------------------------------------------- sessions --

class Conversation:
    """One thread: its state, its transcript, and a lock.

    The lock matters because a turn takes seconds and mutates the state in
    place. Two overlapping requests on one session would interleave a repair,
    a classification and a state update, and the resulting context would belong
    to neither turn.
    """

    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.state = ConversationState()
        self.session = Session(session_id=session_id, turns=[])
        self.lock = threading.Lock()
        self.turn_index = 0

    def reset(self) -> None:
        self.state = ConversationState()
        self.session = Session(session_id=self.id, turns=[])
        self.turn_index = 0


SESSIONS: dict[str, Conversation] = {}
SESSIONS_LOCK = threading.Lock()


def conversation_for(session_id: str) -> Conversation:
    with SESSIONS_LOCK:
        if session_id not in SESSIONS:
            SESSIONS[session_id] = Conversation(session_id)
        return SESSIONS[session_id]


# ------------------------------------------------------------ state shape --

def state_snapshot(state: ConversationState) -> dict:
    """The conversation state as the console's right-hand rail renders it."""
    return {
        "entity": state.active_entity,
        "tables": list(state.active_tables),
        "filters": dict(state.active_filters),
        "grouping": list(state.active_grouping),
        "sorting": state.active_sorting,
        "limit": state.active_limit,
        "intent": state.last_intent,
        "previous_sql": state.previous_sql,
        "turns_in_block": state.turns_in_block,
        "pending_question": state.pending_question or None,
    }


def state_mutations(before: dict, after: dict) -> list[str]:
    """What this turn changed, in the words the rail uses.

    Computed by diffing rather than by recording as we go: the state is
    rewritten from the SQL that actually ran, so a claim about what changed is
    only trustworthy if it is read back off the result.
    """
    out: list[str] = []

    if before.get("entity") != after.get("entity"):
        out.append(f"subject {before.get('entity') or 'none'} -> "
                   f"{after.get('entity') or 'none'}")

    old_filters, new_filters = before.get("filters") or {}, after.get("filters") or {}
    for column in new_filters:
        if column not in old_filters:
            out.append(f"+ filter {new_filters[column]}")
        elif old_filters[column] != new_filters[column]:
            out.append(f"~ filter {old_filters[column]} -> {new_filters[column]}")
    for column in old_filters:
        if column not in new_filters:
            out.append(f"- filter {old_filters[column]}")

    for key, label in (("grouping", "grouped by"), ("sorting", "sorted by"),
                       ("limit", "limit"), ("intent", "intent")):
        if before.get(key) != after.get(key):
            out.append(f"{label} {before.get(key) or 'none'} -> "
                       f"{after.get(key) or 'none'}")

    return out


def to_response(r: TurnResult, asked: str, before: dict, after: dict) -> dict:
    """TurnResult -> the contract documented at the top of ui/api.js.

    result_match and semantic_match come through as None, which the console
    renders as "n/a". They are only meaningful against a known-correct answer,
    and a real question does not have one.
    """
    return {
        "decision": r.decision,
        "question": asked,
        "normalized_question": r.normalized_question,
        "repairs": r.repairs,
        "resumed_from": r.resumed_from,
        "preflight_clarified": r.preflight_clarified,

        "generated_sql": r.generated_sql,
        "sql_valid": r.sql_valid,
        "execution_success": r.execution_success,
        "error": r.error,
        "failure_category": r.failure_category,
        "result": r.actual_result,

        "semantic_match": r.semantic_match,
        "semantic_issues": r.semantic_issues,
        "projection_verdict": r.projection_verdict,
        "result_match": r.result_match,
        "schema_grounded": r.schema_grounded,
        "hallucinated": r.hallucinated,

        "clarification": r.clarification,
        "followup": r.followup or {"type": "none", "suggestions": []},

        "state": after,
        "state_mutations": state_mutations(before, after),

        "tokens": {
            "prompt": r.prompt_tokens,
            "cache_read": r.cache_read_tokens,
            "cache_write": r.cache_write_tokens,
            "completion": r.completion_tokens,
        },
        "latency_ms": r.latency_ms,
        "tool_calls": r.tool_call_count,
        "context_chars": r.context_chars,
        "raw_output": r.raw_output,
    }


# ------------------------------------------------------------------ asking --

def preflight(settings) -> None:
    """Fail at startup rather than three seconds into someone's first question.

    A misconfigured provider surfaces as an HTTP 500 carrying whatever the
    upstream said, which is a poor place to learn that .env still points at a
    model that was decommissioned. Checked once, here, where the message can
    say what to do about it.
    """
    if settings.llm_provider != "cli":
        raise SystemExit(
            f"LLM_PROVIDER is {settings.llm_provider!r}, not 'cli'.\n"
            "This project is only measured against the local Claude Code CLI; "
            "every benchmark figure on record was produced with it.\n"
            "Set LLM_PROVIDER=cli and CLI_LEAN=true in .env, or pass them for "
            "one run:\n"
            "  LLM_PROVIDER=cli CLI_LEAN=true python scripts/serve_api.py"
        )

    from llm_api.cli_provider import detect_claude
    if not detect_claude(settings.claude_command):
        raise SystemExit(
            f"Claude Code CLI not found (looked for {settings.claude_command!r} "
            "on PATH).\nInstall it from https://claude.com/claude-code, then "
            "run `claude --version` to confirm."
        )

    if not settings.cli_lean:
        # Not fatal -- the MCP path works -- but it is almost never what is
        # wanted here, and the difference is invisible until the token figures
        # come back three times larger.
        log.warning("CLI_LEAN is not set: using the MCP path, which needs "
                    "`wren serve mcp` running and costs ~3x the context. "
                    "Set CLI_LEAN=true for the mode the benchmarks used.")


class Runtime:
    """Everything a request needs that does not change between requests."""

    def __init__(self, args) -> None:
        self.settings = load_settings()
        register_secrets(self.settings.secrets())
        preflight(self.settings)
        self.gazetteer = load_gazetteer()
        self.mcp_config_path = write_mcp_config(args.config, args.privacy, self.settings)
        self.privacy = args.privacy
        self.context_mode = args.context_mode

        # Questions people actually type are the only source of test cases
        # nobody thought to write, and they were previously going to stderr and
        # dying with the terminal. Same filename the suites use, so
        # scripts/analyze_followup.py reads a console session unchanged.
        self.log_path = None
        if args.log:
            self.log_path = Path(args.log) / "raw" / "turns.jsonl"
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_lock = threading.Lock()

    def record(self, result, question: str, state: dict) -> None:
        if self.log_path is None:
            return
        row = asdict(result)
        row.update({
            "asked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "session_id": result.conversation_id,
            "typed": question,
            "state_after": state,
        })
        try:
            with self.log_lock, self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
        except OSError as exc:      # a full disk must not lose the answer
            log.warning("could not append to %s: %s", self.log_path, exc)

    def ask(self, payload: dict) -> dict:
        question = (payload.get("question") or "").strip()
        if not question:
            raise ValueError("question is required")

        conversation = conversation_for(payload.get("session_id") or "default")

        with conversation.lock:
            if payload.get("reset_context"):
                conversation.reset()

            # A clicked suggestion carries a structured action. Applying it
            # here means the context the model sees already reflects the
            # choice; the label still goes through as the question, so the
            # turn takes the ordinary path and there is no second way for a
            # query to be built.
            action = payload.get("action")
            if action and action.get("type") in ACTION_TYPES:
                try:
                    apply_action(conversation.state, Action(
                        type=action["type"],
                        field=action.get("field"),
                        operator=action.get("operator"),
                        value=action.get("value"),
                    ))
                except (ValueError, TypeError) as exc:
                    log.warning("ignoring unusable action %s: %s", action, exc)

            before = state_snapshot(conversation.state)

            turn = SuiteTurn(
                id=f"{conversation.id}.{conversation.turn_index}",
                question=question,
                expected_sql=None,          # no ground truth: this is a real question
                category="runtime",
                conversation_id=conversation.id,
                turn_index=conversation.turn_index,
            )
            result = run_turn(
                turn, conversation.state, self.gazetteer, self.settings,
                self.mcp_config_path, self.privacy, conversation.session,
                context_mode=self.context_mode,
            )
            conversation.turn_index += 1
            after = state_snapshot(conversation.state)
            self.record(result, question, after)

        log.info("  %-10s %-22s %s", result.decision,
                 result.failure_category or result.followup_type, question[:48])
        return to_response(result, question, before, after)


# ------------------------------------------------------------------- http --

class Handler(BaseHTTPRequestHandler):
    runtime: Runtime = None          # set in main()
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):   # quieter than the default
        pass

    # CORS is only needed for someone who opened ui/index.html straight off
    # disk. Served from here it is same-origin, which is why that is the
    # documented way to run it.
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")

    def _json(self, status: int, body: dict) -> None:
        raw = json.dumps(body, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/health":
            return self._json(200, {"ok": True, "sessions": len(SESSIONS)})

        name = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (UI_DIR / name).resolve()
        # Nothing outside ui/ is servable, whatever the path says.
        if not str(target).startswith(str(UI_DIR.resolve())) or not target.is_file():
            return self._json(404, {"error": f"no such file: {name}"})

        body = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")   # it is being edited
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/ask":
            return self._json(404, {"error": "POST /ask"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": f"bad request body: {exc}"})

        try:
            return self._json(200, self.runtime.ask(payload))
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        except Exception as exc:                      # a bad turn must not kill the server
            log.exception("turn failed")
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--config", default="D")
    ap.add_argument("--privacy", default="strict")
    ap.add_argument("--context-mode", default="state",
                    choices=["none", "history", "state"])
    ap.add_argument("--log", default="results/console",
                    help="directory to append every turn to as JSONL; "
                         "'' disables logging")
    args = ap.parse_args()

    Handler.runtime = Runtime(args)
    settings = Handler.runtime.settings
    mode = "lean (no MCP)" if settings.cli_lean else f"MCP config {args.config}"

    print(f"provider: {settings.llm_provider} / {settings.claude_model or 'default'}   {mode}")
    print(f"database: {settings.pg_database}   context mode: {args.context_mode}")
    print(f"gazetteer: {len(Handler.runtime.gazetteer)} entity value(s)")
    print()
    print(f"  console   http://{args.host}:{args.port}/")
    print(f"  endpoint  POST http://{args.host}:{args.port}/ask")
    if Handler.runtime.log_path:
        print(f"  log       {Handler.runtime.log_path}")
    print()
    print("Ctrl+C to stop.")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
