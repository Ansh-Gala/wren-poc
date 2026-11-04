"""Small helpers the routes and services share: errors, the JSON and
event-stream replies, and whether a caller is on this machine."""

from __future__ import annotations

import json
from collections.abc import Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from config.logging import get_logger
from pipeline.redact import GENERIC, safe_error
from pipeline.run_access import RunNotAllowed, UserIdError

from server.config import TOKEN_LIMIT_CODE, _LOOPBACK

log = get_logger("serve_api")


class TokenLimitError(Exception):
    pass


class BadRequest(ValueError):
    """Something wrong with the request itself, said as is with a 400.
    Drupal's InvalidArgumentException in AskResource. Any other error, a
    ValueError from deep in the pipeline included, is a 500 through
    safe_error."""


def failure(exc: Exception, what: str) -> tuple[int, dict]:
    """A failed turn as a status and a body, the same for /ask and the stream.

    The real message reaches the wire only when safe_error finds no table,
    column or query in it.
    """
    if isinstance(exc, TokenLimitError):
        return 429, {"error": str(exc), "code": TOKEN_LIMIT_CODE}
    if isinstance(exc, UserIdError):
        return 400, {"error": str(exc), "code": exc.code}
    if isinstance(exc, RunNotAllowed):
        return 403, {"error": str(exc), "code": exc.code}
    if isinstance(exc, BadRequest):
        return 400, {"error": str(exc)}
    log.exception(what)
    return 500, {"error": safe_error(str(exc)) or GENERIC}


def _local_client(address: str) -> bool:
    return address in _LOOPBACK


def _closing(fn: Callable, *args):
    """Run fn on a worker thread, and close that thread's database
    connection after it: the next request may land on another thread."""
    from database.connection import close_thread_connection
    try:
        return fn(*args)
    finally:
        close_thread_connection()


def _json(status: int, body: dict) -> JSONResponse:
    # Through json.dumps(default=str) first: rows can hold dates and Decimals.
    return JSONResponse(json.loads(json.dumps(body, default=str)), status_code=status)


def _local(request: Request) -> bool:
    return request.client is not None and _local_client(request.client.host)


async def _read_json(request: Request) -> dict | JSONResponse:
    """The request body as a JSON object, or the 400 to send instead.
    Debug, and save_chat: false, are honoured only on this machine."""
    try:
        payload = json.loads(await request.body() or b"{}")
    except (ValueError, json.JSONDecodeError) as exc:
        return _json(400, {"error": f"bad request body: {exc}"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "bad request body: expected a JSON object"})
    if not _local(request):
        payload["debug"] = False
        payload.pop("save_chat", None)
    return payload


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
