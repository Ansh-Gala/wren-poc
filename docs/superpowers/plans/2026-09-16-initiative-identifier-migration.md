# Business Object → Initiative: Identifier Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the technical identifiers `tms_business_object_flat`, `business_object_*` and `bo_id` to their Initiative equivalents through the whole chatbot stack — Postgres views, metadata, Python, PHP, and the chat grid — while proving the rename changed no result.

**Architecture:** The `tms_*_flat` objects are **views**, not tables, so the rename is a sequence of `ALTER VIEW … RENAME COLUMN` statements — no Drupal table is touched, no data moves, and grants are preserved. Old view names survive the migration as passthrough compatibility views, which is what lets the benchmark stay green while its 794 expected-SQL statements are converted and re-verified one suite at a time. The correctness proof is differential: every expected SQL must return a byte-identical result set before and after. At the one place the chatbot hands off to the legacy TMS dialog, the new vocabulary is translated back to `bo_id` rather than propagated.

**Tech Stack:** PostgreSQL views, Python 3.12 / psycopg 3 / pytest, PHP 8 (Drupal module `vf_sql_chatbot`), React 18 + AG Grid Enterprise 32.3.3.

## Why this plan exists

`docs/superpowers/specs/2026-09-09-initiative-phase-roadmap.md`, Plan 2, recorded the opposite decision on 9 September 2026: *"the technical identifiers stay… renaming them would break both implementations and every recorded suite."* That boundary was deliberately reversed by the human partner on 16 September 2026, with the blast radius below on the table. This plan supersedes that boundary and nothing else in the roadmap.

## Global Constraints

- **`business_unit` is never renamed.** It is a different entity from Business Object. A per-word substitution that turns "business" into "initiative" corrupts it. Every rename here is a whole-identifier match, never a substring pass. The trap is already documented and tested in `tests/test_initiative_terms.py`.
- **`metadata/*.yaml` exists twice and must stay byte-identical**, in `wren-poc/metadata/` and `dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/metadata/`. Verify with `md5sum` after every metadata task.
- **The parity harness compares the built system prompt byte for byte.** Any metadata edit changes the prompt; `tests/parity/check.php` must be re-run and its recorded md5 updated in the same task.
- **The legacy TMS app is out of scope.** ~380 of the frontend's 386 `bo_id` references belong to `track_bos`, `BODetails` and the workflow modeler. Those keep `bo_id`. Only the 6 chatbot references are in scope.
- **`wren_ro` must hold `SELECT` on every new view and nothing more.** The read-only role is the only barrier preventing generated SQL from reading history tables. Re-grant explicitly; never `GRANT ALL`.
- **Recorded accuracy figures in `results/` become non-comparable** once the benchmark is converted. Task 9 records that fact rather than hiding it.
- Database `arvind_retail_chatbot_test_1` on `localhost:5432`; owner role `postgres`, read-only role `wren_ro`.
- Known-good baseline before any work: **402 passed, 9 failed, 33 skipped**. Those 9 failures predate this work (they come from commit `438bafa` dropping `active_user` and the user/task rules) and are not this plan's to fix. "No new failures" means exactly those 9.

---

## The Name Mapping

The single source of truth for every task. 29 columns across 4 views.

### `tms_business_object_flat` → `tms_initiative_flat`

| Old | New |
| --- | --- |
| `business_object_id` | `initiative_id` |
| `business_object_ref_id` | `initiative_ref_id` |
| `business_unit` | **`business_unit` (UNCHANGED)** |
| `business_object_type` | `initiative_type` |
| `business_object_color` | `initiative_color` |
| `business_object_note` | `initiative_note` |
| `business_object_created_at` | `initiative_created_at` |
| `business_object_updated_at` | `initiative_updated_at` |
| `business_object_client_due_at` | `initiative_client_due_at` |
| `business_object_status` | `initiative_status` |
| `business_object_start_date` | `initiative_start_date` |
| `business_object_end_date` | `initiative_end_date` |
| `business_object_expected_completion_date` | `initiative_expected_completion_date` |

Every other column (`common_buffer`, `workflow_id`, `total_task_count`, `open_tasks_list`, …) is unchanged.

### `tms_business_object_attributes_flat` → `tms_initiative_attributes_flat`

| Old | New |
| --- | --- |
| `business_object_id` | `initiative_id` |
| `initiative_type` | `attribute_initiative_type` |

**The collision, and why the second row exists.** This view already has a column named `initiative_type`, sourced from `json_data ->> 'initiative_type'`. It is a customer-supplied JSON attribute — a different thing from the canonical type column. Once `business_object_type` becomes `initiative_type`, the ONE_TO_ONE join declared at `metadata/schema_description.yaml:617` projects two columns named `initiative_type`. The JSON attribute is the one that moves, because the canonical column is the one the business rules and the gazetteer reference.

### `tms_task_flat` and `tms_issue_flat` (view names unchanged)

