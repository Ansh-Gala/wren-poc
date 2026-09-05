"""Execute every ground-truth query against the real database.

    python scripts/verify_ground_truth.py [--verbose]

Exits non-zero if ANY expected query fails, so benchmark setup halts rather
than scoring generated SQL against a reference that does not run. Also warns
about questions whose expected result is empty: a question no row can satisfy
would be passed by almost any wrong query and measures nothing.
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from benchmark.questions import load_questions
from config.logging import register_secrets
from config.settings import load_settings
from database.connection import run_readonly


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="show every query's row count")
    args = parser.parse_args()

    settings = load_settings()
    register_secrets(settings.secrets())
    questions = load_questions()

    failures: list[tuple[str, str]] = []
    empty: list[str] = []

    print(f"Verifying {len(questions)} ground-truth queries against "
          f"{settings.pg_database}...\n")

    for q in questions:
        if q.expected_sql is None:
            if args.verbose:
                print(f"  skip  {q.id}  (No expected SQL)")
            continue
        result = run_readonly(settings, q.expected_sql, settings.statement_timeout_ms)
        if result.error:
            failures.append((q.id, result.error.splitlines()[0]))
            print(f"  FAIL  {q.id}  {result.error.splitlines()[0]}")
            continue
        if not result.rows:
            empty.append(q.id)
        if args.verbose:
            print(f"  ok    {q.id}  {len(result.rows):>3} rows, "
                  f"{len(result.columns)} cols")

    categories = sorted({q.category for q in questions})
    print(f"\n{len(questions) - len(failures)}/{len(questions)} queries executed "
          f"successfully across {len(categories)} categories "
          f"({''.join(categories)}).")

    if empty:
        print(f"\nWARNING: {len(empty)} question(s) return no rows: {', '.join(empty)}")
        print("  An empty expected result is nearly impossible to get wrong, so "
              "these inflate the score without testing anything.")

    if failures:
        print(f"\n{len(failures)} ground-truth quer(ies) FAILED:")
        for qid, error in failures:
            print(f"  {qid}: {error}")
        print("\nFix these before running the benchmark. Ground truth must be "
              "correct by construction; the benchmark cannot score against a "
              "reference that does not run.")
        return 1

    print("\nAll ground truth verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
