"""Re-score a completed run on semantic SQL correctness.

    python scripts/semantic_rescore.py results/expansion_v1
    python scripts/semantic_rescore.py results/lean_state_v4 --detail

Result accuracy answers "did it return the right rows". That is necessary but
not sufficient: a query can return the right rows from the wrong column, and
result comparison will pass it. This reads the stored SQL from a finished run
and reports the two metrics side by side, so the gap between them is visible.

The interesting number is the third one -- turns that passed on results while
being semantically wrong. Those are the failures the benchmark was hiding.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import _bootstrap  # noqa: F401

from benchmark.sql_semantics import (
    PROJECTION_EXACT, PROJECTION_MISSING, PROJECTION_SUBSTITUTED,
    PROJECTION_SUPERSET, compare,
)


def load(run_dir: Path) -> list[dict]:
    f = run_dir / "raw" / "turns.jsonl"
    if not f.exists():
        raise SystemExit(f"no results at {f}")
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--detail", action="store_true", help="show every semantic issue")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    rows = load(Path(args.run_dir))
    ordered_ids = _ordered_lookup()

    result_ok = semantic_ok = both = hidden = 0
    projection = Counter()
    component_fail = Counter()
    hidden_rows: list[tuple[dict, object]] = []
    semantic_fail_rows: list[tuple[dict, object]] = []

    for r in rows:
        c = compare(r["expected_sql"], r["generated_sql"],
                    ordered=ordered_ids.get(r["turn_id"], False))
        r_ok = bool(r["result_match"])
        s_ok = c.semantically_correct
        result_ok += r_ok
        semantic_ok += s_ok
        both += r_ok and s_ok
        projection[c.projection_verdict] += 1
        if not s_ok:
            semantic_fail_rows.append((r, c))
            for name in ("tables", "filters", "joins", "aggregates",
                         "grouping", "ordering", "limit"):
                if not getattr(c, f"{name}_match"):
                    component_fail[name] += 1
            if c.projection_verdict in (PROJECTION_MISSING, PROJECTION_SUBSTITUTED):
                component_fail[f"projection:{c.projection_verdict}"] += 1
        if r_ok and not s_ok:
            hidden += 1
            hidden_rows.append((r, c))

    n = len(rows)
    print("=" * 72)
    print(f"SEMANTIC RESCORE  {Path(args.run_dir).name}   ({n} turns)")
    print("=" * 72)
    print(f"  result accuracy      {result_ok}/{n}  ({result_ok / n * 100:.1f}%)")
    print(f"  semantic accuracy    {semantic_ok}/{n}  ({semantic_ok / n * 100:.1f}%)")
    print(f"  both                 {both}/{n}  ({both / n * 100:.1f}%)")
    print(f"  RIGHT ROWS, WRONG SQL {hidden}/{n}  <- hidden by result matching")
    print()
    print("  projection:")
    for verdict in (PROJECTION_EXACT, PROJECTION_SUPERSET,
                    PROJECTION_MISSING, PROJECTION_SUBSTITUTED):
        cnt = projection.get(verdict, 0)
        flag = "   <- counts against correctness" if verdict in (
            PROJECTION_MISSING, PROJECTION_SUBSTITUTED) and cnt else ""
        print(f"    {verdict:<14} {cnt:>4}  ({cnt / n * 100:.1f}%){flag}")

    if component_fail:
        print("\n  semantic failures by component:")
        for name, cnt in component_fail.most_common():
            print(f"    {name:<26} {cnt}")

    if hidden_rows:
        print("\n" + "=" * 72)
        print("PASSED ON RESULTS BUT SEMANTICALLY WRONG")
        print("=" * 72)
        for r, c in hidden_rows:
            print(f"\n  {r['turn_id']}  {r['question'][:56]}")
            for issue in c.issues:
                print(f"     - {issue}")
            print(f"     expected : {' '.join((r['expected_sql'] or '').split())[:130]}")
            print(f"     generated: {' '.join((r['generated_sql'] or '-').split())[:130]}")

    if args.detail and semantic_fail_rows:
        print("\n" + "=" * 72)
        print("ALL SEMANTIC FAILURES")
        print("=" * 72)
        for r, c in semantic_fail_rows:
            mark = "result-ok" if r["result_match"] else "result-fail"
            print(f"\n  {r['turn_id']} [{mark}]  {r['question'][:52]}")
            for issue in c.issues:
                print(f"     - {issue}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "turns": n, "result_accuracy": result_ok / n * 100,
            "semantic_accuracy": semantic_ok / n * 100,
            "hidden_failures": hidden,
            "projection": dict(projection),
            "component_failures": dict(component_fail),
        }, indent=2), encoding="utf-8")
    return 0


def _ordered_lookup() -> dict[str, bool]:
    """Which turns actually demanded an order, across every suite."""
    from benchmark.lean_suite import all_turns, load_suite
    out: dict[str, bool] = {}
    for name in ("lean_questions.yaml", "lean_stress.yaml", "expansion_questions.yaml",
                 "targeted_questions.yaml"):
        path = Path(__file__).resolve().parents[1] / "benchmark" / name
        if not path.exists():
            continue
        for t in all_turns(load_suite(path)):
            out[t.id] = t.ordered
    return out


if __name__ == "__main__":
    raise SystemExit(main())
