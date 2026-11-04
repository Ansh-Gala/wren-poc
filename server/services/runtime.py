"""Answering a question: who may ask, the turn itself, and what the
server reports about itself (/health, /info)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

from config.logging import get_logger, register_secrets
from config.settings import load_settings
from llm_api.factory import llm_identity
from pipeline.chat_store import ChatStore, safe_session_id
from pipeline.context import remember_question
from pipeline.context_pills import context_pills, drop_by_ref
from pipeline.evaluator import first_rows
from pipeline.followup import ACTION_TYPES, Action, apply_action, label_for_ref
from pipeline.identity_provider import resolve_identity
from pipeline.lean_runner import logged, run_turn
from pipeline.lean_suite import SuiteTurn
from pipeline.metadata import profile
from pipeline.pii import PiiError, PiiGuard, PiiVault, get_anonymizer
from pipeline.redact import public_response, safe_error
from pipeline.run_access import check_run, user_id_from

from server.config import (
    DEBUG_LOG_TURNS,
    LOCK_WAIT_SECONDS,
    PII_UNAVAILABLE,
    ROOT,
    TOKEN_LIMIT_MESSAGE,
)
from server.schemas import (
    displayed,
    pii_debug,
    pretty_sql,
    shown_result,
    state_snapshot,
    to_response,
    with_freshness,
)
from server.services.conversation import conversation_for
from server.utils import BadRequest, TokenLimitError

log = get_logger("serve_api")


# ------------------------------------------------------------------ asking --

def provider_problem(settings) -> str | None:
    """Why the configured LLM cannot answer, or None when it can."""
    # The transports Drupal offers: the local CLI, or one HTTPS call to an
    # API. An API needs only its key; the CLI needs to be installed.
    keys = {"anthropic": ("ANTHROPIC_API_KEY", settings.anthropic_api_key),
            "openai": ("OPENAI_API_KEY", settings.openai_api_key),
            "groq": ("GROQ_API_KEY", settings.openai_api_key),
            "gemini": ("GEMINI_API_KEY", settings.openai_api_key)}
    provider = settings.llm_provider
    if provider in keys:
        name, key = keys[provider]
        return None if key else f"LLM_PROVIDER is {provider!r} but {name} is not set in .env."
    if provider != "cli":
        return f"LLM_PROVIDER is {provider!r}. Use cli, anthropic, openai, groq or gemini."
    from llm_api.cli_provider import detect_claude
    if not detect_claude(settings.claude_command):
        return (f"Claude Code CLI not found (looked for {settings.claude_command!r} "
                "on PATH).\nInstall it from https://claude.com/claude-code, then "
                "run `claude --version` to confirm.")
    return None


def health(settings) -> dict:
    """GET /health, in the shape of Drupal's /api/sql-chat/health."""
    from database.connection import read_only_posture, run_readonly
    mode, vendor, model = llm_identity(settings)
    database = run_readonly(settings, "SELECT 1")
    posture = read_only_posture(settings)
    ready = provider_problem(settings) is None
    chats = ChatStore(settings, None).reachable() if settings.chats_configured else None
    return {
        "ok": database.ok and ready and posture["select_only"] and chats is not False,
        "provider": mode,
        # What is answering questions right now.
        "api_provider": vendor if mode == "api" else None,
        "model": model,
        "provider_ready": ready,
        "database": {
            "ok": database.ok,
            "name": settings.pg_database,
            # Sanitised: the raw message can name schema objects.
            "error": None if database.ok else "could not query the database",
        },
        "read_only_role": {
            "role": settings.pg_readonly_user,
            "privileges": posture["privileges"],
            "select_only": posture["select_only"],
        },
        # Which database and login write the chats. Never the password.
        "chat_database": {
            "configured": settings.chats_configured,
            "ok": chats,
            "name": settings.history_db_name or None,
            "role": settings.history_db_user or None,
        },
        "run_roles": list(settings.run_roles),
    }