| Old | New |
| --- | --- |
| `bo_id` | `initiative_id` |
| `business_object_ref_id` | `initiative_ref_id` |
| `business_unit` | **`business_unit` (UNCHANGED)** |
| `business_object_status` | `initiative_status` |
| `business_object_type` | `initiative_type` |
| `business_object_color` | `initiative_color` |
| `is_business_object_delayed` | `is_initiative_delayed` |

`tms_role_flat`, `tms_user_flat` and `tms_user_department_flat` carry none of this vocabulary and are not touched.

### The canonical sed block

Referenced by Tasks 5, 6 and 7. Longest identifiers first, so `business_object_status` is never half-matched by the `business_object_id` rule. `\b` anchors keep it a whole-identifier pass.

```bash
sed -i -E \
  -e 's/\btms_business_object_attributes_flat\b/tms_initiative_attributes_flat/g' \
  -e 's/\btms_business_object_flat\b/tms_initiative_flat/g' \
  -e 's/\bis_business_object_delayed\b/is_initiative_delayed/g' \
  -e 's/\bbusiness_object_expected_completion_date\b/initiative_expected_completion_date/g' \
  -e 's/\bbusiness_object_client_due_at\b/initiative_client_due_at/g' \
  -e 's/\bbusiness_object_created_at\b/initiative_created_at/g' \
  -e 's/\bbusiness_object_updated_at\b/initiative_updated_at/g' \
  -e 's/\bbusiness_object_start_date\b/initiative_start_date/g' \
  -e 's/\bbusiness_object_end_date\b/initiative_end_date/g' \
  -e 's/\bbusiness_object_ref_id\b/initiative_ref_id/g' \
  -e 's/\bbusiness_object_status\b/initiative_status/g' \
  -e 's/\bbusiness_object_color\b/initiative_color/g' \
  -e 's/\bbusiness_object_note\b/initiative_note/g' \
  -e 's/\bbusiness_object_type\b/initiative_type/g' \
  -e 's/\bbusiness_object_id\b/initiative_id/g' \
  -e 's/\bbo_id\b/initiative_id/g' \
  "$f"
```

After every use of this block, run the carve-out check:

```bash
grep -c "initiative_unit" "$f"   # MUST be 0 — if not, it was a substring pass; revert
```

---

## File Structure

**Created:**
- `database/migrations/2026-09-16_initiative_rename.sql` — forward DDL: 4 renamed views + 2 compatibility views
- `database/migrations/2026-09-16_initiative_rename_rollback.sql` — drops the new, restores the old
- `database/migrations/2026-09-16_drop_compat_views.sql` — Task 10
- `scripts/verify_rename_equivalence.py` — the differential prover; the safety net for Tasks 3–6
- `tests/test_rename_equivalence.py` — tests for the prover
- `results/2026-09-16-initiative-rename-rebaseline.md` — the honesty record

**Modified:** `metadata/*.yaml` (5 files ×2 repos), `benchmark/*.yaml` (7 files, 794 occurrences), seven `pipeline/` modules, four `scripts/build_*` suite builders, six Drupal `src/Service/` classes, `tests/parity/check.php`, and `src/components/SqlChatbot/ChatResultGrid.jsx`.

---

### Task 1: The migration DDL and its rollback

**Files:**
- Create: `database/migrations/2026-09-16_initiative_rename.sql`
- Create: `database/migrations/2026-09-16_initiative_rename_rollback.sql`

**Interfaces:**
- Produces: views `tms_initiative_flat`, `tms_initiative_attributes_flat`; updated `tms_task_flat` / `tms_issue_flat`; compatibility views `tms_business_object_flat`, `tms_business_object_attributes_flat`.

**Why `ALTER VIEW`, not `CREATE OR REPLACE VIEW`.** Postgres rejects `CREATE OR REPLACE VIEW` when the replacement changes a column *name* — it can only add columns to the end. `ALTER VIEW … RENAME COLUMN` (Postgres 9.2+; this database is 16.12) is the supported path, and it is better on three counts: it is atomic, it leaves the view body untouched so there is no chance of mistyping a `CASE` expression, and **it preserves grants**, so `wren_ro` keeps its `SELECT` without a re-`GRANT`. Verified: no other view or matview reads these four, so nothing cascades.

- [ ] **Step 1: Write the forward migration**

