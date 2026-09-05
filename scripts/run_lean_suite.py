"""Run the 50-turn lean suite.

    python scripts/run_lean_suite.py
    python scripts/run_lean_suite.py --ids C04           # one conversation
    python scripts/run_lean_suite.py --out results/lean_v1

Conversations run whole: selecting a single turn would give it an empty
context and test nothing.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

import _bootstrap  # noqa: F401

from benchmark.lean_runner import run_suite
from benchmark.lean_suite import all_turns, load_suite, select
from config.logging import get_logger, register_secrets
from config.settings import load_settings
from wren_setup.mcp_config import write_mcp_config


def summarise(results, out_dir: Path) -> dict:
    n = len(results)
    if not n:
        return {}
    ok = sum(1 for r in results if r.result_match)
    standalone = [r for r in results if r.turn_index == 0 and r.conversation_id == r.turn_id]
    followups = [r for r in results if r.turn_index > 0]
    decided = [r for r in results if r.decision_match is not None]
    resets = [r for r in results if r.expected_decision in ("new_block", "switch")]

    def pct(sub):
        return (sum(1 for r in sub if r.result_match) / len(sub) * 100) if sub else 0.0

    avg = lambda f: sum(f(r) for r in results) / n

    s = {
        "turns": n,
        "correct": ok,
        "accuracy": ok / n * 100,
        "standalone_accuracy": pct(standalone),
        "standalone_n": len(standalone),
        "followup_accuracy": pct(followups),
        "followup_n": len(followups),
        "context_reset_accuracy": pct(resets),
        "context_reset_n": len(resets),
        "decision_accuracy": (
            sum(1 for r in decided if r.decision_match) / len(decided) * 100
        ) if decided else 0.0,
        "decision_n": len(decided),
        "avg_prompt_tokens": avg(lambda r: r.prompt_tokens),
        "avg_cache_read_tokens": avg(lambda r: r.cache_read_tokens),
        "avg_completion_tokens": avg(lambda r: r.completion_tokens),
        "avg_total_tokens": avg(lambda r: r.prompt_tokens + r.completion_tokens),
        "avg_effective_tokens": avg(
            lambda r: (r.prompt_tokens - r.cache_read_tokens)
            + r.cache_read_tokens * 0.1 + r.completion_tokens
        ),
        "avg_tool_calls": avg(lambda r: r.tool_call_count),
        "avg_latency_s": avg(lambda r: r.latency_ms / 1000),
        "avg_context_chars": avg(lambda r: r.context_chars),
        "sql_generated": sum(1 for r in results if r.generated_sql),
        "sql_executed": sum(1 for r in results if r.execution_success),
    }

    print("\n" + "=" * 66)
    print("LEAN SUITE")
    print("=" * 66)
    print(f"  accuracy                 {ok}/{n}  ({s['accuracy']:.1f}%)")
    print(f"    standalone             {s['standalone_accuracy']:.1f}%  (n={s['standalone_n']})")
    print(f"    follow-up              {s['followup_accuracy']:.1f}%  (n={s['followup_n']})")
    print(f"    context reset/switch   {s['context_reset_accuracy']:.1f}%  (n={s['context_reset_n']})")
    print(f"    turn classification    {s['decision_accuracy']:.1f}%  (n={s['decision_n']})")
    print(f"  sql generated / executed {s['sql_generated']}/{n}  {s['sql_executed']}/{n}")
    print()
    print(f"  avg prompt tokens        {s['avg_prompt_tokens']:>10,.0f}")
    print(f"  avg cache read tokens    {s['avg_cache_read_tokens']:>10,.0f}")
    print(f"  avg completion tokens    {s['avg_completion_tokens']:>10,.0f}")
    print(f"  avg total tokens         {s['avg_total_tokens']:>10,.0f}")
    print(f"  avg effective tokens     {s['avg_effective_tokens']:>10,.0f}")
    print(f"  avg tool calls           {s['avg_tool_calls']:>10.1f}")
    print(f"  avg latency (s)          {s['avg_latency_s']:>10.1f}")
    print(f"  avg context chars        {s['avg_context_chars']:>10.0f}")

    failures = [r for r in results if not r.result_match]
    if failures:
        print(f"\n  failures ({len(failures)}):")
        for cat, c in Counter(r.failure_category for r in failures).most_common():
            print(f"    {cat:<26} {c}")
        print()
        for r in failures:
            print(f"    {r.turn_id:<7} {r.failure_category:<24} {r.question[:44]}")

    bad_decisions = [r for r in results if r.decision_match is False]
    if bad_decisions:
        print(f"\n  turn misclassified ({len(bad_decisions)}):")
        for r in bad_decisions:
            print(f"    {r.turn_id:<7} expected {r.expected_decision:<10} got {r.decision}")

    by_cat = defaultdict(lambda: [0, 0])
    for r in results:
        by_cat[r.category][1] += 1
        if r.result_match:
            by_cat[r.category][0] += 1
    print("\n  by category:")
    for cat in sorted(by_cat):
        good, tot = by_cat[cat]
        flag = "" if good == tot else "   <-"
        print(f"    {cat:<38} {good}/{tot}{flag}")

    out_dir.mkdir(parents=True, exist_ok=True)
    import json
    (out_dir / "summary.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", default=None, help="conversation or turn ids, comma separated")
    ap.add_argument("--categories", default=None)
    ap.add_argument("--out", default="results/lean", help="output directory")
    ap.add_argument("--config", default="D")
    ap.add_argument("--privacy", default="strict")
    ap.add_argument("--context-mode", default="state",
                    choices=["none", "history", "state"],
                    help="none = pre-session baseline, history = replay the "
                         "thread verbatim, state = compact structured context")
    args = ap.parse_args()

    settings = load_settings()
    register_secrets(settings.secrets())
    log = get_logger("run_lean_suite", settings.debug)

    conversations = load_suite()
    if args.ids or args.categories:
        conversations = select(
            conversations,
            ids=[i.strip() for i in args.ids.split(",")] if args.ids else None,
            categories=args.categories,
        )
    turns = all_turns(conversations)

    out_dir = Path(args.out)
    jsonl = out_dir / "raw" / "turns.jsonl"
    if jsonl.exists():
        jsonl.unlink()

    mcp_config_path = write_mcp_config(args.config, args.privacy, settings)
    mode = "lean (no MCP)" if settings.cli_lean else f"MCP config {args.config}"
    print(f"provider: {settings.llm_provider} / {settings.claude_model or 'default'}   {mode}")
    print(f"context mode: {args.context_mode}")
    print(f"conversations: {len(conversations)}   turns: {len(turns)}")
    print(f"output: {out_dir}\n")

    results = run_suite(conversations, settings, mcp_config_path, args.privacy,
                        jsonl_path=jsonl, context_mode=args.context_mode)
    s = summarise(results, out_dir)
    return 0 if s.get("accuracy", 0) >= 90 else 1


if __name__ == "__main__":
    raise SystemExit(main())
