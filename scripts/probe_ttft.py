"""Where a model call's seconds go: waiting, or typing.

A turn is 8-12 seconds and 99% of it is one HTTP request with no tool loop, so
there is no round trip left to remove. Two readings fit that, and they lead to
opposite fixes:

  * generation-bound -- the first token comes back quickly and the rest of the
    wait is the model typing the ~200 tokens the answer contract asks for. The
    fix is to stop waiting for the parts nobody reads first, or to generate
    faster.
  * TTFT-bound -- seconds of dead air, then a fast burst. Output length is then
    irrelevant and only a different provider helps.

`results/new_views_python` argues for the first on the Claude path: a p50 of
2071 ms is impossible if the first token takes seven seconds. Luna has never
been measured and may genuinely differ. This settles it with a number.

The prompts are the real ones, built by the same functions the pipeline uses,
because a probe on a synthetic prompt measures a call nobody makes.

    python scripts/probe_ttft.py --base-url https://api.groq.com/openai/v1 \
        --model llama-3.3-70b-versatile --api-key-env GROQ_API_KEY

    python scripts/probe_ttft.py --reps 5 --out results/2026-09-23/ttft_luna.json

Anything speaking the OpenAI chat-completions shape works, which is Luna,
OpenAI, Groq and Gemini's compatibility endpoint. The Claude CLI is not covered
-- `scripts/bench_latency.py` already reports its wall time, and its streaming
is `--output-format stream-json`, a different thing needing its own parser.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from claude.parser import sql_value_end as find_sql_end  # noqa: E402
from claude.prompts import build_lean_system_prompt, build_user_prompt  # noqa: E402
from pipeline.metadata import enable_site_metadata  # noqa: E402

# The same ceiling the Drupal transport uses, so a model is not given more room
# here than it gets in production.
MAX_TOKENS = 2048

DEFAULT_QUESTION = "Show the open tasks for AR_YD_Suiting"


def probe(client: httpx.Client, url: str, headers: dict, payload: dict) -> dict:
    """One streamed call, with the marks taken as the bytes arrive."""
    started = time.perf_counter()
    ttft_ms = None
    sql_done_ms = None
    text = ""
    usage = {}
    chunks = 0

    def ms() -> float:
        return (time.perf_counter() - started) * 1000

    with client.stream("POST", url, headers=headers, json=payload) as response:
        if response.status_code != 200:
            response.read()
            return {"ok": False, "error": f"HTTP {response.status_code}: {response.text[:400]}",
                    "total_ms": ms()}
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            # Some providers send the usage block in its own final chunk with
            # an empty choices list, so it is read before choices is indexed.
            if event.get("usage"):
                usage = event["usage"]
            choices = event.get("choices") or []
            if not choices:
                continue
            piece = (choices[0].get("delta") or {}).get("content") or ""
            if not piece:
                continue
            chunks += 1
            if ttft_ms is None:
                ttft_ms = ms()
            text += piece
            if sql_done_ms is None and find_sql_end(text) is not None:
                sql_done_ms = ms()

    total_ms = ms()
    out_tokens = int(usage.get("completion_tokens") or 0)
    return {
        "ok": ttft_ms is not None,
        "ttft_ms": ttft_ms,
        "sql_done_ms": sql_done_ms,
        "total_ms": total_ms,
        "output_tokens": out_tokens,
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "cached_tokens": int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
        # A reasoning model thinks before it says anything, and those tokens
        # are billed and generated but never streamed. If TTFT is large, this
        # is where the seconds went -- and unlike the answer contract, it is
        # tunable with one parameter.
        "reasoning_tokens": int(
            (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
        "chunks": chunks,
        "output_chars": len(text),
        # What the model spent typing, as distinct from what the caller spent
        # waiting for it to start.
        "gen_ms": (total_ms - ttft_ms) if ttft_ms is not None else None,
        "tok_per_s": (out_tokens / ((total_ms - ttft_ms) / 1000))
        if (ttft_ms is not None and out_tokens and total_ms > ttft_ms) else None,
        # The part of the answer the user is not waiting for.
        "after_sql_ms": (total_ms - sql_done_ms) if sql_done_ms is not None else None,
        "text": text,
    }


def mean(rows: list[dict], key: str) -> float | None:
    values = [r[key] for r in rows if r.get(key) is not None]
    return statistics.fmean(values) if values else None


def show(label: str, rows: list[dict]) -> None:
    rows = [r for r in rows if r.get("ok")]
    if not rows:
        print(f"\n{label}: no successful runs")
        return

    def fmt(key: str, unit: str = "s") -> str:
        v = mean(rows, key)
        if v is None:
            return "     --"
        return f"{v / 1000:6.2f}s" if unit == "s" else f"{v:6.1f}"

    print(f"\n{label}  (n={len(rows)})")
    print(f"  {'Time to first token':34} {fmt('ttft_ms')}")
    print(f"  {'Time to complete SQL':34} {fmt('sql_done_ms')}")
    print(f"  {'Time to last token':34} {fmt('total_ms')}")
    print(f"  {'  of which generating':34} {fmt('gen_ms')}")
    print(f"  {'  spent after the SQL was known':34} {fmt('after_sql_ms')}")
    print(f"  {'Output tokens':34} {fmt('output_tokens', 'n')}")
    reasoning = mean(rows, "reasoning_tokens")
    if reasoning:
        print(f"  {'  of which thinking, never shown':34} {fmt('reasoning_tokens', 'n')}")
    print(f"  {'Tokens per second':34} {fmt('tok_per_s', 'n')}")
    print(f"  {'Prompt tokens (cached)':34} {fmt('prompt_tokens', 'n')} ({fmt('cached_tokens', 'n').strip()})")

    ttft, total = mean(rows, "ttft_ms"), mean(rows, "total_ms")
    if ttft and total:
        share = ttft / total * 100
        print()
        if share >= 60:
            print(f"  TTFT-BOUND: {share:.0f}% of the wait is before the first token.")
            if reasoning:
                print(f"  {reasoning:.0f} of those tokens are the model thinking. "
                      "Try --reasoning-effort minimal.")
            else:
                print("  Output length is not the lever. A different provider is.")
        else:
            print(f"  GENERATION-BOUND: {100 - share:.0f}% of the wait is typing.")
            sql_done = mean(rows, "sql_done_ms")
            if sql_done:
                print(f"  The SQL is known at {sql_done / 1000:.2f}s; the remaining "
                      f"{(total - sql_done) / 1000:.2f}s is answer trimmings.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True,
                    help="the endpoint root, e.g. https://api.groq.com/openai/v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key-env", default="OPENAI_API_KEY",
                    help="environment variable holding the key (default OPENAI_API_KEY)")
    ap.add_argument("--question", default=DEFAULT_QUESTION)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="pass -1 to omit it, which OpenAI's reasoning models require")
    ap.add_argument("--reasoning-effort", default=None,
                    help="minimal, low, medium or high. OpenAI's reasoning models "
                         "think before emitting anything, and that thinking is "
                         "the TTFT this script measures.")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--out", default=None,
                    help="where to write the JSON; defaults to "
                         "results/<today>/ttft_<model>.json")
    args = ap.parse_args()

    enable_site_metadata()
    key = os.environ.get(args.api_key_env, "").strip()
    if not key:
        print(f"{args.api_key_env} is not set in the environment.", file=sys.stderr)
        return 1

    url = args.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": build_lean_system_prompt()},
            {"role": "user", "content": build_user_prompt(args.question, lean=True)},
        ],
        "stream": True,
        # Not every provider sends usage on a stream unless asked. Ignored by
        # those that always do.
        "stream_options": {"include_usage": True},
    }
    # OpenAI renamed the output ceiling for its reasoning models and the
    # current ones reject the old name outright. The same branch
    # src/Llm/OpenAiCompatibleProvider.php makes, and for the same reason.
    on_openai = "api.openai.com" in args.base_url
    payload["max_completion_tokens" if on_openai else "max_tokens"] = MAX_TOKENS
    # Those models also accept only the default temperature. Sending nothing
    # gets it, which is the only thing they allow.
    if args.temperature >= 0 and not on_openai:
        payload["temperature"] = args.temperature
    if args.reasoning_effort:
        payload["reasoning_effort"] = args.reasoning_effort

    print(f"{args.model} at {args.base_url}")
    print(f"{args.reps} reps of: {args.question}")
    print(f"system prompt {len(payload['messages'][0]['content'])} chars\n")

    rows = []
    with httpx.Client(timeout=args.timeout) as client:
        headers = {"Authorization": f"Bearer {key}", "content-type": "application/json"}
        for rep in range(args.reps):
            r = probe(client, url, headers, payload)
            rows.append(r)
            if not r.get("ok"):
                print(f"  rep{rep} FAILED: {r.get('error', 'no content received')}")
                continue
            print(f"  rep{rep}  ttft {r['ttft_ms'] / 1000:5.2f}s"
                  f"  sql {(r['sql_done_ms'] or 0) / 1000:5.2f}s"
                  f"  total {r['total_ms'] / 1000:5.2f}s"
                  f"  {r['output_tokens']:4d} tok", flush=True)

    print("\n" + "=" * 72)
    show("COLD (first rep)", rows[:1])
    if len(rows) > 1:
        show("WARM (later reps)", rows[1:])

    out = Path(args.out) if args.out else (
        ROOT / "results" / date.today().isoformat() / f"ttft_{args.model.replace('/', '_')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "base_url": args.base_url,
        "model": args.model,
        "question": args.question,
        "reps": args.reps,
        "system_prompt_chars": len(payload["messages"][0]["content"]),
        "rows": rows,
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0 if any(r.get("ok") for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