```sql
-- database/migrations/2026-09-16_initiative_rename.sql
-- Views only. No Drupal table (vf_*) is touched, and no data moves.
-- ALTER VIEW preserves grants; the compatibility views at the foot are new
-- objects and so need their own GRANT.

ALTER VIEW tms_business_object_flat RENAME TO tms_initiative_flat;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_id       TO initiative_id;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_ref_id   TO initiative_ref_id;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_type     TO initiative_type;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_color    TO initiative_color;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_note     TO initiative_note;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_created_at TO initiative_created_at;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_updated_at TO initiative_updated_at;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_client_due_at TO initiative_client_due_at;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_status   TO initiative_status;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_start_date TO initiative_start_date;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_end_date TO initiative_end_date;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_expected_completion_date TO initiative_expected_completion_date;
-- business_unit is deliberately absent. It is a different entity.

ALTER VIEW tms_business_object_attributes_flat RENAME TO tms_initiative_attributes_flat;
-- The JSON attribute moves first so it is out of the way; see the collision note.
ALTER VIEW tms_initiative_attributes_flat RENAME COLUMN initiative_type TO attribute_initiative_type;
ALTER VIEW tms_initiative_attributes_flat RENAME COLUMN business_object_id TO initiative_id;

ALTER VIEW tms_task_flat RENAME COLUMN bo_id                     TO initiative_id;
ALTER VIEW tms_task_flat RENAME COLUMN business_object_ref_id    TO initiative_ref_id;
ALTER VIEW tms_task_flat RENAME COLUMN business_object_status    TO initiative_status;
ALTER VIEW tms_task_flat RENAME COLUMN business_object_type      TO initiative_type;
ALTER VIEW tms_task_flat RENAME COLUMN business_object_color     TO initiative_color;
ALTER VIEW tms_task_flat RENAME COLUMN is_business_object_delayed TO is_initiative_delayed;

ALTER VIEW tms_issue_flat RENAME COLUMN bo_id                     TO initiative_id;
ALTER VIEW tms_issue_flat RENAME COLUMN business_object_ref_id    TO initiative_ref_id;
ALTER VIEW tms_issue_flat RENAME COLUMN business_object_status    TO initiative_status;
ALTER VIEW tms_issue_flat RENAME COLUMN business_object_type      TO initiative_type;
ALTER VIEW tms_issue_flat RENAME COLUMN business_object_color     TO initiative_color;
ALTER VIEW tms_issue_flat RENAME COLUMN is_business_object_delayed TO is_initiative_delayed;
```

- [ ] **Step 2: Write the rollback as the exact inverse, then append the compatibility views to the forward file**

The rollback is every `ALTER` above, reversed in order with the arguments swapped, preceded by dropping the two compatibility views:

```sql
-- database/migrations/2026-09-16_initiative_rename_rollback.sql
DROP VIEW IF EXISTS tms_business_object_flat;
DROP VIEW IF EXISTS tms_business_object_attributes_flat;

ALTER VIEW tms_issue_flat RENAME COLUMN is_initiative_delayed TO is_business_object_delayed;
-- … the remaining inverses, in reverse order …
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_id TO business_object_id;
ALTER VIEW tms_initiative_flat RENAME TO tms_business_object_flat;
```

Then append to the **forward** file the compatibility views, which are what keep the un-converted benchmark suites passing. These are new objects, so they do need an explicit `GRANT`:

```sql
-- Compatibility: the old names stay readable until Task 9 converts the last
-- suite. Dropped in Task 10. Column order matches the pre-migration views.
CREATE OR REPLACE VIEW tms_business_object_flat AS
  SELECT initiative_id                        AS business_object_id,
         initiative_ref_id                    AS business_object_ref_id,
         business_unit,
         initiative_type                      AS business_object_type,
         initiative_color                     AS business_object_color,
         initiative_note                      AS business_object_note,
         initiative_created_at                AS business_object_created_at,
         initiative_updated_at                AS business_object_updated_at,
         initiative_client_due_at             AS business_object_client_due_at,
         common_buffer, buff_penetration_prcnt, buff_penetration_days,
         total_remaining_duration, days_to_due_date, hold_days,
         workflow_id, workflow_code, workflow_name,
         initiative_status                    AS business_object_status,
         initiative_start_date                AS business_object_start_date,
         initiative_end_date                  AS business_object_end_date,
         elapsed_days,
         initiative_expected_completion_date  AS business_object_expected_completion_date,
         short_closed_by, short_closed_on,
         current_active_milestone, current_milestone_delay_days,
         current_milestone_expected_completion,
         total_task_count, open_task_count, closed_task_count,
         delayed_task_count, open_tasks_list
  FROM tms_initiative_flat;
GRANT SELECT ON tms_business_object_flat TO wren_ro;

CREATE OR REPLACE VIEW tms_business_object_attributes_flat AS
  SELECT initiative_id             AS business_object_id,
         attribute_initiative_type AS initiative_type,
         category, end_date, season, program, request_receipt_date, pi_date,
         stage, data_color, brandix_t_a, csbd_date, batch_no, item_code,
         volume, event, channel, vendor, total_qty, moq, number_of_options,
         count, merchant_name, person, assign_date, quality, buyer,
         mcode_won_number, ex_mill_date, garment_desc, matching_instruction,
         fabric_description, dye_part, shade, internal_or_confirmed,
         division, style_or_garment_code
  FROM tms_initiative_attributes_flat;
GRANT SELECT ON tms_business_object_attributes_flat TO wren_ro;
```

- [ ] **Step 3: Commit the DDL without applying it**

```bash
git add database/migrations/
git commit -m "Record the Initiative rename DDL and its rollback"
```

