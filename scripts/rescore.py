"""Re-score a finished run without calling Claude again.

    python scripts/rescore.py results/smoke/raw/D.strict.jsonl

Reads the recorded SQL, re-executes both the generated and the expected query
against PostgreSQL, and reports two metrics:

  strict   same rows AND same columns
  rows     same rows, extra columns tolerated

The second exists because several questions genuinely do not say which columns
to return. "Which tasks are currently blocked?" was answered with
`SELECT id, name, workflow_id, assigned_user_id, due_date` against a ground
truth of `SELECT name` -- the same seven tasks, so the filter was right and only
the projection differed. Counting that as a failure understates the semantic
layer; counting it as a pass hides real errors. Reporting both keeps them
separate.

Costs nothing: no Claude invocation, only SQL replay.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from benchmark.evaluator import compare_results, compare_row_subset
from benchmark.questions import load_questions
from config.logging import register_secrets
from config.settings import load_settings
from database.connection import run_readonly


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("jsonl", help="a results/**/raw/*.jsonl file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    register_secrets(settings.secrets())
    ordered_by_id = {q.id: q.ordered for q in load_questions()}

    path = Path(args.jsonl)
    records = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not records:
        print(f"no records in {path}")
        return 1

    strict_pass = rows_pass = 0
    only_columns: list[str] = []
    genuinely_wrong: list[tuple[str, str]] = []
    not_executable: list[str] = []

    for rec in records:
        qid = rec["question_id"]
        ordered = ordered_by_id.get(qid, False)
        gen = rec.get("generated_sql")

        if not gen or not rec.get("execution_success"):
            not_executable.append(qid)
            continue

        expected = run_readonly(settings, rec["expected_sql"], settings.statement_timeout_ms)
        actual = run_readonly(settings, gen, settings.statement_timeout_ms)

        strict = compare_results(expected, actual, ordered)
        subset = compare_row_subset(expected, actual, ordered)
        strict_pass += strict
        rows_pass += subset

        if strict:
            verdict = "PASS"
        elif subset:
            verdict = "EXTRA_COLUMNS"
            only_columns.append(qid)
        else:
            verdict = rec.get("failure_category") or "FAIL"
            genuinely_wrong.append((qid, verdict))

        if args.verbose or not strict:
            print(f"  {qid:<5} {rec['category']:<2} {verdict:<16} "
                  f"exp={len(expected.rows)}r/{len(expected.columns)}c  "
                  f"got={len(actual.rows)}r/{len(actual.columns)}c")

    n = len(records)
    print(f"\n{'=' * 56}")
    print(f"RE-SCORED  {path.name}   ({n} questions)")
    print(f"{'=' * 56}\n")
    print(f"  strict match (rows + columns)   {strict_pass:>3} / {n}   "
          f"{strict_pass / n * 100:>6.2f}%")
    print(f"  right rows (columns tolerated)  {rows_pass:>3} / {n}   "
          f"{rows_pass / n * 100:>6.2f}%")
    print()
    print(f"  failed on projection only       {len(only_columns):>3}   "
          f"{', '.join(only_columns) if only_columns else '-'}")
    print(f"  genuinely wrong results         {len(genuinely_wrong):>3}   "
          f"{', '.join(q for q, _ in genuinely_wrong) if genuinely_wrong else '-'}")
    print(f"  never executed                  {len(not_executable):>3}   "
          f"{', '.join(not_executable) if not_executable else '-'}")

    if genuinely_wrong:
        print("\n  Genuine failures by category:")
        counts: dict[str, int] = {}
        for _, cat in genuinely_wrong:
            counts[cat] = counts.get(cat, 0) + 1
        for cat, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"    {cat:<28} {count}")

    wren_missing = [r["question_id"] for r in records if r.get("wren_tool_calls", 0) == 0]
    print(f"\n  Wren MCP tools called on {n - len(wren_missing)}/{n} questions")
    if wren_missing:
        print(f"  WARNING: no Wren tools on {', '.join(wren_missing)} - those "
              f"measure Claude alone")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
