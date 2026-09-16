"""Where a query's time actually goes, measured rather than assumed.

The lean suite reports one number per turn and averages it. That is enough to
notice latency but not to attribute it, and attribution is the whole job here:
before this existed, ~4.5s per query of Claude CLI process startup was being
measured in cli_provider and then discarded, so it appeared in no metric at
all and the model looked twice as expensive as it was.

This runs a fixed set of questions through the real pipeline, repeatedly, and
prints the per-stage breakdown with percentiles. Cold and warm are reported
separately because the first query through a fresh process is not the query a
user typically waits for, and averaging the two hides both.

    python scripts/bench_latency.py                     # default set, 3 reps
    python scripts/bench_latency.py --reps 5
    python scripts/bench_latency.py --questions "one question"
    python scripts/bench_latency.py --out results/bench_before.json

Compare two runs:

    python scripts/bench_latency.py --out results/bench_before.json
    ... make a change ...
    python scripts/bench_latency.py --out results/bench_after.json --compare results/bench_before.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import load_settings  # noqa: E402
from pipeline.context import ConversationState  # noqa: E402
from pipeline.lean_runner import load_gazetteer, run_turn  # noqa: E402
from pipeline.lean_suite import SuiteTurn  # noqa: E402
from pipeline.models import Session  # noqa: E402

# Chosen to exercise different branches rather than to be representative of
# volume: a plain list, an aggregate, a join through the task table, and a
# question whose answer is a single number.
DEFAULT_QUESTIONS = [
    "Show the AR_NPD_Shirting items",
    "How many initiatives are there by status?",
    "Which initiative type has the most items?",
    "Show the open tasks for AR_YD_Suiting",
]

# The stages that are separately measured. `other` is the remainder, and it
# being large means something is happening that nothing here accounts for --
# which is exactly the state this script was written to end.
STAGES = [
    ("llm_wall_ms", "Claude (wall, incl. startup)"),
    ("llm_ms", "  of which CLI-reported"),
    ("db_ms", "Database"),
    ("schema_check_ms", "Schema grounding"),
    ("normalize_ms", "Typo repair"),
    ("safety_ms", "Safety gate"),
    ("followup_ms", "Suggestions"),
]


def pct(values: list[float], p: float) -> float:
    """The p-th percentile, nearest-rank. Small n here, so no interpolation."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(p / 100 * len(ordered) + 0.5)) - 1))
    return ordered[k]


def summarise(rows: list[dict]) -> dict:
    total = [r["latency_ms"] for r in rows]
    out = {
        "n": len(rows),
        "mean_ms": statistics.fmean(total) if total else 0.0,
        "median_ms": statistics.median(total) if total else 0.0,
        "min_ms": min(total) if total else 0.0,
        "max_ms": max(total) if total else 0.0,
        "p95_ms": pct(total, 95),
        "p99_ms": pct(total, 99),
        "stages": {},
    }
    for key, _ in STAGES:
        vals = [r.get(key, 0.0) for r in rows]
        out["stages"][key] = statistics.fmean(vals) if vals else 0.0
    # Everything the named stages do not account for. llm_ms is excluded from
    # the sum because it is a subset of llm_wall_ms, not a sibling of it.
    accounted = sum(v for k, v in out["stages"].items() if k != "llm_ms")
    out["stages"]["other_ms"] = max(0.0, out["mean_ms"] - accounted)
    return out


def show(label: str, s: dict) -> None:
    if not s["n"]:
        print(f"\n{label}: no turns")
        return
    print(f"\n{label}  (n={s['n']})")
    print(f"  {'Total':32} {s['mean_ms']/1000:6.2f}s   "
          f"median {s['median_ms']/1000:5.2f}s  p95 {s['p95_ms']/1000:5.2f}s  "
          f"p99 {s['p99_ms']/1000:5.2f}s  max {s['max_ms']/1000:5.2f}s")
    print()
    for key, name in STAGES:
        v = s["stages"].get(key, 0.0)
        share = (v / s["mean_ms"] * 100) if s["mean_ms"] else 0.0
        marker = "" if key == "llm_ms" else f"{share:5.1f}%"
        print(f"  {name:32} {v/1000:6.2f}s   {marker}")
    other = s["stages"]["other_ms"]
    print(f"  {'Other':32} {other/1000:6.2f}s   "
          f"{(other / s['mean_ms'] * 100) if s['mean_ms'] else 0:5.1f}%")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=3,
                    help="passes over the question set (default 3)")
    ap.add_argument("--questions", nargs="*", default=None,
                    help="override the default question set")
    ap.add_argument("--out", default=None, help="write the summary as JSON")
    ap.add_argument("--compare", default=None,
                    help="a previous --out file, to print a before/after table")
    args = ap.parse_args()

    questions = args.questions or DEFAULT_QUESTIONS
    settings = load_settings()
    gazetteer = load_gazetteer()

    print(f"{len(questions)} questions x {args.reps} reps = "
          f"{len(questions) * args.reps} turns. This calls the real model.\n")

    rows: list[dict] = []
    for rep in range(args.reps):
        for q in questions:
            # A fresh state per turn: this measures single-question latency,
            # not conversational follow-up, and carrying state would let one
            # turn's filters change the next turn's SQL.
            state = ConversationState()
            session = Session(session_id=f"bench{len(rows)}", lean=True)
            turn = SuiteTurn(id=f"bench{len(rows)}", question=q, expected_sql=None,
                             category="bench", conversation_id=f"bench{len(rows)}",
                             turn_index=0)
            started = time.perf_counter()
            r = run_turn(turn, state, gazetteer, settings, None, "strict", session)
            wall = (time.perf_counter() - started) * 1000
            row = {"rep": rep, "question": q, "latency_ms": r.latency_ms or wall}
            for key, _ in STAGES:
                row[key] = getattr(r, key, 0.0)
            row["sql"] = bool(r.generated_sql)
            rows.append(row)
            print(f"  rep{rep} {q[:44]:44} {row['latency_ms']/1000:5.2f}s"
                  f"  (claude {row['llm_wall_ms']/1000:5.2f}s)", flush=True)

    per_rep = len(questions)
    cold, warm = rows[:per_rep], rows[per_rep:]

    print("\n" + "=" * 78)
    show("COLD (first pass)", summarise(cold))
    if warm:
        show("WARM (subsequent passes)", summarise(warm))
    show("ALL", summarise(rows))

    report = {"questions": questions, "reps": args.reps,
              "cold": summarise(cold), "warm": summarise(warm) if warm else None,
              "all": summarise(rows), "rows": rows}

    if args.compare:
        prior = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        key = "warm" if (warm and prior.get("warm")) else "all"
        a, b = prior[key], report[key]
        print(f"\n{'=' * 78}\nBEFORE vs AFTER ({key})\n")
        print(f"  {'':32} {'before':>9} {'after':>9} {'delta':>9}")
        print(f"  {'Total (mean)':32} {a['mean_ms']/1000:8.2f}s "
              f"{b['mean_ms']/1000:8.2f}s {(b['mean_ms']-a['mean_ms'])/1000:+8.2f}s")
        for k, name in STAGES:
            av, bv = a["stages"].get(k, 0.0), b["stages"].get(k, 0.0)
            print(f"  {name:32} {av/1000:8.2f}s {bv/1000:8.2f}s {(bv-av)/1000:+8.2f}s")

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
