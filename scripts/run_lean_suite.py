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

from pipeline.lean_runner import run_suite
from benchmark.suite import all_turns, load_suite, select
from config.logging import get_logger, register_secrets
from config.settings import load_settings
from wren_setup.mcp_config import write_mcp_config


def _pct(values: list[float], p: float) -> float:
    """Nearest-rank percentile. No interpolation: n is 50, not 50,000."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(p / 100 * len(ordered) + 0.5)) - 1))
    return ordered[k]


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
        # An average hides the tail, and the tail is what a person notices.
        # Everything below is already in the JSONL; only the reporting was
        # missing.
        "p50_latency_s": _pct([r.latency_ms for r in results], 50) / 1000,
        "p95_latency_s": _pct([r.latency_ms for r in results], 95) / 1000,
        "p99_latency_s": _pct([r.latency_ms for r in results], 99) / 1000,
        "max_latency_s": max((r.latency_ms for r in results), default=0) / 1000,
        # What the CLI says the model cost, and what the caller actually
        # waited for it. The difference is process overhead.
        "avg_llm_s": avg(lambda r: r.llm_ms / 1000),
        "avg_llm_wall_s": avg(lambda r: r.llm_wall_ms / 1000),
        "avg_context_chars": avg(lambda r: r.context_chars),
        "sql_generated": sum(1 for r in results if r.generated_sql),
        "sql_executed": sum(1 for r in results if r.execution_success),
        "semantic_accuracy": sum(1 for r in results if r.semantic_match) / n * 100,
        "hidden_semantic_failures": sum(
            1 for r in results if r.result_match and not r.semantic_match),
        "projection_exact": sum(1 for r in results if r.projection_verdict == "exact"),
        "projection_superset": sum(1 for r in results if r.projection_verdict == "superset"),
        "projection_missing": sum(1 for r in results if r.projection_verdict == "missing"),
        "projection_substituted": sum(
            1 for r in results if r.projection_verdict == "substituted"),
    }

    # The follow-up layer, scored apart from the SQL. A turn can write a
    # perfect query and offer a useless continuation; folding the two into one
    # number would hide both and would make the before/after comparison of SQL
    # accuracy impossible to read.
    repaired = [r for r in results if r.normalized_match is not None]
    typed = [r for r in results if r.followup_match is not None]
    acted = [r for r in results if r.action_match is not None]
    s.update({
        "repair_accuracy": (
            sum(1 for r in repaired if r.normalized_match) / len(repaired) * 100
        ) if repaired else None,
        "repair_n": len(repaired),
        "followup_type_accuracy": (
            sum(1 for r in typed if r.followup_match) / len(typed) * 100
        ) if typed else None,
        "followup_type_n": len(typed),
        "action_accuracy": (
            sum(1 for r in acted if r.action_match) / len(acted) * 100
        ) if acted else None,
        "action_n": len(acted),
        "turns_with_repair": sum(1 for r in results if r.repairs),
        "turns_offering_suggestions": sum(
            1 for r in results if r.followup.get("suggestions")),
        "preflight_clarified": sum(1 for r in results if r.preflight_clarified),
        # Turns the follow-up layer answered without any model call at all.
        "llm_calls_avoided": sum(1 for r in results if r.preflight_clarified),
    })

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
    print(f"  SEMANTIC accuracy        {s['semantic_accuracy']:.1f}%   "
          f"(right query, not just right rows)")
    print(f"    right rows, wrong sql  {s['hidden_semantic_failures']}"
          f"   <- hidden by result matching")
    print(f"    projection exact       {s['projection_exact']}/{n}")
    print(f"    projection superset    {s['projection_superset']}/{n}")
    print(f"    projection missing     {s['projection_missing']}/{n}")
    print(f"    projection substituted {s['projection_substituted']}/{n}")
    print()
    print(f"  avg prompt tokens        {s['avg_prompt_tokens']:>10,.0f}")
    print(f"  avg cache read tokens    {s['avg_cache_read_tokens']:>10,.0f}")
    print(f"  avg completion tokens    {s['avg_completion_tokens']:>10,.0f}")
    print(f"  avg total tokens         {s['avg_total_tokens']:>10,.0f}")
    print(f"  avg effective tokens     {s['avg_effective_tokens']:>10,.0f}")
    print(f"  avg tool calls           {s['avg_tool_calls']:>10.1f}")
    print(f"  avg latency (s)          {s['avg_latency_s']:>10.1f}")
    print(f"  p50 / p95 / p99 (s)      "
          f"{s['p50_latency_s']:>4.1f} / {s['p95_latency_s']:.1f} / "
          f"{s['p99_latency_s']:.1f}   max {s['max_latency_s']:.1f}")
    print(f"  avg model (s)            {s['avg_llm_wall_s']:>10.1f}"
          f"   (CLI reports {s['avg_llm_s']:.1f})")
    print(f"  avg context chars        {s['avg_context_chars']:>10.0f}")

    if repaired or typed or acted:
        print()
        print("  FOLLOW-UP LAYER")
        if repaired:
            print(f"    repair                 {s['repair_accuracy']:.1f}%  (n={s['repair_n']})")
        if typed:
            print(f"    follow-up type         {s['followup_type_accuracy']:.1f}%  (n={s['followup_type_n']})")
        if acted:
            print(f"    suggested action       {s['action_accuracy']:.1f}%  (n={s['action_n']})")
        print(f"    turns repaired         {s['turns_with_repair']}")
        print(f"    turns with suggestions {s['turns_offering_suggestions']}")
        print(f"    clarified without LLM  {s['preflight_clarified']}")

        wrong_repair = [r for r in repaired if not r.normalized_match]
        if wrong_repair:
            print(f"\n  repair misses ({len(wrong_repair)}):")
            for r in wrong_repair:
                print(f"    {r.turn_id:<7} {r.question!r}")
                print(f"            got      {r.normalized_question!r}")
                print(f"            expected {r.expect_normalized!r}")

        wrong_followup = [r for r in typed if not r.followup_match]
        if wrong_followup:
            print(f"\n  follow-up type misses ({len(wrong_followup)}):")
            for r in wrong_followup:
                print(f"    {r.turn_id:<7} expected {r.expected_followup:<14} "
                      f"got {r.followup_type:<14} {r.question[:36]!r}")

        wrong_action = [r for r in acted if not r.action_match]
        if wrong_action:
            print(f"\n  suggested action misses ({len(wrong_action)}):")
            for r in wrong_action:
                offered = [x["action"] for x in r.followup.get("suggestions", [])]
                print(f"    {r.turn_id:<7} wanted {r.expected_action}")
                print(f"            offered {offered}")

    failures = [r for r in results if not r.result_match]
    if failures:
        print(f"\n  failures ({len(failures)}):")
        for cat, c in Counter(r.failure_category for r in failures).most_common():
            print(f"    {cat:<26} {c}")
        print()
        for r in failures:
            print(f"    {r.turn_id:<7} {r.failure_category:<24} {r.question[:44]}")

    hidden = [r for r in results if r.result_match and not r.semantic_match]
    if hidden:
        print(f"\n  right rows but wrong query ({len(hidden)}):")
        for r in hidden:
            print(f"    {r.turn_id:<8} {r.question[:44]}")
            for issue in r.semantic_issues[:3]:
                print(f"       - {issue[:88]}")

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
    ap.add_argument("--suite", default=None,
                    help="path to a suite yaml (default benchmark/lean_questions.yaml)")
    ap.add_argument("--config", default="D")
    ap.add_argument("--privacy", default="strict")
    ap.add_argument("--no-followup", action="store_true",
                    help="disable the repair/clarification/exploration layer, "
                         "to measure what it costs and what it changes")
    ap.add_argument("--context-mode", default="state",
                    choices=["none", "history", "state"],
                    help="none = pre-session baseline, history = replay the "
                         "thread verbatim, state = compact structured context")
    args = ap.parse_args()

    settings = load_settings()
    register_secrets(settings.secrets())
    log = get_logger("run_lean_suite", settings.debug)

    conversations = load_suite(Path(args.suite) if args.suite else None)
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
    print(f"context mode: {args.context_mode}   "
          f"follow-up layer: {'off' if args.no_followup else 'on'}")
    print(f"conversations: {len(conversations)}   turns: {len(turns)}")
    print(f"output: {out_dir}\n")

    results = run_suite(conversations, settings, mcp_config_path, args.privacy,
                        jsonl_path=jsonl, context_mode=args.context_mode,
                        followup_mode=not args.no_followup)
    s = summarise(results, out_dir)
    return 0 if s.get("accuracy", 0) >= 90 else 1


if __name__ == "__main__":
    raise SystemExit(main())