def preflight(settings) -> None:
    """Fail at startup rather than three seconds into someone's first question.

    A misconfigured provider surfaces as an HTTP 500 carrying whatever the
    upstream said, which is a poor place to learn that .env still points at a
    model that was decommissioned. Checked once, here, where the message can
    say what to do about it.
    """
    problem = provider_problem(settings)
    if problem:
        raise SystemExit(problem)
    for problem in settings.problems():
        raise SystemExit(problem)
    if settings.llm_provider == "anthropic":
        return

    if not settings.cli_lean:
        # The MCP path needs wren_setup, which a lean-only deployment does not
        # ship. Checked here so the answer arrives at startup with something
        # actionable in it, rather than as a ModuleNotFoundError on the first
        # question that mentions no module the reader has heard of.
        try:
            import wren_setup.mcp_config  # noqa: F401
        except ModuleNotFoundError:
            raise SystemExit(
                "CLI_LEAN is false, which selects the MCP path, but wren_setup "
                "is not installed in this checkout.\n"
                "This is a production deployment: it ships only the lean path. "
                "Set CLI_LEAN=true in .env.\n"
                "The MCP path lives on the develop branch."
            )
        # Not fatal there -- the MCP path works -- but it is almost never what
        # is wanted, and the difference is invisible until the token figures
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
        # Lean mode makes no MCP calls, so there is nothing to configure and
        # no wren_setup to import. Writing the file anyway was harmless but it
        # made the module a hard dependency of a path that never uses it.
        self.mcp_config_path = None
        if not self.settings.cli_lean:
            from wren_setup.mcp_config import write_mcp_config
            self.mcp_config_path = write_mcp_config(
                args.config, args.privacy, self.settings)
        self.privacy = args.privacy
        self.context_mode = args.context_mode

        # Loaded now, like the warm processes below: a few seconds the first
        # question would otherwise wait through.
        self.anonymizer = None
        if self.settings.pii_aliasing:
            self.anonymizer = get_anonymizer(self.settings)
            self.anonymizer.load()

        # Questions people actually type are the only source of test cases
        # nobody thought to write, and they were previously going to stderr and
        # dying with the terminal. Same filename the suites use, so
        # scripts/analyze_followup.py reads a console session unchanged.
        self.log_path = None
        if args.log:
            self.log_path = Path(args.log) / "raw" / "turns.jsonl"
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_lock = threading.Lock()

        # Boot the warm Claude processes now rather than on the first
        # question. Each needs about three seconds before it can answer, and
        # the server is normally started well before anyone types anything --
        # so the cost lands in dead time instead of on the first arrival.
        if (self.settings.llm_provider == "cli" and self.settings.cli_lean
                and self.settings.cli_pool_size > 0):
            from claude.prompts import build_lean_system_prompt
            from llm_api.cli_provider import _pool_for
            _pool_for(self.settings, build_lean_system_prompt())

    def record(self, result, question: str, state: dict) -> None:
        if self.log_path is None:
            return
        row = logged(result)
        # The saved chat keeps the answer. The log keeps how the turn went,
        # not people's data: columns and counts, no rows.
        for key in ("actual_result", "chart_result"):
            row[key] = first_rows(row.get(key), 0)
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

    def pii_guard(self, loaded: dict) -> PiiGuard | None:
        """This turn's aliasing, with the chat's aliases as stored. None when
        aliasing is off. Raises rather than start a chat's numbering over."""
        anonymizer = getattr(self, "anonymizer", None)
        if anonymizer is None:
            return None
        if not loaded.get("ok", True):
            raise PiiError(PII_UNAVAILABLE)
        return PiiGuard(anonymizer, PiiVault.from_entries(loaded.get("aliases") or []))

    def authorize(self, payload: dict) -> int:
        """The request's user_id, once they are allowed to run a question.
        Raises UserIdError or RunNotAllowed; nothing has run yet."""
        user_id = user_id_from(payload.get("user_id"))
        check_run(self.settings, user_id)
        return user_id

    def ask(self, payload: dict, user_id: int,
            on_rows: Callable[[dict], None] | None = None) -> dict:
        """One turn for an authorized user, and the response the console renders.

        ``on_rows`` is optional. When it is given, the reply is streamed and
        the table is handed over the moment the SQL is complete -- about two
        seconds before the last token. The returned response is the same
        either way, so a caller that ignores the rows behaves exactly as it
        does today.
        """
        question = str(payload.get("question") or "").strip()
        drop_ref = str(payload.get("drop_ref") or "").strip()
        # A drop has no question; the goal fills it in once the state is in
        # hand. Checked again below.
        if not question and not drop_ref:
            raise BadRequest("question is required")
        debug = bool(payload.get("debug"))
        # Cleaned once, here: the saved chat is keyed by the cleaned id, so the
        # in-memory session and its lock must be too.
        session_id = safe_session_id(payload.get("session_id"))
        # The Python console sends save_chat: false; every other caller's
        # chats are saved (unless SAVE_CHATS pauses saving for everyone).
        store = ChatStore(self.settings, user_id, save=payload.get("save_chat") is not False)

        # Before the state is touched: a refused question costs nothing and
        # never enters the recent-questions window.
        self.assert_within_monthly_limit(store)

        conversation = conversation_for(session_id, user_id)

        if not conversation.lock.acquire(timeout=LOCK_WAIT_SECONDS):
            raise RuntimeError("another question is still being answered on this session")
        try:
            conversation.expire_if_idle()
            reset = bool(payload.get("reset_context"))
            if reset:
                conversation.reset()

            # The recent questions and the recap come from the chat's turns,
            # not from memory, so a chat reopened after a restart still knows
            # what it was about. On a reset this turn is the new start. The
            # turn number is counted from the rows, so it continues them.
            loaded = store.load(session_id)
            if not store.enabled:
                loaded["aliases"] = conversation.aliases
            pii = self.pii_guard(loaded)
            if loaded["chat_id"] is not None:
                conversation.turn_index = loaded["turn_index"]
                state = conversation.state
                state.recent_questions = []
                state.rolling_recap = None
                if not reset:
                    history = loaded["history"]
                    # A turn saved before aliasing was on kept its values;
                    # they are anonymized here, before any prompt holds them.
                    screened = history.get("screened") or [True] * len(history["questions"])
                    for asked, clean in zip(history["questions"], screened):
                        remember_question(state, asked if clean or pii is None
                                          else pii.anonymize(asked))
                    recap = history["recap"]
                    if recap and pii is not None and not history.get("recap_screened", True):
                        recap = pii.anonymize(recap)
                    state.rolling_recap = recap

            # A clicked suggestion carries a structured action. Applying it
            # here means the context the model sees already reflects the
            # choice; the label still goes through as the question, so the
            # turn takes the ordinary path and there is no second way for a
            # query to be built.
            action = payload.get("action")
            if isinstance(action, dict) and action.get("type") in ACTION_TYPES:
                try:
                    apply_action(conversation.state, Action(
                        type=action["type"],
                        field=action.get("field"),
                        operator=action.get("operator"),
                        value=action.get("value"),
                    ))
                except (ValueError, TypeError) as exc:
                    log.warning("ignoring unusable action %s: %s", action, exc)

            # Map a chip's ref back to the exact offered wording. A stale chip
            # matches nothing and is read as typed text; the turn still
            # resolves it, the same as a typed answer.
            option_ref = str(payload.get("option_ref") or "").strip()
            if option_ref:
                chosen = label_for_ref(conversation.state.pending_clarification, option_ref)
                if chosen is not None:
                    question = chosen

            # Dropping a pill: take the constraint off, and ask the active goal
            # again with one fewer constraint.
            if drop_ref:
                dropped = drop_by_ref(conversation.state, drop_ref)
                if dropped and not question and conversation.state.active_goal is not None:
                    question = conversation.state.active_goal
            if not question:
                raise BadRequest("question is required")

            before = state_snapshot(conversation.state)

            turn_index = conversation.turn_index
            turn = SuiteTurn(
                id=f"{conversation.id}.{conversation.turn_index}",
                question=question,
                expected_sql=None,          # no ground truth: this is a real question
                category="runtime",
                conversation_id=conversation.id,
                turn_index=conversation.turn_index,
            )
            result = run_turn(
                turn, conversation.state, self.settings,
                self.mcp_config_path, self.privacy, conversation.session,
                context_mode=self.context_mode,
                on_sql=(lambda early: on_rows(self.rows_event(early, debug)))
                if on_rows else None,
                # Every turn: the business rules, not this code, decide what
                # is personal. A cached lookup is cheap.
                identity=resolve_identity(self.settings, user_id),
                pii=pii,
            )
            if reset:
                result.context_reset = True
            conversation.turn_index += 1
            # Drupal saves the state, and starts its hour, here.
            conversation.saved_at = time.monotonic()
            after = state_snapshot(conversation.state)
            pills = context_pills(conversation.state)
            self.record(result, question, after)
            full = to_response(result, question, before, after, self.settings, pills)
            # The chart's verdict is reached in to_response, after the turn ran.
            result.chart_reason = full.get("chart_reason")
            # Before displayed(): the pane shows what the model was sent.
            full["pii"] = pii_debug(result, pii, self.settings)
            if pii is not None:
                full = displayed(full, pii)

            # Inside the lock: the next question reads its recent questions
            # from these rows, and must not load before this one lands.
            chat_id = store.save(session_id, question if pii is None
                                 else pii.restore_text(question))
            # Lets the page ask for every row. Only now: the chat id does not
            # exist until save().
            if chat_id is not None and isinstance(full.get("result"), dict) \
                    and full["result"].get("truncated"):
                full["result"] = {**full["result"],
                                  "download": {"chat_id": chat_id, "turn": turn_index + 1}}
            saved = store.record_turn(chat_id, turn_index, question, result, full,
                                      conversation.state)
            if pii is not None and not store.enabled:
                # Saving is paused: this process keeps the chat's aliases.
                conversation.aliases = pii.vault.entries()
            elif pii is not None and not saved:
                # The aliases this turn introduced were not stored, and the
                # state in memory already refers to them. Start the thread
                # clean rather than carry aliases nothing can restore.
                log.error("Turn %s of session %s was not saved; its conversation "
                          "state is reset so no unsaved alias outlives it.",
                          turn_index, session_id)
                conversation.reset()
        finally:
            conversation.lock.release()

        log.info("  %-10s %-22s %s", result.decision,
                 result.failure_category or result.followup_type, question[:48])
        if debug and store.enabled:
            # After the turn is recorded, so the figure includes this question.
            usage = self.token_usage(store)
            if usage is not None:
                full["token_usage"] = usage

        # Bounded: a long session should not grow without limit, and nobody
        # scrolls back past fifty answers to read their SQL. Under its lock
        # because /debug reads this list from another thread.
        with conversation.debug_lock:
            conversation.debug_log.append({**full, "turn_index": turn_index})
            del conversation.debug_log[:-DEBUG_LOG_TURNS]
        # Debug off is the default, and it is enforced here rather than in the
        # page: a field the browser receives has already left the server.
        return full if debug else public_response(full)

    def assert_within_monthly_limit(self, store: ChatStore) -> None:
        """Refuse when all users together have reached this month's limit.

        A usage figure that cannot be read lets the question through: a broken
        counter must not take the chatbot down. The last question allowed can
        go over by its own cost, which is only known once it has run.
        """
        limit = self.settings.monthly_token_limit
        if limit == 0 or not store.enabled:
            return
        try:
            used = store.monthly_effective_tokens()
        except Exception as exc:
            log.error("Monthly token usage could not be read, so the question "
                      "was allowed: %s", exc)
            return
        if used >= limit:
            raise TokenLimitError(TOKEN_LIMIT_MESSAGE)

    def token_usage(self, store: ChatStore) -> dict | None:
        """This month's usage, for the debug badge. A limit of 0 is none."""
        try:
            return {"used": store.monthly_effective_tokens(),
                    "limit": self.settings.monthly_token_limit}
        except Exception:
            return None

    def rows_event(self, early: dict, debug: bool) -> dict:
        """The table, before the sentences that explain it have been written.

        Redacted by the same public_response the finished answer goes through
        -- whitelisting, so the SQL and the real column names drop out with
        debug off exactly as they do there. A second redaction rule here is a
        second thing to keep in step.

        with_presentation is the one wrapper missing, and deliberately: what
        it needs is the model's `group` verdict, which has not arrived yet.
        Grouping lands with the finished answer, which carries the whole
        result again.
        """
        # The same note the answer will carry, so it arrives with the table.
        result = with_freshness(shown_result(early.get("actual_result"), self.settings),
                                self.settings, [early.get("generated_sql")])
        event = {
            "generated_sql": early.get("generated_sql"),
            "generated_sql_pretty": pretty_sql(early.get("generated_sql")),
            "sql_valid": early.get("sql_valid"),
            "execution_success": early.get("execution_success"),
            "error": safe_error(early.get("error"), early.get("sqlstate")),
            "raw_error": early.get("error"),
            "result": result,
        }
        return event if debug else public_response(event)


