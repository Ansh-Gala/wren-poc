"""The HTTP endpoints. Each reads the request, hands the work to a
service and turns the result into a reply."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from config.logging import get_logger
from pipeline.chat_store import ChatStore, safe_session_id
from pipeline.run_access import RunNotAllowed, UserIdError, check_run, user_id_from

from server.config import UI_DIR
from server.services.chats import full_csv, present_chat, present_chats
from server.services import conversation
from server.services.runtime import Runtime, console_info, health, welcome
from server.utils import _closing, _json, _local, _read_json, _sse, failure

log = get_logger("serve_api")

router = APIRouter()


def _runtime(request: Request) -> Runtime:
    return request.app.state.runtime


@router.get("/health")
def get_health(request: Request):
    return _closing(lambda: _json(200, health(_runtime(request).settings)))


@router.get("/info")
def get_info(request: Request):
    """The model, the modes and the databases, for the console's setup panel."""
    return _json(200, console_info(_runtime(request).settings, local=_local(request)))


def _answer(runtime: Runtime, payload: dict) -> tuple[int, dict]:
    try:
        user_id = runtime.authorize(payload)
        return 200, runtime.ask(payload, user_id)
    except Exception as exc:                      # a bad turn must not kill the server
        return failure(exc, "turn failed")


@router.post("/ask")
async def post_ask(request: Request):
    payload = await _read_json(request)
    if isinstance(payload, JSONResponse):
        return payload
    return _json(*await run_in_threadpool(_closing, _answer, _runtime(request), payload))


def stream_events(runtime, payload: dict, user_id: int) -> Iterator[str]:
    """POST /ask/stream's body -- the table first, the rest when it is written.

    Two Server-Sent Events:

        event: rows      the query and what it returned
        event: answer    exactly what POST /ask returns

    `rows` is omitted when the turn clarifies, because a clarification
    carries no SQL and none is coming. `answer` always arrives and is the
    whole response, so a client may ignore `rows` entirely.

    The turn runs on a thread of its own and hands events over a queue. If
    the reader leaves, the turn still finishes and is saved.
    """
    events: queue.Queue = queue.Queue()
    # Kill switch, honoured server-side: when off, only `answer` is sent.
    on_rows = (lambda d: events.put(("rows", d))) if runtime.settings.stream_answers else None

    def work() -> None:
        try:
            events.put(("answer", runtime.ask(payload, user_id, on_rows=on_rows)))
        except Exception as exc:                  # a bad turn must not kill the server
            # Same body as /ask's, without its status: the stream has begun.
            events.put(("error", failure(exc, "streamed turn failed")[1]))
        finally:
            from database.connection import close_thread_connection
            close_thread_connection()
            events.put(None)

    threading.Thread(target=work, daemon=True).start()
    while (item := events.get()) is not None:
        yield _sse(*item)


@router.post("/ask/stream")
async def post_ask_stream(request: Request):
    payload = await _read_json(request)
    if isinstance(payload, JSONResponse):
        return payload
    runtime = _runtime(request)
    # Before the stream opens, so a refusal is a plain status and no SQL runs.
    try:
        user_id = await run_in_threadpool(_closing, runtime.authorize, payload)
    except Exception as exc:
        return _json(*failure(exc, "streamed turn refused"))
    return StreamingResponse(stream_events(runtime, payload, user_id),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@router.post("/debug")
async def post_debug(request: Request):
    """What the server kept for turns it has already answered. Reads only;
    nothing is generated and nothing is executed. It holds the SQL and the
    real column names, so only this machine may ask."""
    if not _local(request):
        return _json(403, {"error": "/debug answers only on this machine"})
    payload = await _read_json(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        user_id = user_id_from(payload.get("user_id"))
    except UserIdError as exc:
        return _json(*failure(exc, "debug"))
    with conversation.SESSIONS_LOCK:
        chat = conversation.SESSIONS.get((user_id, safe_session_id(payload.get("session_id"))))
    if chat is None:
        return _json(200, {"turns": []})
    with chat.debug_lock:
        turns = list(chat.debug_log)
    return _json(200, {"turns": turns})


# ------------------------------------------------------------- saved chats --

def _chats_call(request: Request, what: str, fn: Callable[[ChatStore, int], Response],
                run: bool = False) -> Response:
    """A saved-chats request for the user_id in the query string. Listing and
    reading need only a valid id; `run` also needs a run role."""
    settings = _runtime(request).settings
    try:
        user_id = user_id_from(request.query_params.get("user_id"))
        if run:
            check_run(settings, user_id)
        return fn(ChatStore(settings, user_id), user_id)
    except (UserIdError, RunNotAllowed) as exc:
        return _json(*failure(exc, what))
    except Exception:
        # Log, not wire, as on /ask.
        log.exception("saved chats failed on %s", request.url.path)
        return _json(500, {"error": what})


@router.get("/chats")
def get_chats(request: Request, limit: str = "50", offset: str = "0"):
    """This user's chats, newest activity first."""
    def listed(store: ChatStore, user_id: int) -> Response:
        if not store.enabled:
            return _json(200, {"chats": [], "total": 0, "welcome": welcome()})
        return _json(200, present_chats(store, limit, offset))
    return _closing(_chats_call, request, "I couldn't load your chat history.", listed)


@router.get("/chats/{chat_id}")
def get_chat(request: Request, chat_id: int, debug: str = ""):
    def opened_chat(store: ChatStore, user_id: int) -> Response:
        opened = store.open_chat(chat_id) if store.enabled else None
        # Someone else's chat is a 404, never a 403: the endpoint does not
        # confirm that an id exists.
        if opened is None:
            return _json(404, {"error": "No such chat."})
        # PHP's !empty(): "0" is off, as on Drupal.
        return _json(200, present_chat(opened, debug not in ("", "0") and _local(request)))
    return _closing(_chats_call, request, "I couldn't load that chat.", opened_chat)


@router.delete("/chats/{chat_id}")
def delete_chat(request: Request, chat_id: int):
    """Takes the chat off its owner's list; its turns stay in the database.
    Drupal's ChatResource::delete."""
    def deleted(store: ChatStore, user_id: int) -> Response:
        if not store.enabled or not store.delete_chat(chat_id):
            return _json(404, {"error": "No such chat."})
        return _json(200, {"deleted": True})
    return _closing(_chats_call, request, "I couldn't delete that chat.", deleted)


@router.get("/chats/{chat_id}/turns/{turn}/csv")
def get_chat_csv(request: Request, chat_id: int, turn: int):
    """Every row of one answered question. Runs SQL, so it needs a run role."""
    def download(store: ChatStore, user_id: int) -> Response:
        status, body = full_csv(_runtime(request).settings, store, chat_id, turn)
        if status != 200:
            return _json(status, body)
        return Response(body, media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="chat-{chat_id}-answer-{turn}.csv"',
            "Cache-Control": "no-cache, private"})
    return _closing(_chats_call, request, "I couldn't load that chat.", download, True)


# ------------------------------------------------------------------ console --

@router.get("/{name:path}")
def get_file(name: str):
    name = name or "index.html"
    target = (UI_DIR / name).resolve()
    # Nothing outside ui/ is servable, whatever the path says.
    if not target.is_relative_to(UI_DIR.resolve()) or not target.is_file():
        return _json(404, {"error": f"no such file: {name}"})
    return FileResponse(target, headers={"Cache-Control": "no-store"})   # it is being edited