---

### Task 2: The differential prover

**Files:**
- Create: `scripts/verify_rename_equivalence.py`
- Test: `tests/test_rename_equivalence.py`

**Interfaces:**
- Produces: `verify_pairs(pairs: list[tuple[str, str]]) -> list[str]` — a list of human-readable failure descriptions, empty when every pair agrees.

This is the safety net for the whole migration. Written **before** the migration is applied, it is what makes Tasks 3–6 verifiable rather than hopeful.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rename_equivalence.py
from scripts.verify_rename_equivalence import verify_pairs


def test_identical_queries_agree():
    assert verify_pairs([("SELECT 1 AS a", "SELECT 1 AS a")]) == []


def test_differing_queries_are_reported():
    failures = verify_pairs([("SELECT 1 AS a", "SELECT 2 AS a")])
    assert len(failures) == 1
    assert "row 0" in failures[0]


def test_a_column_rename_is_not_a_difference():
    """Values are compared positionally. The heading is meant to change."""
    assert verify_pairs([("SELECT 1 AS business_object_id",
                          "SELECT 1 AS initiative_id")]) == []


def test_a_broken_new_query_is_reported_not_raised():
    failures = verify_pairs([("SELECT 1", "SELECT * FROM tms_nope")])
    assert len(failures) == 1
    assert "new query failed" in failures[0]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/Scripts/pytest.exe tests/test_rename_equivalence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.verify_rename_equivalence'`

- [ ] **Step 3: Implement the prover**

```python
"""Prove a renamed query returns what the original returned.

Values are compared positionally and headings are ignored: the whole point of
the migration is that the headings change. Row order is normalised by sorting,
because neither query carries an ORDER BY unless its author wrote one, and
Postgres is free to differ. Values are stringified before comparison so that a
column whose type is unchanged but whose driver representation differs (a
Decimal read through a renamed alias) does not read as a difference.

Nothing here raises on SQL error. A failing query is a finding to report, in
the same spirit as run_readonly.
"""

from __future__ import annotations

from config.settings import load_settings
from database.connection import connect


def _rows(cur, sql: str) -> list[tuple[str, ...]]:
    cur.execute(sql)
    return sorted(tuple(str(v) for v in row) for row in cur.fetchall())


def verify_pairs(pairs: list[tuple[str, str]]) -> list[str]:
    settings = load_settings()
    failures: list[str] = []
    with connect(settings, readonly=True) as conn:
        for old_sql, new_sql in pairs:
            cur = conn.cursor()
            try:
                old = _rows(cur, old_sql)
            except Exception as exc:
                conn.rollback()
                failures.append(f"old query failed: {exc}\n  {old_sql}")
                continue
            try:
                new = _rows(cur, new_sql)
            except Exception as exc:
                conn.rollback()
                failures.append(f"new query failed: {exc}\n  {new_sql}")
                continue
            if len(old) != len(new):
                failures.append(
                    f"row count {len(old)} -> {len(new)}\n  {old_sql}")
                continue
            for i, (a, b) in enumerate(zip(old, new)):
                if a != b:
                    failures.append(f"row {i} {a!r} != {b!r}\n  {old_sql}")
                    break
    return failures
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/Scripts/pytest.exe tests/test_rename_equivalence.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_rename_equivalence.py tests/test_rename_equivalence.py
git commit -m "Prove a renamed query returns what the original returned"
```

---

### Task 3: Apply the migration and prove the views agree

**Files:**
- Modify: live database `arvind_retail_chatbot_test_1`

- [ ] **Step 1: Back the schema up first**

```bash
pg_dump -h localhost -U postgres -d arvind_retail_chatbot_test_1 \
  --schema-only > "$SCRATCH/pre_initiative_rename_schema.sql"
test -s "$SCRATCH/pre_initiative_rename_schema.sql" && echo OK
```

Expected: `OK`. **Do not proceed without it.**

- [ ] **Step 2: Apply inside a transaction you can still abort**

```bash
psql -h localhost -U postgres -d arvind_retail_chatbot_test_1 \
  --single-transaction -v ON_ERROR_STOP=1 \
  -f database/migrations/2026-09-16_initiative_rename.sql
```

Expected: exit 0. Any error rolls the whole thing back untouched.

- [ ] **Step 3: Prove old and new views return the same data**

```python
from scripts.verify_rename_equivalence import verify_pairs

pairs = [
    ("SELECT business_object_id, business_object_ref_id, business_unit, "
     "business_object_status, business_object_type FROM tms_business_object_flat",
     "SELECT initiative_id, initiative_ref_id, business_unit, "
     "initiative_status, initiative_type FROM tms_initiative_flat"),
    ("SELECT bo_id, business_object_status, is_business_object_delayed "
     "FROM tms_task_flat",
     "SELECT initiative_id, initiative_status, is_initiative_delayed "
     "FROM tms_task_flat"),
    ("SELECT business_object_id, initiative_type "
     "FROM tms_business_object_attributes_flat",
     "SELECT initiative_id, attribute_initiative_type "
     "FROM tms_initiative_attributes_flat"),
]
failures = verify_pairs(pairs)
assert failures == [], failures
```

