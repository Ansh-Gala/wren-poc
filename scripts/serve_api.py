"""Serve the pipeline over HTTP, so the QA console can ask real questions.

    python scripts/serve_api.py
    python scripts/serve_api.py --port 8000 --context-mode state

Then open http://localhost:8000/ -- the console is served from here too, which
keeps it same-origin and means there is no CORS to think about.

There is no second pipeline. Every request goes through pipeline.lean_runner
.run_turn, the same function the four benchmark suites run, with no expected
SQL to compare against. That is the whole design: a console that exercised its
own copy of the logic would drift from the thing being measured, and would
then be showing you something other than what the benchmark says.

FastAPI, bound to this machine. Every request names its user_id
(pipeline/run_access.py); asking needs one of CHATBOT_RUN_ROLES. Business
queries go to DATABASE_* as DATABASE_READONLY_USER; saved chats go to
HISTORY_DATABASE_* as HISTORY_DATABASE_USER (docs/two-databases.md).
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pipeline.metadata import enable_site_metadata
from server.routes import router
from server.services.runtime import Runtime
from server.utils import _json

# No docs pages and no CORS headers. The console is served from here, so it is
# same-origin; "Access-Control-Allow-Origin: *" let any web page the user had
# open read this server's answers.
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.state.runtime = None             # set in main()


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Errors in the server's own {"error": ...} shape, not FastAPI's."""
    return _json(exc.status_code, {"error": str(exc.detail)})


app.include_router(router)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--config", default="D")
    ap.add_argument("--privacy", default="strict")
    ap.add_argument("--context-mode", default="state",
                    choices=["none", "history", "state"])
    ap.add_argument("--log", default="logs/console",
                    help="directory to append every turn to as JSONL; "
                         "'' disables logging")
    args = ap.parse_args()

    import uvicorn

    # Before Runtime: it builds the system prompt for the warm pool.
    enable_site_metadata()
    runtime = app.state.runtime = Runtime(args)
    settings = runtime.settings
    mode = "lean (no MCP)" if settings.cli_lean else f"MCP config {args.config}"

    # Which database and login each operation uses. Never a password.
    print(f"provider: {settings.llm_provider} / {settings.claude_model or 'default'}   {mode}")
    print(f"business database: {settings.pg_database} on {settings.pg_host}:{settings.pg_port}"
          f"   queries run as {settings.pg_readonly_user}")
    print("chat database:     " + (
        f"{settings.history_db_name} on {settings.history_db_host}:{settings.history_db_port}"
        f"   written as {settings.history_db_user}"
        + ("" if settings.save_chats else "   PAUSED (SAVE_CHATS=false): chats are not saved")
        if settings.chats_configured
        else "not configured (HISTORY_DATABASE_NAME / _USER): chats are not saved"))
    print(f"run roles:         {', '.join(settings.run_roles) or 'not set (CHATBOT_RUN_ROLES): everyone may ask'}")
    print(f"context mode: {args.context_mode}")
    print("PII aliasing:      " + (
        f"on ({settings.pii_model}, threshold {settings.pii_threshold})"
        if settings.pii_aliasing else "off (PII_ALIASING)"))
    print()
    print(f"  console   http://{args.host}:{args.port}/?user_id=<TMS user id>")
    print(f"  endpoint  POST http://{args.host}:{args.port}/ask")
    if runtime.log_path:
        print(f"  log       {runtime.log_path}")
    print()
    print("Ctrl+C to stop.")

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        # Warm processes are children of this one; without this they outlive
        # a Ctrl+C and sit holding memory.
        from llm_api.cli_provider import shutdown_pools
        shutdown_pools()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