def console_info(settings, local: bool = False) -> dict:
    """GET /info: what the console's setup panel shows. The model and the
    modes and product.yaml's welcome (the starter questions) for anyone; for
    a caller on this machine, also the metadata folder and the databases it
    reads and writes, by name and login -- never a password. `stream` tells
    the console which endpoint to ask: /ask/stream when on, /ask when off."""
    mode, provider, model = llm_identity(settings)
    info = {"llm": {"mode": mode, "provider": provider, "model": model},
            "pii": {"enabled": settings.pii_aliasing,
                    "model": settings.pii_model if settings.pii_aliasing else None},
            "stream": settings.stream_answers,
            "welcome": welcome()}
    if local:
        try:
            info["metadata"] = settings.metadata_dir.relative_to(ROOT).as_posix()
        except ValueError:
            info["metadata"] = str(settings.metadata_dir)
        info["databases"] = {
            "read": {"name": settings.pg_database, "user": settings.pg_readonly_user},
            "write": ({"name": settings.history_db_name, "user": settings.history_db_user,
                       "saving": settings.save_chats}
                      if settings.chats_configured else None),
        }
    return info


def welcome() -> dict | None:
    """product.yaml's welcome: the line under the greeting and the starter
    questions. None when product.yaml has problems: they are logged, and must
    not cost the user their chat history. Drupal's ChatsResource::welcome."""
    try:
        return profile().welcome()
    except RuntimeError as exc:
        log.error("%s", exc)
        return None