Expected: no assertion error. **If this fails, run the rollback file and stop.**

- [ ] **Step 4: Confirm `wren_ro` reads the new views**

```bash
psql -h localhost -U wren_ro -d arvind_retail_chatbot_test_1 \
  -c "SELECT count(*) FROM tms_initiative_flat" \
  -c "SELECT count(*) FROM tms_initiative_attributes_flat"
```

Expected: two counts matching the pre-migration figures (307 initiatives).

- [ ] **Step 5: Confirm the read-only barrier did not widen**

```bash
psql -h localhost -U wren_ro -d arvind_retail_chatbot_test_1 \
  -c "SELECT count(*) FROM vf_business_object_audit1"
```

Expected: `ERROR: permission denied`. If this succeeds, the migration widened access — **roll back immediately**. That table holds 1.8M audit rows and `wren_ro` must never reach it.

- [ ] **Step 6: Run the existing suite against the compatibility views**

Run: `./.venv/Scripts/pytest.exe tests/ -q`
Expected: 402 passed, 9 failed (the same pre-existing 9), 33 skipped. **No new failures** — the compatibility views are doing their job.

- [ ] **Step 7: Record that the migration is applied**

```bash
git commit --allow-empty -m "Apply the Initiative view rename to arvind_retail_chatbot_test_1"
```

---

### Task 4: Regenerate `metadata/schema_description.yaml`

**Files:**
- Modify: `scripts/build_schema_description.py`
- Modify: `metadata/schema_description.yaml` (×2 repos)

**Interfaces:**
- Consumes: the new views from Task 3.
- Produces: a schema description whose table keys are `tms_initiative_flat` and `tms_initiative_attributes_flat`.

The builder reads `information_schema` and preserves descriptions across regeneration, so the rename arrives automatically and the prose written in commit `5a681e3` survives.

- [ ] **Step 1: Point the builder at the new view names**

In `scripts/build_schema_description.py`, change its table list from `tms_business_object_flat` / `tms_business_object_attributes_flat` to `tms_initiative_flat` / `tms_initiative_attributes_flat`.

- [ ] **Step 2: Regenerate**

Run: `./.venv/Scripts/python.exe scripts/build_schema_description.py`

- [ ] **Step 3: Verify the carve-outs and the collision fix**

```bash
grep -c "^        business_unit:" metadata/schema_description.yaml   # >= 1
grep -c "initiative_unit" metadata/schema_description.yaml           # MUST be 0
grep -c "attribute_initiative_type" metadata/schema_description.yaml # >= 1
```

- [ ] **Step 4: Check for drift against the database**

Run: `./.venv/Scripts/python.exe scripts/build_schema_description.py --check`
Expected: no drift reported.

- [ ] **Step 5: Mirror to Drupal and prove byte-identity**

```bash
DRUPAL=/c/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/metadata
cp metadata/schema_description.yaml "$DRUPAL/"
md5sum metadata/schema_description.yaml "$DRUPAL/schema_description.yaml"
```

Expected: identical hashes.

- [ ] **Step 6: Commit both repos**

---

### Task 5: The four hand-written metadata files

**Files:**
- Modify: `metadata/business_rules.yaml`, `column_hierarchy.yaml`, `entity_gazetteer.yaml`, `question_sql_pairs.yaml` (×2 repos)

**Interfaces:**
- Produces: rule names `active_initiative`, `short_closed_initiative`, `closed_initiative`, `count_initiatives_from_tasks`, consumed by `pipeline/followup.py` in Task 7 and `Followup.php` in Task 8.

These carry `sql_fragment`, column lists, gazetteer keys and example SQL — all identifiers.

- [ ] **Step 1: Apply the canonical sed block, plus the rule names**

Run the canonical sed block from the mapping section over all four files, then the rule-name pass:

```bash
cd /c/Users/ansh.gala/Desktop/Python/wren-poc/metadata
for f in business_rules.yaml column_hierarchy.yaml entity_gazetteer.yaml question_sql_pairs.yaml; do
  sed -i -E \
    -e 's/\bactive_business_object\b/active_initiative/g' \
    -e 's/\bshort_closed_business_object\b/short_closed_initiative/g' \
    -e 's/\bclosed_business_object\b/closed_initiative/g' \
    -e 's/\bcount_business_objects_from_tasks\b/count_initiatives_from_tasks/g' \
    "$f"
done
```

- [ ] **Step 2: Prove `business_unit` was not touched**

```bash
grep -c "initiative_unit" *.yaml   # every file MUST report 0
```

If any file reports non-zero, the sed ran as a substring pass. `git checkout` the file and fix the pattern before continuing.

- [ ] **Step 3: Keep the synonym bridge intact**

