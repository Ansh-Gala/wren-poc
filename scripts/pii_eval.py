"""Measure the PII detector on real questions, with no LLM and no database.

    python scripts/pii_eval.py --questions path/to/questions.csv
    python scripts/pii_eval.py --questions questions.csv --out results/pii_eval.json

Two numbers decide whether PII_ALIASING is worth turning on with a model:

  over-masking   real questions changed by a false detection. Each one hides
                 a word the LLM needed, so the answer can get worse.
  canary catch   synthetic personal data inserted into real questions, and
                 the share of it replaced. A miss is a leak.

The questions file is a CSV with a "question" column, or plain text with one
question per line. The canary values are made up; nothing real is inserted.
The answer-quality half of the evaluation -- the lean suite run with
PII_ALIASING=true against with it off -- needs the LLM and is run separately.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import time
from collections import Counter
from pathlib import Path

import _bootstrap  # noqa: F401

from config.settings import load_settings
from pipeline.metadata import enable_site_metadata
from pipeline.pii import PiiVault, get_anonymizer

# Made-up values, one list per type, and the phrasing each is inserted with.
CANARIES = {
    "person": (["Rahul Sharma", "Priya Nair", "Amit Rao", "Fatima Sheikh", "Karan Mehta",
                "Neha Joshi", "Sunil Verma", "Anita Desai"],
               ["{q} for {v}", "{q}, assigned to {v}", "{v} asked: {q}"]),
    "email": (["rahul.sharma@example.com", "p.nair@acme.co.in", "amit_rao@mailinator.com",
               "neha.joshi@example.org"],
              ["{q} and email it to {v}", "{q} (contact {v})"]),
    "location": (["Mumbai", "Pune", "Bengaluru", "Indore", "Chennai", "Ahmedabad"],
                 ["{q} in {v}", "{q} for the {v} office"]),
    "phone number": (["+91 98200 12345", "9820012345", "022-2345 6789"],
                     ["{q}, call {v}", "{q} and text {v}"]),
}


def read_questions(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        rows = csv.DictReader(text.splitlines())
        questions = [str(row.get("question") or "") for row in rows]
    else:
        questions = text.splitlines()
    return [" ".join(q.split()) for q in questions if q.strip()]


def over_masking(anonymizer, questions: list[str]) -> dict:
    altered, flagged = 0, Counter()
    for question in questions:
        vault = PiiVault()
        if anonymizer.apply(question, vault) != question:
            altered += 1
            flagged.update(f"{e['original']} ({e['label']})" for e in vault.new)
    return {"questions": len(questions), "altered": altered,
            "altered_pct": round(100 * altered / max(1, len(questions)), 1),
            "most_flagged": flagged.most_common(15)}


def canary_catch(anonymizer, questions: list[str], per_type: int, seed: int) -> dict:
    rng = random.Random(seed)
    out = {}
    for label, (values, templates) in CANARIES.items():
        caught, misses = 0, []
        for _ in range(per_type):
            value = rng.choice(values)
            text = rng.choice(templates).format(q=rng.choice(questions), v=value)
            if value.casefold() not in anonymizer.apply(text, PiiVault()).casefold():
                caught += 1
            else:
                misses.append(text)
        out[label] = {"inserted": per_type, "caught": caught,
                      "caught_pct": round(100 * caught / max(1, per_type), 1),
                      "missed_examples": misses[:5]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--canaries", type=int, default=50, help="inserted per type")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    # As the server does: the site's tables belong to the schema vocabulary.
    enable_site_metadata()
    settings = load_settings()
    anonymizer = get_anonymizer(settings)
    started = time.perf_counter()
    anonymizer.load()
    load_s = time.perf_counter() - started

    questions = read_questions(args.questions)
    started = time.perf_counter()
    masking = over_masking(anonymizer, questions)
    per_question_ms = (time.perf_counter() - started) * 1000 / max(1, len(questions))
    canaries = canary_catch(anonymizer, questions, args.canaries, args.seed)

    report = {"model": settings.pii_model, "threshold": settings.pii_threshold,
              "load_s": round(load_s, 1), "ms_per_question": round(per_question_ms, 1),
              "over_masking": masking, "canaries": canaries}

    print(f"model {settings.pii_model} at threshold {settings.pii_threshold}; "
          f"loaded in {load_s:.1f} s; {per_question_ms:.0f} ms per question")
    print(f"\nOver-masking: {masking['altered']} of {masking['questions']} real questions "
          f"changed ({masking['altered_pct']}%)")
    for text, count in masking["most_flagged"]:
        print(f"  {count:>3}  {text}")
    print("\nCanaries caught (a miss is a leak):")
    for label, row in canaries.items():
        print(f"  {label:<13} {row['caught']:>3} / {row['inserted']}  ({row['caught_pct']}%)")
        for example in row["missed_examples"][:2]:
            print(f"      missed: {example}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
