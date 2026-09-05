"""Inspect a lean-suite run: what failed, and why.

    python scripts/analyze_lean.py results/lean_state_v1
    python scripts/analyze_lean.py results/lean_state_v1 --compare results/lean_baseline_none

Prints the full record for each failure -- context state, both queries, both
results -- because a bare failure category does not tell you which layer to
fix. Also groups failures by category so a shared root cause is visible as a
pattern rather than as four separate bugs.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def load(run_dir: Path) -> list[dict]:
    f = run_dir / "raw" / "turns.jsonl"
    if not f.exists():
        raise SystemExit(f"no results at {f}")
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


def _rows(res: dict) -> str:
    if not res:
        return "-"
    if res.get("error"):
        return f"ERROR {str(res['error'])[:70]}"
    n = res.get("row_count", "?")
    cols = ",".join(res.get("columns", [])[:6])
    sample = ""
    rs = res.get("rows") or []
    if rs and len(rs[0]) <= 3:
        sample = "  " + "; ".join(str(tuple(r)) for r in rs[:2])
    return f"{n} rows [{cols}]{sample[:80]}"


def summarise(rows: list[dict], label: str) -> dict:
    n = len(rows)
    ok = sum(1 for r in rows if r["result_match"])
    fu = [r for r in rows if r["turn_index"] > 0]
    sa = [r for r in rows if r["turn_index"] == 0 and r["conversation_id"] == r["turn_id"]]
    dec = [r for r in rows if r.get("decision_match") is not None]
    avg = lambda f: sum(f(r) for r in rows) / n if n else 0
    return {
        "label": label, "n": n, "ok": ok,
        "accuracy": ok / n * 100 if n else 0,
        "standalone": (sum(1 for r in sa if r["result_match"]) / len(sa) * 100) if sa else 0,
        "followup": (sum(1 for r in fu if r["result_match"]) / len(fu) * 100) if fu else 0,
        "decision": (sum(1 for r in dec if r["decision_match"]) / len(dec) * 100) if dec else 0,
        "prompt": avg(lambda r: r["prompt_tokens"]),
        "cache_read": avg(lambda r: r["cache_read_tokens"]),
        "completion": avg(lambda r: r["completion_tokens"]),
        "total": avg(lambda r: r["prompt_tokens"] + r["completion_tokens"]),
        "effective": avg(lambda r: (r["prompt_tokens"] - r["cache_read_tokens"])
                         + r["cache_read_tokens"] * 0.1 + r["completion_tokens"]),
        "tools": avg(lambda r: r["tool_call_count"]),
        "latency": avg(lambda r: r["latency_ms"] / 1000),
        "ctx_chars": avg(lambda r: r["context_chars"]),
    }


def print_table(runs: list[dict]) -> None:
    keys = [("accuracy", "accuracy %", "{:.1f}"), ("standalone", "  standalone %", "{:.1f}"),
            ("followup", "  follow-up %", "{:.1f}"), ("decision", "  turn class %", "{:.1f}"),
            ("prompt", "prompt tokens", "{:,.0f}"), ("cache_read", "cache read", "{:,.0f}"),
            ("completion", "completion", "{:,.0f}"), ("total", "total tokens", "{:,.0f}"),
            ("effective", "effective tokens", "{:,.0f}"), ("tools", "tool calls", "{:.1f}"),
            ("latency", "latency (s)", "{:.1f}"), ("ctx_chars", "context chars", "{:.0f}")]
    w = 20
    print(f"{'metric':<20}" + "".join(f"{r['label']:>{w}}" for r in runs))
    print("-" * (20 + w * len(runs)))
    for key, label, fmt in keys:
        print(f"{label:<20}" + "".join(f"{fmt.format(r[key]):>{w}}" for r in runs))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--compare", nargs="*", default=[])
    ap.add_argument("--full", action="store_true", help="print every failure in detail")
    args = ap.parse_args()

    main_rows = load(Path(args.run_dir))
    runs = [summarise(main_rows, Path(args.run_dir).name)]
    others = {}
    for d in args.compare:
        rows = load(Path(d))
        others[d] = rows
        runs.append(summarise(rows, Path(d).name))

    print("=" * (20 + 20 * len(runs)))
    print_table(runs)
    print()

    failures = [r for r in main_rows if not r["result_match"]]
    print(f"failures: {len(failures)}/{len(main_rows)}")
    if failures:
        for cat, c in Counter(r["failure_category"] for r in failures).most_common():
            print(f"  {cat:<28} {c}")

    misread = [r for r in main_rows if r.get("decision_match") is False]
    if misread:
        print(f"\nturn misclassified: {len(misread)}")
        for r in misread:
            print(f"  {r['turn_id']:<8} expected {r['expected_decision']:<10} got {r['decision']}")

    # Where in a thread do failures land? Late failures usually mean state drift.
    by_idx = defaultdict(lambda: [0, 0])
    for r in main_rows:
        by_idx[r["turn_index"]][1] += 1
        if r["result_match"]:
            by_idx[r["turn_index"]][0] += 1
    print("\naccuracy by turn position:")
    for i in sorted(by_idx):
        good, tot = by_idx[i]
        print(f"  turn {i}: {good}/{tot}")

    if failures:
        print("\n" + "=" * 78)
        print("FAILURE DETAIL")
        print("=" * 78)
        for r in failures:
            print(f"\n--- {r['turn_id']}  [{r['failure_category']}]  {r['category']}")
            print(f"  question       : {r['question']}")
            print(f"  conversation   : {r['conversation_id']} turn {r['turn_index']}")
            print(f"  decision       : {r['decision']}"
                  + (f"  (expected {r['expected_decision']})" if r.get("expected_decision") else ""))
            print(f"  context chars  : {r['context_chars']}")
            print(f"  expected sql   : {' '.join((r['expected_sql'] or '').split())[:200]}")
            print(f"  generated sql  : {' '.join((r['generated_sql'] or '-').split())[:200]}")
            print(f"  expected result: {_rows(r['expected_result'])}")
            print(f"  actual result  : {_rows(r['actual_result'])}")
            if r.get("error"):
                print(f"  error          : {str(r['error'])[:160]}")
            print(f"  tokens         : prompt={r['prompt_tokens']:,} "
                  f"cache_read={r['cache_read_tokens']:,} out={r['completion_tokens']:,} "
                  f"tools={r['tool_call_count']} {r['latency_ms']/1000:.1f}s")

    # Regressions relative to the first comparison run.
    for d, rows in others.items():
        base = {r["turn_id"]: r["result_match"] for r in rows}
        regressed = [r["turn_id"] for r in main_rows
                     if base.get(r["turn_id"]) and not r["result_match"]]
        gained = [r["turn_id"] for r in main_rows
                  if base.get(r["turn_id"]) is False and r["result_match"]]
        print(f"\nvs {Path(d).name}:  gained {len(gained)}  regressed {len(regressed)}")
        if gained:
            print(f"  gained   : {', '.join(gained)}")
        if regressed:
            print(f"  REGRESSED: {', '.join(regressed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