`entity_alias` in `business_rules.yaml` must still declare that Initiative, Order, BO and Business Object name one entity, now pointing at `tms_initiative_flat`. The `terminology` gloss and the `question_sql_pairs.yaml` entry "How many open tasks are in BO 123?" keep their prose and change only their SQL. A user typing "BO 123" must still work — this is checked end-to-end in Task 10.

- [ ] **Step 4: Prove every `sql_fragment` still executes**

```python
import yaml
from scripts.verify_rename_equivalence import verify_pairs

rules = yaml.safe_load(open("metadata/business_rules.yaml"))["rules"]
frags = [r["sql_fragment"] for r in rules if r.get("sql_fragment")]
probes = [f"SELECT 1 FROM tms_initiative_flat WHERE {f} LIMIT 1"
          for f in frags if "initiative_" in f and "=" in f]
failures = verify_pairs([(p, p) for p in probes])
assert failures == [], failures
```

Expected: no failures — every fragment is valid SQL against the new views.

- [ ] **Step 5: Mirror all four to Drupal and prove all five files identical**

```bash
DRUPAL=/c/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/metadata
for f in business_rules.yaml column_hierarchy.yaml entity_gazetteer.yaml question_sql_pairs.yaml schema_description.yaml; do
  cp "metadata/$f" "$DRUPAL/$f"
  a=$(md5sum "metadata/$f" | cut -d' ' -f1); b=$(md5sum "$DRUPAL/$f" | cut -d' ' -f1)
  [ "$a" = "$b" ] && echo "IDENTICAL $f" || echo "DIVERGED  $f"
done
```

Expected: five `IDENTICAL` lines.

- [ ] **Step 6: Commit both repos**

---

### Task 6: Convert the 794 benchmark ground-truth statements

**Files:**
- Modify: `benchmark/questions.yaml` (189), `lean_questions.yaml` (159), `followup_questions.yaml` (151), `expansion_questions.yaml` (141), `targeted_questions.yaml` (66), `lean_stress.yaml` (49), `active_first_questions.yaml` (39)

The largest and highest-risk task. The compatibility views from Task 1 are what make it safe: the old SQL still runs, so each suite converts and proves independently, and each is its own commit.

**Do one suite at a time. Steps 1–5 are the cycle; Step 6 repeats it.**

- [ ] **Step 1: Extract every expected SQL and pair it with its conversion**

```python
import re, yaml, pathlib

SUITE = "benchmark/lean_questions.yaml"
MAPPING = [  # longest first; whole-identifier only
    ("tms_business_object_attributes_flat", "tms_initiative_attributes_flat"),
    ("tms_business_object_flat", "tms_initiative_flat"),
    ("is_business_object_delayed", "is_initiative_delayed"),
    ("business_object_expected_completion_date", "initiative_expected_completion_date"),
    ("business_object_client_due_at", "initiative_client_due_at"),
    ("business_object_created_at", "initiative_created_at"),
    ("business_object_updated_at", "initiative_updated_at"),
    ("business_object_start_date", "initiative_start_date"),
    ("business_object_end_date", "initiative_end_date"),
    ("business_object_ref_id", "initiative_ref_id"),
    ("business_object_status", "initiative_status"),
    ("business_object_color", "initiative_color"),
    ("business_object_note", "initiative_note"),
    ("business_object_type", "initiative_type"),
    ("business_object_id", "initiative_id"),
    ("bo_id", "initiative_id"),
]


def convert(sql: str) -> str:
    for old, new in MAPPING:
        sql = re.sub(rf"\b{old}\b", new, sql)
    return sql


doc = yaml.safe_load(pathlib.Path(SUITE).read_text(encoding="utf-8"))
pairs = [(q["expected_sql"], convert(q["expected_sql"]))
         for q in doc["questions"] if q.get("expected_sql")]
print(len(pairs), "statements to prove")
```

- [ ] **Step 2: Prove every pair returns identical rows BEFORE writing anything**

```python
from scripts.verify_rename_equivalence import verify_pairs

failures = verify_pairs(pairs)
assert not failures, "\n".join(failures[:10])
```

Expected: zero failures — the proof that the conversion preserved meaning for every statement in this suite. **If any pair fails, fix the mapping. Do not edit the suite to make it pass.**

- [ ] **Step 3: Only now write the converted SQL back**

Apply the canonical sed block to the suite file, then re-parse and assert the file's statements equal the conversions already proven:

```python
after = yaml.safe_load(pathlib.Path(SUITE).read_text(encoding="utf-8"))
got = [q["expected_sql"] for q in after["questions"] if q.get("expected_sql")]
assert got == [new for _, new in pairs], "file does not match the proven set"
```

- [ ] **Step 4: Confirm `business_unit` survived**

```bash
grep -c "initiative_unit" benchmark/lean_questions.yaml   # MUST be 0
```

- [ ] **Step 5: Commit this suite alone**

```bash
git add benchmark/lean_questions.yaml
git commit -m "Convert the lean suite's ground truth to Initiative identifiers"
```

