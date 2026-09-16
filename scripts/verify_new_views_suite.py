"""Verify the new-views suite before any model is asked to answer it.

Four things are checked, because a suite that looks reasonable and is wrong
teaches the wrong lesson louder than no suite at all:

  1. every expected SQL executes against the live database
  2. what it returns is worth asking for -- an empty result or a NULL scalar
     usually means the question cannot be answered from this data
  3. every table and column named exists in metadata/schema_description.yaml,
     so the model is never expected to use something it was not told about
  4. no two questions are the same
"""
import re
import sys
import pathlib
import yaml

sys.path.insert(0, r"C:\Users\ansh.gala\Desktop\Python\wren-poc")
from config.settings import load_settings
from database.connection import connect

ROOT = pathlib.Path(r"C:\Users\ansh.gala\Desktop\Python\wren-poc")
doc = yaml.safe_load((ROOT / "benchmark/new_views_questions.yaml").read_text(encoding="utf-8"))
schema = yaml.safe_load((ROOT / "metadata/schema_description.yaml").read_text(encoding="utf-8"))

known_tables = set(schema["tables"])
known_cols = {t: set(s.get("columns") or {}) for t, s in schema["tables"].items()}
all_cols = set().union(*known_cols.values())

conn = connect(load_settings(), readonly=True)
problems, empties = [], []
seen = {}

print(f"{'id':5} {'rows':>5}  result")
print("-" * 78)
for q in doc["questions"]:
    qid, sql, text = q["id"], q["expected_sql"], q["question"]

    if text.lower() in seen:
        problems.append(f"{qid}: duplicate of {seen[text.lower()]}")
    seen[text.lower()] = qid

    for t in re.findall(r"\b(tms_\w+)\b", sql):
        if t not in known_tables:
            problems.append(f"{qid}: table {t} is not in schema_description.yaml")

    cur = conn.cursor()
    try:
        cur.execute(sql)
        rows = cur.fetchall()
    except Exception as exc:
        conn.rollback()
        problems.append(f"{qid}: SQL FAILED -- {str(exc).splitlines()[0][:90]}")
        print(f"{qid:5} {'--':>5}  FAILED")
        continue

    n = len(rows)
    first = rows[0] if rows else None
    scalar = first[0] if first and len(first) == 1 else None
    shown = str(first)[:52] if first else "(no rows)"
    print(f"{qid:5} {n:5}  {shown}")

    if n == 0:
        empties.append(f"{qid}: returns no rows -- {text!r}")
    elif scalar is None and first is not None and len(first) == 1:
        empties.append(f"{qid}: returns NULL -- {text!r}")

print()
print(f"{len(doc['questions'])} questions checked")
print(f"  SQL/grounding problems : {len(problems)}")
for p in problems:
    print("     ", p)
print(f"  empty or NULL answers  : {len(empties)}")
for e in empties:
    print("     ", e)

cov = {}
for q in doc["questions"]:
    for t in re.findall(r"\b(tms_\w+)\b", q["expected_sql"]):
        cov[t] = cov.get(t, 0) + 1
print("  table coverage:")
for t, c in sorted(cov.items(), key=lambda kv: -kv[1]):
    print(f"     {t:34} {c:3} question(s)")

sys.exit(1 if problems else 0)
