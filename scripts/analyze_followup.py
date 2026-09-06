"""Classify every failure in a run by the stage that produced it.

    python scripts/analyze_followup.py results/followup_v1
    python scripts/analyze_followup.py results/after_lean --compare results/baseline_lean

"88/100 passed" is the least useful true thing you can say about a run. Twelve
failures that are all pronoun resolution is one bug; twelve failures spread
across six stages is six. The number is the same and the work is not, so this
groups by *where* a turn went wrong before it lists what went wrong.

The stages are ordered by how early they run, and a turn is attributed to the
earliest stage that failed -- a turn whose question was mis-repaired will also
have wrong SQL, and calling that a SQL failure would send you to fix the wrong
layer.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

# Earliest first. The first one that matches owns the failure.
STAGES = [
    ("normalization", "the repair layer changed the question wrongly, or "
                      "failed to change it"),
    ("classification", "the turn was read as continuing or starting a block, "
                       "wrongly"),
    ("candidate_retrieval", "asked which of several things was meant, and "
                            "offered nothing to choose from"),
    ("followup_generation", "offered the wrong kind of follow-up, or none"),
    ("suggestion_ranking", "offered follow-ups, but not the useful one"),
    ("clarification_behaviour", "answered a question it should have asked "
                                "about, or asked about one it could answer"),
    ("sql_execution", "the query did not run"),
    ("sql_generation", "the query ran and returned the wrong thing"),
    ("semantic", "right rows, wrong query"),
]


def load(run_dir: Path) -> list[dict]:
    f = run_dir / "raw" / "turns.jsonl"
    if not f.exists():
        raise SystemExit(f"no results at {f}")
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


def stage_of(r: dict) -> str | None:
    """The earliest stage that went wrong, or None if the turn was clean."""
    if r.get("normalized_match") is False:
        return "normalization"
    if r.get("decision_match") is False:
        return "classification"
    if (r.get("followup", {}).get("reason") == "unknown_value"
            and not r.get("followup", {}).get("suggestions")):
        return "candidate_retrieval"
    if r.get("followup_match") is False:
        return "followup_generation"
    if r.get("action_match") is False:
        return "suggestion_ranking"
    if r.get("behavior_match") is False:
        return "clarification_behaviour"
    # `is False`, not falsy: a runtime turn has no expected answer, so its
    # result_match is None, and that is "nothing to compare" rather than "wrong".
    if r["result_match"] is False:
        if r["failure_category"] in ("SQL_SYNTAX_ERROR", "SCHEMA_ERROR",
                                     "TOOL_PIPELINE_ERROR", "PROMPT_ERROR"):
            return "sql_execution"
        return "sql_generation"
    if not r.get("semantic_match", True):
        return "semantic"
    return None


def report(rows: list[dict], label: str) -> None:
    failures = [(r, stage_of(r)) for r in rows]
    failures = [(r, s) for r, s in failures if s is not None]

    print("=" * 74)
    print(f"{label}: {len(rows) - len(failures)}/{len(rows)} clean, "
          f"{len(failures)} with a defect")
    print("=" * 74)

    if not failures:
        print("  nothing to analyse")
        return

    by_stage: dict[str, list[dict]] = defaultdict(list)
    for r, stage in failures:
        by_stage[stage].append(r)

    print("\n  BY STAGE")
    for stage, description in STAGES:
        hit = by_stage.get(stage)
        if hit:
            print(f"    {stage:<24} {len(hit):>3}   {description}")

    print("\n  BY CATEGORY")
    for category, count in Counter(r["category"] for r, _ in failures).most_common():
        print(f"    {category:<44} {count}")

    tokens = [r["prompt_tokens"] + r["completion_tokens"] for r, _ in failures]
    clean = [r["prompt_tokens"] + r["completion_tokens"]
             for r in rows if stage_of(r) is None]
    if tokens and clean:
        print(f"\n  tokens: {sum(tokens)/len(tokens):,.0f} avg on failures, "
              f"{sum(clean)/len(clean):,.0f} avg on clean turns")

    for stage, _ in STAGES:
        hit = by_stage.get(stage)
        if not hit:
            continue
        print(f"\n  ---- {stage} ({len(hit)}) " + "-" * (50 - len(stage)))
        for r in hit:
            print(f"    {r['turn_id']:<8} {r['category']}")
            print(f"      asked     {r['question']!r}")
            if r.get("normalized_question") and r["normalized_question"] != r["question"]:
                print(f"      repaired  {r['normalized_question']!r}")
            if stage == "normalization":
                print(f"      expected  {r['expect_normalized']!r}")
            elif stage == "classification":
                print(f"      expected  {r['expected_decision']}  got {r['decision']}")
            elif stage in ("followup_generation", "suggestion_ranking"):
                print(f"      expected  {r.get('expected_followup')} "
                      f"{r.get('expected_action') or ''}")
                print(f"      offered   {[s['action'] for s in r['followup'].get('suggestions', [])]}")
            elif stage == "clarification_behaviour":
                print(f"      expected  {r['expected_behavior']}")
                print(f"      said      {(r.get('clarification') or r.get('generated_sql') or '')!r:.140}")
            else:
                print(f"      expected  {' '.join((r.get('expected_sql') or '').split())[:110]}")
                print(f"      got       {' '.join((r.get('generated_sql') or '').split())[:110]}")
                if r.get("error"):
                    print(f"      error     {str(r['error'])[:110]}")
                for issue in (r.get("semantic_issues") or [])[:2]:
                    print(f"      issue     {issue[:104]}")
            print(f"      tokens    {r['prompt_tokens'] + r['completion_tokens']:,}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--compare", default=None,
                    help="an earlier run, to show what moved")
    args = ap.parse_args()

    rows = load(Path(args.run_dir))
    report(rows, Path(args.run_dir).name)

    if args.compare:
        before = {r["turn_id"]: r for r in load(Path(args.compare))}
        after = {r["turn_id"]: r for r in rows}
        shared = sorted(set(before) & set(after))
        fixed = [t for t in shared
                 if not before[t]["result_match"] and after[t]["result_match"]]
        broken = [t for t in shared
                  if before[t]["result_match"] and not after[t]["result_match"]]

        print("\n" + "=" * 74)
        print(f"AGAINST {Path(args.compare).name}  ({len(shared)} shared turns)")
        print("=" * 74)
        print(f"  newly passing  {len(fixed)}   {', '.join(fixed) or '-'}")
        print(f"  newly failing  {len(broken)}  {', '.join(broken) or '-'}")
        for turn_id in broken:
            print(f"\n    {turn_id}  {after[turn_id]['question']!r}")
            print(f"      was  {before[turn_id]['failure_category'] or 'PASS'}")
            print(f"      now  {after[turn_id]['failure_category']}")

        def avg(rs, f):
            return sum(f(r) for r in rs) / len(rs) if rs else 0

        b = [before[t] for t in shared]
        a = [after[t] for t in shared]
        total = lambda r: r["prompt_tokens"] + r["completion_tokens"]
        print(f"\n  avg total tokens   {avg(b, total):>9,.0f} -> {avg(a, total):>9,.0f}")
        print(f"  avg latency (s)    {avg(b, lambda r: r['latency_ms']/1000):>9.1f} -> "
              f"{avg(a, lambda r: r['latency_ms']/1000):>9.1f}")
        no_call = sum(1 for r in a if r.get("preflight_clarified"))
        print(f"  turns answered with no model call: {no_call}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