- [ ] **Step 6: Repeat Steps 1–5 for each remaining suite**

`questions.yaml`, `followup_questions.yaml`, `expansion_questions.yaml`, `targeted_questions.yaml`, `lean_stress.yaml`, `active_first_questions.yaml` — changing `SUITE` each time. Six more commits, each independently revertable.

---

### Task 7: Python pipeline and suite builders

**Files:**
- Modify: `pipeline/initiative.py` (11), `followup.py` (6), `labels.py` (5), `context.py` (2), `normalize.py` (2), `sql_semantics.py` (1), `lean_runner.py` (1)
- Modify: `scripts/build_followup_suite.py` (167), `build_expansion_suite.py` (144), `build_targeted_suite.py` (72), `build_gazetteer.py` (4)
- Test: `tests/test_initiative_terms.py`, `test_labels.py`, `test_column_order.py`, `test_context.py`, `test_followup.py`, `test_redact.py`, `test_prompt_grounding.py`

**Interfaces:**
- Consumes: rule name `active_initiative` from Task 5.
- Produces: `column_label("initiative_id") == "Initiative Id"`; `column_phrase("initiative_status") == "initiative status"`.

- [ ] **Step 1: Update the label seam's tests first**

`tests/test_initiative_terms.py` asserts `column_label("business_object_id") == "Initiative Id"`. The **input** side of every case becomes the new identifier. Its module docstring — which says the database "always will" say business object — is now false and must be rewritten to describe the seam after this migration.

```python
"""The word the UI uses for an Initiative.

Since the 2026-09-16 identifier migration the database says `initiative_*`
too, so this layer is no longer a translation. It still matters for two
reasons: `business_unit` is a different entity and must survive untouched,
and `bo_id` still arrives from the legacy TMS API, which was not migrated.
"""


@pytest.mark.parametrize("name,heading", [
    ("initiative_id", "Initiative Id"),
    ("initiative_ref_id", "Initiative Ref Id"),
    ("initiative_status", "Initiative Status"),
    ("initiative_type", "Initiative Type"),
    ("initiative_color", "Initiative Color"),
    ("initiative_note", "Initiative Note"),
    ("initiative_count", "Initiative Count"),
    ("is_initiative_delayed", "Is Initiative Delayed"),
    # Still arrives from the legacy API, which kept its vocabulary.
    ("bo_id", "Initiative Id"),
])
def test_a_reader_sees_initiative(name, heading):
    assert column_label(name) == heading


@pytest.mark.parametrize("name,heading", [
    ("business_unit", "Business Unit"),
    ("business_unit_count", "Business Unit Count"),
])
def test_business_unit_is_a_different_thing_and_keeps_its_name(name, heading):
    assert column_label(name) == heading
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/Scripts/pytest.exe tests/test_initiative_terms.py -v`
Expected: FAIL — the phrase pass does not map the new names.

- [ ] **Step 3: Update `pipeline/labels.py`**

The `business object` → `Initiative` phrase entry is now dead for the renamed columns, which title-case correctly on their own. Remove that phrase entry; **keep** `_ACRONYMS` so a `bo_id` from the legacy API still labels; **keep** the `business_unit` guard.

- [ ] **Step 4: Update the rule reference in `pipeline/followup.py:260`**

```python
if name in ("active_initiative", "open_task")
```

- [ ] **Step 5: Apply the canonical sed block to the four suite builders**

`scripts/build_followup_suite.py`, `build_expansion_suite.py`, `build_targeted_suite.py`, `build_gazetteer.py`. Then verify: `grep -c "initiative_unit" scripts/*.py` must be 0.

- [ ] **Step 6: Run the full suite**

Run: `./.venv/Scripts/pytest.exe tests/ -q`
Expected: 402 passed, 9 failed (the same pre-existing 9), 33 skipped.

- [ ] **Step 7: Commit**

---

### Task 8: The Drupal mirror and the parity harness

**Files:**
- Modify: `src/Service/Initiative.php` (9), `Followup.php` (5), `ColumnLabels.php` (5), `Metadata.php` (2), `Normalizer.php` (1), `ConversationContext.php` (1)
- Modify: `tests/parity/check.php` — the recorded prompt md5

**Interfaces:**
- Consumes: the metadata from Tasks 4–5 and the Python behaviour from Task 7, which this mirrors exactly.

- [ ] **Step 1: Mirror each Python change into the six services**

`ColumnLabels.php` mirrors `labels.py` — remove the dead phrase entry, keep the `bo` acronym and the `business_unit` guard. `Followup.php` mirrors the `active_initiative` rule name. The rest are identifier substitutions.

- [ ] **Step 2: Regenerate the parity fixtures**

Run: `./.venv/Scripts/python.exe tests/parity/generate_expected.py "$SCRATCH/parity"`

- [ ] **Step 3: Run the harness**

Run: `php tests/parity/check.php "$SCRATCH/parity" --verbose`
Expected: every layer at its bar. The prompt byte-length and md5 **will** have changed — that is the point, not a failure.

- [ ] **Step 4: Record the new md5 in `check.php` and re-run**

Expected: exit 0.

- [ ] **Step 5: Clear Drupal caches**

Visit `/admin/config/development/performance` and clear all caches. **Drush is broken in this environment** — do not attempt `drush cr`.

- [ ] **Step 6: Commit the Drupal repo**

---

### Task 9: The chat grid's one translation point, and the re-baseline record

**Files:**
- Modify: `src/components/SqlChatbot/ChatResultGrid.jsx:79-88`
- Test: `src/components/SqlChatbot/chatGridLayout.test.js`, `SqlChatbotPage.test.jsx`
- Create: `results/2026-09-16-initiative-rename-rebaseline.md`

- [ ] **Step 1: Translate at the legacy boundary**

The backend now sends `initiative_id`. `BODetails` still reads `bo_id`, and `/track-bo-details/:bo_id` is a URL contract in `Routs.js` shared with the un-migrated TMS app. Translate, do not propagate:

```jsx
const openInitiative = useCallback(
  // The backend speaks `initiative_id` since the 2026-09-16 rename. The
  // legacy BODetails dialog and the /track-bo-details/:bo_id route still
  // speak `bo_id`, and both are shared with the TMS app, which was not
  // migrated. This is the seam between the two vocabularies.
  (initiativeId) => setModalState({
    show: true,
    modalType: "BODetails",
    data: { bo_id: initiativeId },
  }),
  [setModalState],
);
```

- [ ] **Step 2: Update the two chatbot tests to send the new column name**

- [ ] **Step 3: Build**

Run: `npm run dev`
Expected: webpack build succeeds. **Never `react-scripts build`** — `build/` is the live Apache web root, and that command exits 1 on pre-existing eslint debt across ~129 unrelated files.

- [ ] **Step 4: Re-run both suites and record the new baseline**

```bash
./.venv/Scripts/python.exe scripts/run_lean_suite.py
./.venv/Scripts/python.exe scripts/run_benchmark.py
```

Write `results/2026-09-16-initiative-rename-rebaseline.md` stating plainly that the identifier migration changed the system prompt, so figures recorded before 2026-09-16 do not compare with figures after it. Record the old and new numbers **side by side** rather than replacing the old ones.

- [ ] **Step 5: Commit the frontend repo and the results record**

---

### Task 10: Drop the compatibility views

**Files:**
- Create: `database/migrations/2026-09-16_drop_compat_views.sql`

Only after Tasks 4–9 are all green. Until then the compatibility views are load-bearing.

- [ ] **Step 1: Prove nothing references the old names**

```bash
cd /c/Users/ansh.gala/Desktop/Python/wren-poc
grep -rn "tms_business_object_flat" metadata/ benchmark/ pipeline/ scripts/ tests/ | grep -v "\.pyc"
grep -rn "\bbo_id\b" metadata/ benchmark/ scripts/ | grep -v "\.pyc"
```

Expected: no hits from either, except prose that deliberately names the old vocabulary — the `entity_alias` synonym bridge, this plan, and the roadmap spec.

**`pipeline/` and `tests/` are deliberately excluded from the `bo_id` grep.** Task 7 keeps `_ACRONYMS` expanding `bo` in `pipeline/labels.py` and keeps the `("bo_id", "Initiative Id")` case in `tests/test_initiative_terms.py`, because the legacy TMS API — which this migration does not touch — still sends that key. Those are required, not leftovers. Verify they are still present rather than absent:

```bash
grep -c "bo_id" tests/test_initiative_terms.py   # MUST be >= 1
```

- [ ] **Step 2: Drop them**

```sql
DROP VIEW IF EXISTS tms_business_object_flat;
DROP VIEW IF EXISTS tms_business_object_attributes_flat;
```

- [ ] **Step 3: Run everything one last time**

```bash
./.venv/Scripts/pytest.exe tests/ -q
php /c/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/tests/parity/check.php "$SCRATCH/parity"
```

Expected: 402 passed / 9 pre-existing failures; parity exit 0.

- [ ] **Step 4: Verify "BO 123" still answers correctly**

Ask the running chatbot: *"How many open tasks are in BO 123?"* The synonym bridge in `entity_alias` must still resolve it against `tms_initiative_flat`. This is the user-facing regression the migration most risks, and it is checked last because it exercises every layer at once.

- [ ] **Step 5: Commit**

---

## Rollback

At any point before Task 10:

```bash
psql -h localhost -U postgres -d arvind_retail_chatbot_test_1 \
  --single-transaction -v ON_ERROR_STOP=1 \
  -f database/migrations/2026-09-16_initiative_rename_rollback.sql
git revert <range>
```

After Task 10 the compatibility views are gone, and rollback additionally requires re-running the forward migration's compatibility section. The schema dump from Task 3 Step 1 is the last resort.
