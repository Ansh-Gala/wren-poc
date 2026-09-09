# Active-First Default and Column Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The chatbot answers about active records when the user names no status, respects any status the user does name, and ships presentation metadata saying which columns matter — with model compliance measured rather than asserted.

**Architecture:** Active-first is a business rule in `metadata/business_rules.yaml`, the one file that reaches both provider modes (inlined into the lean system prompt, served through `mcp__wren__get_instructions` in Wren mode) and both implementations. The model therefore writes the predicate itself and there is still exactly one thing that writes SQL. Column priority is presentation-only metadata in a new `metadata/column_hierarchy.yaml`, attached to the response beside `column_labels` and expressed as **column positions**, so it can never alter a query nor the byte-identical system prompt.

**Tech Stack:** Python 3.12, PyYAML, sqlglot, pytest. PHP 8 / Drupal 10 for the mirrored `vf_sql_chatbot` module.

## Global Constraints

- `metadata/*.yaml` exists **twice** and is currently byte-identical: `wren-poc/metadata/` and `dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/metadata/`. Every change lands in both, or `tests/parity/check.php` fails its byte-for-byte system-prompt comparison (recorded: 24,316 bytes, md5 `4c5c426e…`).
- A business rule may use only the keys `name`, `definition`, `sql_fragment`, `scope`. Both renderers — `claude/prompts._render_rules` and `PromptBuilder::renderRules` — emit exactly those and silently drop anything else, so any other key never reaches the model.
- `default_to_active` carries **no** `sql_fragment`. `followup._rule_predicates()` turns every single-equality fragment into an "Only the … ones" button, and a default already in force must not be offered as a next move.
- Two status columns exist, and only two: `tms_business_object_flat.business_object_status` (`Active`, `Closed`, `Short Closed`) and `tms_task_flat.task_status` (`open`, `closed`). `tms_user_flat` has **no** status column. `task_display_status` is presentation-only and must never be filtered or grouped on.
- No `cancelled` and no `completed` status exists in this database. Questions using those words keep their existing `zero_or_clarify` behaviour; do not invent a status to satisfy them.
- Active-first scope, as decided: **listings and counts of records**. Carve-outs, stated in the rule's own `scope` text: an explicit status, all/history requests, distributions across status, counts of distinct column values, and missing/malformed-data questions.
- **Tell the human partner before running any suite or test batch.** They live-monitor those runs. Informing them is required; waiting for a reply is not.
- Column presentation is expressed as **positions into `columns`**, never as names. A result may project one name twice (`COUNT(*)` twice; a join projecting `business_object_ref_id` from both sides), which is why `ChatResultGrid` keys its rows `c0..cN` by index.

---

## File Structure

**Created**
- `metadata/column_hierarchy.yaml` — preferred column order and hidden columns, per table. Presentation only.
- `pipeline/column_order.py` — loads that file and resolves it against a result's actual columns, returning positions.
- `tests/test_active_first.py` — that the rule reaches the model intact and leaks into nothing else.
- `tests/test_column_order.py` — the position arithmetic.
- `tests/test_suggestions.py` — the dedicated follow-up suggestion suite (spec §8).
- `benchmark/active_first_questions.yaml` — the measured compliance gate.
- `<module>/metadata/column_hierarchy.yaml` — the mirrored copy.
- `<module>/src/Service/ColumnOrder.php` — the mirrored resolver.

**Modified**
- `metadata/business_rules.yaml` — the `default_to_active` rule.
- `benchmark/lean_questions.yaml`, `benchmark/questions.yaml` — re-baselined expected SQL.
- `pipeline/labels.py` — `with_presentation`, beside the existing `with_column_labels`.
- `pipeline/followup.py` — relabel status-filter removal under the default; gate suggestions on the returned rows.
- `pipeline/lean_runner.py` — pass the executed result through to the follow-up layer.
- `scripts/serve_api.py` — attach presentation to the response.
- `<module>/metadata/business_rules.yaml`, `<module>/src/Service/Followup.php`, `<module>/src/Service/TurnRunner.php`.

`<module>` means `c:/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot`.

---

### Task 1: The active-first rule

**Files:**
- Modify: `metadata/business_rules.yaml` (append after the `count_business_objects_from_tasks` rule, before `entity_alias`)
- Test: `tests/test_active_first.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a rule named `default_to_active`, with `definition` and `scope` and deliberately no `sql_fragment`. Task 2 mirrors this text verbatim. Task 3 measures whether the model obeys it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_active_first.py`:

```python
"""The active-first default: what the model is told when no status is named.

Active-first is a business rule rather than a SQL rewrite, so what can be
asserted here is that the rule reaches the model intact and leaks into none of
the layers that must stay unaware of it. Whether the model then complies is an
accuracy question, and accuracy is measured by
benchmark/active_first_questions.yaml -- not asserted in a unit test.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _rule(name: str) -> dict:
    doc = yaml.safe_load(
        (ROOT / "metadata" / "business_rules.yaml").read_text(encoding="utf-8"))
    found = [r for r in doc["rules"] if r["name"] == name]
    assert len(found) == 1, f"expected exactly one {name!r} rule, found {len(found)}"
    return found[0]


def test_the_default_names_both_status_columns_that_exist():
    """Both, and only both.

    tms_user_flat has no status column, so a rule naming one would be telling
    the model to filter on something that is not there.
    """
    rule = _rule("default_to_active")
    text = rule["definition"] + rule["scope"]
    assert "business_object_status = 'Active'" in text
    assert "task_status = 'open'" in text
    assert "user_status" not in text


def test_the_default_carves_out_the_questions_it_must_not_touch():
    """The carve-outs are the rule. Without them it is simply wrong.

    Each phrase below stands for a question class that must still see every
    row: a stated status, an explicit request for everything, a distribution
    across statuses, a count of distinct values, and a question about missing
    data.
    """
    scope = " ".join(_rule("default_to_active")["scope"].split())
    for carve_out in ("states a status", "everything", "distributed across",
                      "distinct", "missing"):
        assert carve_out in scope, f"scope does not exclude {carve_out!r}"


def test_the_default_is_a_policy_not_a_togglable_filter():
    """It must not become a suggestion button.

    followup._rule_predicates turns every single-equality rule into an "Only
    the active ones" action. This default is already in force, so offering it
    would be offering a no-op -- and the rule carries no sql_fragment
    precisely so it cannot be read that way.
    """
    from pipeline.followup import _rule_predicates

    assert "sql_fragment" not in _rule("default_to_active")
    assert "default_to_active" not in [name for name, *_ in _rule_predicates()]


def test_the_default_reaches_the_model_in_the_built_prompt():
    """Rendered, not merely present on disk.

    _render_rules emits name, definition, sql_fragment and scope and nothing
    else, so a rule whose content lived in any other key would pass the tests
    above and still never be read by the model.
    """
    from claude.prompts import build_lean_system_prompt

    prompt = build_lean_system_prompt()
    assert "default_to_active" in prompt
    assert "business_object_status = 'Active'" in prompt
    assert "task_status = 'open'" in prompt
```

- [ ] **Step 2: Run the test to verify it fails**

Tell the human partner you are about to run tests, then:

Run: `python -m pytest tests/test_active_first.py -v`
Expected: FAIL — all four, with `AssertionError: expected exactly one 'default_to_active' rule, found 0`.

- [ ] **Step 3: Add the rule**

In `metadata/business_rules.yaml`, insert between the `count_business_objects_from_tasks` rule and the `entity_alias` rule:

```yaml
  - name: default_to_active
    definition: >-
      When a question asks for records, or for a count of records, and names no
      status of its own, answer about the active ones only. An Initiative
      (Business Object) is active when business_object_status = 'Active'; a task
      is active when task_status = 'open'. Add that predicate even though the
      question did not ask for it: a user asking "show me my tasks" means the
      ones still to do, not every task they have ever been assigned.
    scope: >-
      This default applies only to questions about the records themselves --
      "show the AR_YD_Suiting items", "how many tasks are in it". It does not
      apply, and the query must see every row, in any of these cases. When the
      question states a status, that status decides and this default is not
      added on top of it: "closed initiatives", "short closed items", "my
      closed tasks". When the question asks for everything or for history:
      "all initiatives", "every task", "including the closed ones". When the
      question asks how records are distributed across statuses -- "how many by
      status", "the status breakdown" -- because adding the filter would empty
      the answer. When the question counts distinct values of a column rather
      than counting records: "how many distinct business object types are
      there". And when the question is about missing or malformed data, such as
      "how many business objects have no workflow name recorded", because an
      answer that saw only the active rows would not be an answer about the
      data. When the conversation already carries a status filter, that filter
      decides. Never use task_display_status for any of this; task_status is
      the column to filter on.
```

There is no `sql_fragment` key, and that is deliberate — see the third test above.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_active_first.py -v`
Expected: PASS, 4 passed.

- [ ] **Step 5: Confirm nothing else moved**

Run: `python -m pytest tests/ -q`
Expected: the same pass/fail set as before this task, except `tests/test_metadata.py` — if it asserts a rule count, update that number and say so in the commit message.

- [ ] **Step 6: Commit**

```bash
git add metadata/business_rules.yaml tests/test_active_first.py
git commit -m "Default to the active records when the question names no status"
```

---

### Task 2: Mirror the rule into the Drupal module

**Files:**
- Modify: `<module>/metadata/business_rules.yaml`, `<module>/tests/parity/README.md`

**Interfaces:**
- Consumes: the exact rule text from Task 1.
- Produces: byte-identical metadata across both implementations, so the parity harness's prompt comparison still holds.

A rules-only change needs **no PHP code at all**: `PromptBuilder::renderRules` already emits `name`, `definition`, `sql_fragment` and `scope`, which is exactly what `_render_rules` emits. This task is a file copy plus the measurement that proves it.

- [ ] **Step 1: Copy the file wholesale**

```bash
cp "c:/Users/ansh.gala/Desktop/Python/wren-poc/metadata/business_rules.yaml" \
   "c:/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/metadata/business_rules.yaml"
```

- [ ] **Step 2: Prove the two are identical**

```bash
diff "c:/Users/ansh.gala/Desktop/Python/wren-poc/metadata/business_rules.yaml" \
     "c:/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/metadata/business_rules.yaml" \
  && echo IDENTICAL
```

Expected: `IDENTICAL`, no diff output.

- [ ] **Step 3: Regenerate the parity fixtures and re-check**

Tell the human partner you are about to run the parity harness. Then, from the Python project root with its virtualenv active:

```bash
python "c:/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/tests/parity/generate_expected.py" /tmp/parity
php "c:/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/tests/parity/check.php" /tmp/parity
```

Expected: exit 0. The prompt check still reports identical, at a **new** byte count and md5 — the prompt grew by the rule.

- [ ] **Step 4: Record the new prompt figure**

In `<module>/tests/parity/README.md`, update the Prompt row's byte count and md5 to what `check.php` just printed, and add one line under "What was measured" naming the date and that the change was the `default_to_active` rule. A stale recorded md5 is worse than none: it invites the next reader to think a real divergence is a typo.

- [ ] **Step 5: Commit (in the backend repo)**

```bash
cd "c:/xampp/htdocs/dev-arvind-retail-chatbot"
git add web/modules/custom/vf_sql_chatbot/metadata/business_rules.yaml \
        web/modules/custom/vf_sql_chatbot/tests/parity/README.md
git commit -m "Carry the active-first default into the module's metadata"
```

---

### Task 3: The measured compliance gate

**Files:**
- Create: `benchmark/active_first_questions.yaml`

**Interfaces:**
- Consumes: the rule from Task 1; the suite schema in `pipeline/lean_suite.SuiteTurn` and the loader in `benchmark/suite.load_suite`.
- Produces: a suite runnable as `python scripts/run_lean_suite.py --suite benchmark/active_first_questions.yaml --out results/active_first`.

Anchors, all taken from the lean suite's verified header: `AR_NPD_Shirting` holds 10 initiatives, 5 Active and 5 Closed — a clean split, so a missing default shows as 10 rows and a working one as 5. `AR_YD_Suiting` holds 22 initiatives (19 Active) and 208 tasks, of which 32 are open.

- [ ] **Step 1: Write the suite**

Create `benchmark/active_first_questions.yaml`:

```yaml
# Does the active-first default fire when it should, and stay out of the way
# when it should not?
#
# Paired by construction. Every implicit question has an explicit twin, so a
# model that ignores the default and a model that applies it unconditionally
# both fail -- one on the implicit half, the other on the explicit half. A
# suite of implicit questions alone would score full marks for a rule that
# simply filtered everything to Active always.
#
# Anchors, from the lean suite's verified header:
#   AR_NPD_Shirting   10 initiatives, 5 Active / 5 Closed -- a clean split, so
#                     a default that failed to fire reads as 10, not 5
#   AR_YD_Suiting     22 initiatives (19 Active), 208 tasks (32 open)

version: 1

questions:

# ------------------------------------------------- the default should fire ==

- id: AF01
  category: Implicit Status
  question: Show the AR_NPD_Shirting items
  note: No status named. Expect 5 rows, not 10.
  expected_sql: |
    SELECT business_object_id, business_object_ref_id, business_object_status
    FROM tms_business_object_flat
    WHERE business_object_type = 'AR_NPD_Shirting'
      AND business_object_status = 'Active'

- id: AF02
  category: Implicit Count
  question: How many AR_NPD_Shirting items are there?
  note: A count of records, so the default applies. Expect 5.
  expected_sql: |
    SELECT COUNT(*) FROM tms_business_object_flat
    WHERE business_object_type = 'AR_NPD_Shirting'
      AND business_object_status = 'Active'

- id: AF03
  category: Implicit Task Status
  question: Show the tasks in AR_YD_Suiting
  note: Tasks are active when open. Expect 32, not 208.
  expected_sql: |
    SELECT task_id, task_display_name, task_status
    FROM tms_task_flat
    WHERE business_object_type = 'AR_YD_Suiting'
      AND task_status = 'open'

# ------------------------------------- an explicit status must always win ==

- id: AF04
  category: Explicit Status
  question: Show the closed AR_NPD_Shirting items
  note: Stated status. Expect 5 closed, and no Active predicate anywhere.
  expected_sql: |
    SELECT business_object_id, business_object_ref_id, business_object_status
    FROM tms_business_object_flat
    WHERE business_object_type = 'AR_NPD_Shirting'
      AND business_object_status = 'Closed'

- id: AF05
  category: Explicit Status
  question: Show the short closed AR_NPD_YD_SHIRTING items
  note: The third status value. Named, so it decides.
  expected_sql: |
    SELECT business_object_id, business_object_ref_id, business_object_status
    FROM tms_business_object_flat
    WHERE business_object_type = 'AR_NPD_YD_SHIRTING'
      AND business_object_status = 'Short Closed'

- id: AF06
  category: Explicit Task Status
  question: Show the closed tasks in AR_YD_Suiting
  expected_sql: |
    SELECT task_id, task_display_name, task_status
    FROM tms_task_flat
    WHERE business_object_type = 'AR_YD_Suiting'
      AND task_status = 'closed'

# --------------------------------------------- the carve-outs, one by one ==

- id: AF07
  category: Carve-out - Everything
  question: Show all AR_NPD_Shirting items, active and closed
  note: Asks for everything outright. Expect 10.
  expected_sql: |
    SELECT business_object_id, business_object_ref_id, business_object_status
    FROM tms_business_object_flat
    WHERE business_object_type = 'AR_NPD_Shirting'

- id: AF08
  category: Carve-out - Status Breakdown
  question: How many AR_NPD_Shirting items are there by status?
  note: A distribution across statuses. The default would empty it.
  expected_sql: |
    SELECT business_object_status, COUNT(*)
    FROM tms_business_object_flat
    WHERE business_object_type = 'AR_NPD_Shirting'
    GROUP BY business_object_status

- id: AF09
  category: Carve-out - Distinct Values
  question: How many distinct business object types are there?
  note: Counts values of a column, not records. No status predicate.
  expected_sql: |
    SELECT COUNT(DISTINCT business_object_type) FROM tms_business_object_flat

- id: AF10
  category: Carve-out - Missing Data
  question: How many business objects have no workflow name recorded?
  note: A data-quality question. Restricting to active would not answer it.
  expected_sql: |
    SELECT COUNT(*) FROM tms_business_object_flat
    WHERE workflow_name IS NULL

- id: AF11
  category: Carve-out - No Such Status
  question: Show me the cancelled AR_NPD_Shirting items
  note: >-
    There is no 'cancelled' status in this database -- only Active, Closed and
    Short Closed. The default must not quietly rescue the question by
    substituting Active; returning nothing or saying so are both right.
  expect_behavior: zero_or_clarify

# ------------------------------------------------- across a conversation ==

- id: AFC01
  category: Conversation - Override The Default
  turns:
    - id: AFC01.1
      question: Show the AR_NPD_Shirting items
      note: Default fires. 5 rows.
      expect_decision: new_block
      expected_sql: |
        SELECT business_object_id, business_object_ref_id, business_object_status
        FROM tms_business_object_flat
        WHERE business_object_type = 'AR_NPD_Shirting'
          AND business_object_status = 'Active'
    - id: AFC01.2
      question: what about the closed ones?
      note: >-
        Elliptical and explicit at once. The status must be replaced, not added
        to -- Active AND Closed is empty, and an empty answer here would look
        like a data problem rather than a bug.
      expect_decision: follow_up
      expected_sql: |
        SELECT business_object_id, business_object_ref_id, business_object_status
        FROM tms_business_object_flat
        WHERE business_object_type = 'AR_NPD_Shirting'
          AND business_object_status = 'Closed'
    - id: AFC01.3
      question: show me all of them, whatever the status
      note: An explicit escape from the default. Expect 10.
      expect_decision: follow_up
      expected_sql: |
        SELECT business_object_id, business_object_ref_id, business_object_status
        FROM tms_business_object_flat
        WHERE business_object_type = 'AR_NPD_Shirting'
```

- [ ] **Step 2: Verify the suite loads and its ids are unique**

Run:

```bash
python -c "from benchmark.suite import load_suite, all_turns; from pathlib import Path; c=load_suite(Path('benchmark/active_first_questions.yaml')); print(len(c), 'conversations,', len(all_turns(c)), 'turns')"
```

Expected: `12 conversations, 14 turns`. `load_suite` raises on a duplicate id or a bad `expect_behavior`, so a clean print is the check.

- [ ] **Step 3: Commit**

```bash
git add benchmark/active_first_questions.yaml
git commit -m "Measure the active-first default against its explicit twins"
```

---

### Task 4: Re-baseline the existing suites

**Files:**
- Modify: `benchmark/lean_questions.yaml`, `benchmark/questions.yaml`, `README.md`

**Interfaces:**
- Consumes: the carve-out rules from Task 1's `scope`.
- Produces: suites whose ground truth matches the behaviour that now ships. Every changed turn carries a `note` saying why.

31 of 50 lean turns and 30 of 86 full-suite turns currently expect **no** status predicate, and the lean suite's own header calls a leaked `Active` filter a defect. Those figures measure a product that is being changed, so the ground truth has to change with it. Do not guess which turns: classify them mechanically, then decide each one against the carve-outs.

- [ ] **Step 1: List the candidates**

```bash
python - <<'PY'
import re, yaml
for path in ("benchmark/lean_questions.yaml", "benchmark/questions.yaml"):
    doc = yaml.safe_load(open(path, encoding="utf-8"))
    flat = []
    for q in doc.get("questions") or []:
        flat.extend(q["turns"] if "turns" in q else [q])
    print(f"\n=== {path} ===")
    for q in flat:
        s = " ".join((q.get("expected_sql") or "").split())
        if not s:
            continue
        touches = "tms_business_object_flat" in s or "tms_task_flat" in s
        stated = re.search(r"(business_object_status|task_status)\s*(=|IN|<>|!=)", s, re.I)
        grouped = re.search(r"GROUP BY[^;]*?(business_object_status|task_status)", s, re.I)
        if touches and not stated and not grouped:
            print(f"  {q['id']}: {q['question']}")
PY
```

Expected: 31 ids from the lean suite, 30 from the full suite.

- [ ] **Step 2: Classify every id in that list**

For each, choose exactly one and write the reason into the turn's `note`:

- **Re-baseline** — a listing or a count of records. Add the predicate to `expected_sql`: `AND business_object_status = 'Active'` for the initiative table, `AND task_status = 'open'` for the task table. Known members: `S01 Show the AR_YD_Suiting items`, `S02 How many AR_YD_Suiting items are there?`, `S13 Show the tasks in AR_YD_Suiting`, `S15 How many tasks are in AR_YD_Suiting?`, `T01`, `T02`, `T03`, `T05`, `T06`.
- **Carve-out, leave alone** — matches one of the rule's exclusions; add a `note` naming which. Known members: `S12 How many distinct business object types are there?` (distinct values), `S21 How many business objects have no workflow name recorded?` (missing data), `S08 How many AR_YD_Suiting items are there by priority colour?` (a distribution — across colour rather than status, but the default would still change its denominator, so treat it as a carve-out and say so in the note).

Do not batch-edit with `sed`. Each turn is a judgement and the `note` is the record of it.

- [ ] **Step 3: Also check the conversations that lose their point**

`C01` in `lean_questions.yaml` is a three-turn thread whose second turn is "Only the active ones". Under the default, turn 1 already returns only active rows, so turn 2 is a no-op and the thread no longer discriminates anything. Either re-point it at a status the default does not add — change turn 2 to "only the closed ones" and adjust turns 2 and 3 accordingly — or leave it and add a `note` saying it now tests that a redundant refinement is harmless. Pick one and say which in the commit message.

- [ ] **Step 4: Fix the header comment that now contradicts the rule**

`benchmark/lean_questions.yaml` currently reads, in its header block:

```
#   AR_NPD_Shirting      10 BOs (5 Active, 5 Closed)  -- clean split, so a
#                        leaked "Active" filter is visible as 5 instead of 10
```

Replace with:

```
#   AR_NPD_Shirting      10 BOs (5 Active, 5 Closed)  -- clean split, so the
#                        active-first default is visible as 5 instead of 10,
#                        and a turn that should have escaped it as 10
```

Leaving the old wording would tell the next reader that the behaviour this suite now asserts is a bug.

- [ ] **Step 5: Verify both suites still load, with the same turn counts**

```bash
python -c "from benchmark.suite import load_suite, all_turns; from pathlib import Path; [print(p, len(all_turns(load_suite(Path(p))))) for p in ('benchmark/lean_questions.yaml','benchmark/questions.yaml')]"
```

Expected: `benchmark/lean_questions.yaml 50` and `benchmark/questions.yaml 86`. The counts must not change — this task edits SQL, never the turn set.

- [ ] **Step 6: Record that old figures no longer compare**

Append to `README.md`, under the section carrying the accuracy figures, one short paragraph: that the active-first default changed the definition of a correct answer for N lean turns and M full-suite turns on 2026-09-09, that every figure recorded in `results/` predates it, and that pre- and post-change figures are not comparable. Use the real N and M from Step 2.

- [ ] **Step 7: Commit**

```bash
git add benchmark/lean_questions.yaml benchmark/questions.yaml README.md
git commit -m "Re-baseline the suites: no status named now means the active ones"
```

---

### Task 5: Run the gate and record what the model actually does

**Files:**
- Create: `results/active_first/`, `results/lean_active_first/` (written by the runner)

**Interfaces:**
- Consumes: Tasks 1, 3, 4.
- Produces: a recorded compliance figure. This is the step that decides whether the rule alone is enough, or whether the deterministic-rewrite backstop has to be reconsidered.

This task needs a live PostgreSQL holding the `tms_*` views and the Claude Code CLI. It is the only task here that costs model calls.

- [ ] **Step 1: Tell the human partner, then run the new gate**

State plainly that you are starting a suite run, which suite, and roughly how many turns. Do not wait for a reply.

Run: `python scripts/run_lean_suite.py --suite benchmark/active_first_questions.yaml --out results/active_first`
Expected: 14 turns execute; a summary table lands in `results/active_first/latest.md`.

- [ ] **Step 2: Read the result against the two halves separately**

The suite fails in two distinguishable ways and they need different fixes:

- the **implicit** turns (AF01, AF02, AF03, AFC01.1) failing means the model is not applying the default — the `definition` is not carrying.
- the **explicit and carve-out** turns (AF04–AF11, AFC01.2, AFC01.3) failing means it is over-applying — the `scope` is not carrying.

Record both counts in the ledger. If either half is below 90%, stop and report to the human partner rather than tuning the wording repeatedly: the decision on record is "rule plus measured gate", and a rule that cannot reach 90% on either half is exactly the evidence that the fallback needs discussing.

- [ ] **Step 3: Re-run the re-baselined lean suite**

Tell the human partner first. Then:

Run: `python scripts/run_lean_suite.py --out results/lean_active_first`
Expected: 50 turns. Compare against the last recorded pre-change run, understanding that per Task 4 they are not strictly comparable — what matters is that it has not collapsed. A drop of more than a few points means the rule is firing on turns Task 4 classified as carve-outs, and those turns name the wording that needs narrowing.

- [ ] **Step 4: Commit the results**

```bash
git add results/active_first results/lean_active_first
git commit -m "Record what the model does with the active-first default"
```

---

### Task 6: The column hierarchy, as presentation metadata

**Files:**
- Create: `metadata/column_hierarchy.yaml`, `pipeline/column_order.py`, `tests/test_column_order.py`
- Modify: `pipeline/labels.py`, `scripts/serve_api.py`

**Interfaces:**
- Consumes: `state.active_tables`, already in the response as `state["tables"]`.
- Produces: `pipeline.column_order.presentation(columns: list[str] | None, tables: list[str] | None) -> dict` returning `{"order": list[int], "hidden": list[int]}`, and `pipeline.labels.with_presentation(result, tables)`. The response's `result` gains `column_order: list[int]` and `hidden_columns: list[int]`. Task 7 mirrors both; the grid work in Plan 3 consumes them.

Positions, not names, throughout — a result may project one name twice, and the grid keys rows by index for that reason.

- [ ] **Step 1: Write the failing test**

Create `tests/test_column_order.py`:

```python
"""Which columns matter, for a result whose columns the user did not choose.

Everything here is positional. A result may project the same name twice --
COUNT(*) twice, or a join taking business_object_ref_id from both sides -- and
the frontend keys its rows by position for exactly that reason, so a
name-based answer would have to be re-resolved by the caller and would be
wrong in the one case that matters.
"""

from __future__ import annotations

from pipeline.column_order import presentation


def test_named_columns_lead_in_the_order_the_file_gives_them():
    columns = ["business_unit", "business_object_status", "business_object_id"]
    out = presentation(columns, ["tms_business_object_flat"])
    # File order, not result order: id, then status, then unit.
    assert [columns[i] for i in out["order"]] == [
        "business_object_id", "business_object_status", "business_unit"]


def test_unlisted_columns_keep_their_own_order_after_the_named_ones():
    """A generated alias has never appeared in any registry and still has to
    be shown somewhere predictable."""
    columns = ["avg_delay_days", "business_object_id", "some_new_column"]
    out = presentation(columns, ["tms_business_object_flat"])
    assert [columns[i] for i in out["order"]] == [
        "business_object_id", "avg_delay_days", "some_new_column"]


def test_hidden_columns_are_positions_and_stay_inside_the_order():
    """Hidden is a display hint, not a deletion.

    The column is still in the result, still in `order`, and still exported --
    the frontend starts it collapsed. Dropping it from `order` would make the
    two lists disagree about how many columns there are.
    """
    columns = ["business_object_id", "business_object_note"]
    out = presentation(columns, ["tms_business_object_flat"])
    assert out["hidden"] == [1]
    assert sorted(out["order"]) == [0, 1]


def test_a_duplicated_column_name_gets_both_of_its_positions():
    columns = ["business_object_id", "business_object_id"]
    out = presentation(columns, ["tms_business_object_flat"])
    assert sorted(out["order"]) == [0, 1], "a repeated name must not collapse"


def test_an_unknown_table_leaves_the_result_untouched():
    columns = ["a", "b", "c"]
    out = presentation(columns, ["some_view_nobody_configured"])
    assert out["order"] == [0, 1, 2]
    assert out["hidden"] == []


def test_no_columns_is_not_an_error():
    """A clarification turn has no result and no columns."""
    assert presentation(None, None) == {"order": [], "hidden": []}
    assert presentation([], ["tms_task_flat"]) == {"order": [], "hidden": []}


def test_the_order_is_always_a_permutation_of_the_positions():
    """The invariant the frontend depends on: every column appears once."""
    columns = ["business_object_id", "workflow_id", "avg_delay_days",
               "business_object_status", "business_object_status"]
    out = presentation(columns, ["tms_business_object_flat"])
    assert sorted(out["order"]) == list(range(len(columns)))
    assert all(0 <= i < len(columns) for i in out["hidden"])


def test_labels_attaches_presentation_without_disturbing_anything():
    from pipeline.labels import with_presentation

    result = {"columns": ["business_object_note", "business_object_id"],
              "rows": [["n", 1]], "row_count": 1, "truncated": False}
    out = with_presentation(result, ["tms_business_object_flat"])

    assert out["column_order"] == [1, 0]
    assert out["hidden_columns"] == [0]
    assert out["columns"] == result["columns"], "columns must be untouched"
    assert out["rows"] == result["rows"], "rows must be untouched"


def test_a_clarification_passes_through_unchanged():
    from pipeline.labels import with_presentation

    assert with_presentation(None, ["tms_task_flat"]) is None
    assert with_presentation("not a dict", None) == "not a dict"
```

- [ ] **Step 2: Run it to verify it fails**

Tell the human partner you are running tests, then:

Run: `python -m pytest tests/test_column_order.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.column_order'`.

- [ ] **Step 3: Write the configuration file**

Create `metadata/column_hierarchy.yaml`:

```yaml
# Which columns matter, and which the UI may start collapsed.
#
# Presentation only. Nothing here reaches the model and nothing here changes a
# query: a generic question can still project all 33 columns of
# tms_business_object_flat, and this file decides the order they are shown in
# and which of them start hidden. Keeping it out of the prompt is deliberate --
# the built system prompt is compared byte for byte against the PHP port, and
# accuracy figures are only comparable while the prompt is unchanged.
#
# `priority` is the order the listed columns are shown in, most useful first.
# A column absent from the list keeps its own relative order and follows
# everything named. `hidden` columns are still in the result and still
# exported; they simply do not open by default.

version: 1

tables:
  tms_business_object_flat:
    priority:
      - business_object_id
      - business_object_ref_id
      - business_object_status
      - business_object_type
      - business_unit
      - business_object_color
      - business_object_client_due_at
      - days_to_due_date
      - open_task_count
      - total_task_count
      - workflow_name
      - current_active_milestone
    hidden:
      - business_object_note
      - workflow_id
      - workflow_code
      - short_closed_by
      - short_closed_on
      - open_tasks_list
      - common_buffer
      - buff_penetration_prcnt
      - buff_penetration_days

  tms_task_flat:
    priority:
      - task_id
      - task_code
      - task_display_name
      - task_status
      - assigned_user_name
      - task_department
      - task_sla_status
      - task_elapsed_days
      - next_followup_at
      - business_object_ref_id
      - business_object_type
    hidden:
      - task_machine_code
      - display_flag
      - is_open_task
      - is_closed_task
      - is_not_started_task
      - is_delayed_open_task
      - is_delayed_closed_task
      - is_business_object_delayed
      - task_reopen_at
      - task_display_status

  tms_business_object_attributes_flat:
    priority:
      - business_object_id
      - business_object_ref_id
    hidden: []

  tms_user_flat:
    priority:
      - user_id
      - user_name
      - role_count
      - department_count
    hidden: []
```

- [ ] **Step 4: Write the resolver**

Create `pipeline/column_order.py`:

```python
"""Display order and hidden columns, resolved against a result's own columns.

Presentation only, and positional. The order comes from
metadata/column_hierarchy.yaml, which lists columns by name; a result carries
columns by position and may carry one name twice, so the answer is a list of
positions rather than a list of names. Anything else would push that
resolution onto the caller, which is where it would go wrong.

A column the file does not mention is not an error -- generated aliases such
as `avg_delay_days` have never appeared in any registry -- so unlisted columns
keep their own relative order and follow everything named.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

META_DIR = Path(__file__).resolve().parents[1] / "metadata"


@lru_cache(maxsize=1)
def _config() -> dict:
    path = META_DIR / "column_hierarchy.yaml"
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _spec(tables: list[str] | None) -> dict:
    """The first configured table among those the query touched.

    First rather than merged: a join's columns come from two tables and
    merging their priority lists would invent an order neither file states.
    active_tables is in FROM order, so the leading table is the subject.
    """
    configured = _config().get("tables") or {}
    for table in tables or []:
        if table in configured:
            return configured[table] or {}
    return {}


def presentation(columns: list[str] | None, tables: list[str] | None) -> dict:
    """Where each column should sit, and which start collapsed.

    Returns positions into ``columns``. ``order`` is always a permutation of
    every position, so the frontend can trust that reordering loses nothing.
    """
    names = list(columns or [])
    if not names:
        return {"order": [], "hidden": []}

    spec = _spec(tables)
    priority = list(spec.get("priority") or [])
    hidden_names = set(spec.get("hidden") or [])

    rank = {name: i for i, name in enumerate(priority)}
    # A stable sort on (rank, original position) puts the named columns in the
    # file's order and leaves everything else in the order the query projected
    # it -- the only order that result has.
    order = sorted(
        range(len(names)),
        key=lambda i: (rank.get(names[i], len(priority)), i),
    )
    hidden = [i for i, name in enumerate(names) if name in hidden_names]
    return {"order": order, "hidden": hidden}
```

- [ ] **Step 5: Attach it to a result**

Append to `pipeline/labels.py`:

```python
def with_presentation(result, tables):
    """A result dict with display order and hidden columns added.

    Additive in the same way as with_column_labels, and for the same reason:
    `columns` and `rows` keep exactly what PostgreSQL said, so the state
    reader and the debug pane are unaffected. Anything that is not a dict
    passes through -- a clarification has no result, and inventing an empty
    table for it would put a header row under a sentence.
    """
    if not isinstance(result, dict):
        return result
    from pipeline.column_order import presentation

    shape = presentation(result.get("columns"), tables)
    return {**result, "column_order": shape["order"],
            "hidden_columns": shape["hidden"]}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_column_order.py -v`
Expected: PASS, 9 passed.

- [ ] **Step 7: Wire it into the response**

In `scripts/serve_api.py`, change the existing import:

```python
from pipeline.labels import with_column_labels
```

to:

```python
from pipeline.labels import with_column_labels, with_presentation
```

and in `to_response`, change:

```python
        "result": with_column_labels(r.actual_result),
```

to:

```python
        "result": with_presentation(
            with_column_labels(r.actual_result), after.get("tables")),
```

`after` is the post-turn state snapshot, so the tables are the ones the query that just ran actually touched.

- [ ] **Step 8: Check the whole suite still passes**

Tell the human partner, then:

Run: `python -m pytest tests/ -q`
Expected: the same pass/fail set as before this task, plus 9 new passes.

- [ ] **Step 9: Commit**

```bash
git add metadata/column_hierarchy.yaml pipeline/column_order.py pipeline/labels.py \
        scripts/serve_api.py tests/test_column_order.py
git commit -m "Say which columns matter, as positions the grid can trust"
```

---

### Task 7: Mirror the column hierarchy into the module

**Files:**
- Create: `<module>/metadata/column_hierarchy.yaml`, `<module>/src/Service/ColumnOrder.php`
- Modify: `<module>/vf_sql_chatbot.services.yml`, `<module>/src/Service/TurnRunner.php`, `<module>/tests/parity/check.php`, `<module>/tests/parity/generate_expected.py`

**Interfaces:**
- Consumes: `pipeline.column_order.presentation` as the reference behaviour.
- Produces: `ColumnOrder::presentation(array $columns, array $tables): array` returning `['order' => int[], 'hidden' => int[]]`, and the same two response fields.

- [ ] **Step 1: Copy the configuration**

```bash
cp "c:/Users/ansh.gala/Desktop/Python/wren-poc/metadata/column_hierarchy.yaml" \
   "c:/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/metadata/column_hierarchy.yaml"
```

- [ ] **Step 2: Write the resolver**

Create `<module>/src/Service/ColumnOrder.php`:

```php
<?php

namespace Drupal\vf_sql_chatbot\Service;

/**
 * Display order and hidden columns, ported from pipeline/column_order.py.
 *
 * Positional, for the same reason the Python is: a result carries columns by
 * position and may carry one name twice, so the answer is a list of positions.
 */
class ColumnOrder {

  /**
   * The parsed metadata/column_hierarchy.yaml, or an empty array.
   *
   * @var array
   */
  protected $config;

  public function __construct(Metadata $metadata) {
    $this->config = $metadata->load('column_hierarchy.yaml');
  }

  /**
   * The first configured table among those the query touched.
   *
   * First rather than merged: a join's columns come from two tables and
   * merging their priority lists would invent an order neither states.
   */
  protected function spec(array $tables) {
    $configured = isset($this->config['tables']) && is_array($this->config['tables'])
      ? $this->config['tables'] : [];
    foreach ($tables as $table) {
      if (isset($configured[$table]) && is_array($configured[$table])) {
        return $configured[$table];
      }
    }
    return [];
  }

  /**
   * Where each column should sit, and which start collapsed.
   */
  public function presentation(array $columns, array $tables) {
    if (!$columns) {
      return ['order' => [], 'hidden' => []];
    }
    $spec = $this->spec($tables);
    $priority = isset($spec['priority']) && is_array($spec['priority']) ? $spec['priority'] : [];
    $hiddenNames = isset($spec['hidden']) && is_array($spec['hidden']) ? $spec['hidden'] : [];

    $rank = array_flip($priority);
    $unranked = count($priority);

    $order = range(0, count($columns) - 1);
    // The original index is the tie-break, so the sort is deterministic on
    // every PHP version rather than relying on usort being stable -- which is
    // what parity against the Python's stable sort requires.
    usort($order, function ($a, $b) use ($columns, $rank, $unranked) {
      $ra = isset($rank[$columns[$a]]) ? $rank[$columns[$a]] : $unranked;
      $rb = isset($rank[$columns[$b]]) ? $rank[$columns[$b]] : $unranked;
      return $ra === $rb ? $a - $b : $ra - $rb;
    });

    $hidden = [];
    foreach ($columns as $i => $name) {
      if (in_array($name, $hiddenNames, TRUE)) {
        $hidden[] = $i;
      }
    }
    return ['order' => array_values($order), 'hidden' => $hidden];
  }

}
```

- [ ] **Step 3: Register the service**

First find the real service id of the metadata service and the real method it exposes for loading a YAML file — the constructor above assumes both:

```bash
cd "c:/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot"
grep -n "Metadata" vf_sql_chatbot.services.yml
grep -n "public function" src/Service/Metadata.php
```

If the loader is not `load('column_hierarchy.yaml')`, correct the constructor in Step 2 to whatever `Metadata.php` actually offers. Then add to `vf_sql_chatbot.services.yml`, matching the indentation and quoting the neighbouring entries use:

```yaml
  vf_sql_chatbot.column_order:
    class: Drupal\vf_sql_chatbot\Service\ColumnOrder
    arguments: ['@vf_sql_chatbot.metadata']
```

substituting the real metadata service id for `@vf_sql_chatbot.metadata` if the grep showed a different one.

- [ ] **Step 4: Attach it to the response**

In `<module>/src/Service/TurnRunner.php`, at the point where the result summary already passes through `ColumnLabels`, add the two fields the same way, taking the tables from the post-turn state. Follow whatever the surrounding code already does to reach the state — do not introduce a second path to it.

Note the precedent recorded in the previous phase's ledger: a field added here with a `??` fallback needs an assertion on its **content**, not its presence, or it inherits the blind spot that let `duration_ms` through untested. `order` being a permutation of every position is the content assertion for this one.

- [ ] **Step 5: Measure it against the Python**

Extend `<module>/tests/parity/generate_expected.py` to emit `presentation()` output for the same inputs `tests/test_column_order.py` uses — the duplicated-name case and the unknown-table case included — and add the matching comparison to `check.php`.

Tell the human partner, then:

```bash
python "<module>/tests/parity/generate_expected.py" /tmp/parity
php "<module>/tests/parity/check.php" /tmp/parity
```

Expected: exit 0, with the new column-order layer reported at 100%.

- [ ] **Step 6: Commit (backend repo)**

```bash
cd "c:/xampp/htdocs/dev-arvind-retail-chatbot"
git add web/modules/custom/vf_sql_chatbot
git commit -m "Mirror the column hierarchy, positions and all"
```

---

### Task 8: Suggestions under the default, and their own suite

**Files:**
- Modify: `pipeline/followup.py`
- Create: `tests/test_suggestions.py`

**Interfaces:**
- Consumes: the rule registry via `_rule_predicates()`, and `ConversationState.active_filters`.
- Produces: the same `FollowUp` wire format with one label changed. No new action type — `remove_filter` already does the right thing, and adding one would break the frontend's `ACTION_TYPES` check.

Two behaviours to be clear about before touching anything. First, `explore()` already skips offering a filter on a column that is `in_force`, so once the model applies the default, "Only the active ones" correctly disappears on its own: no change needed there, and a change would be wrong. Second, the *removal* suggestion now fires on a status filter the user never typed, and "Remove the business object status filter" describes that from the system's point of view rather than theirs. That label is what this task fixes — it is the only way a user escapes the default, so it has to read like the thing they would ask for.

- [ ] **Step 1: Write the failing test**

Create `tests/test_suggestions.py`:

```python
"""The follow-up suggestion contract (spec section 8).

Structure, not phrasing -- except where the phrasing is the behaviour: under
the active-first default the status filter in force was never typed by the
user, so how it is offered back to them is the feature.
"""

from __future__ import annotations

from pipeline.context import ConversationState, update_state
from pipeline.followup import explore


def _state_after(sql: str, rows: int = 5) -> ConversationState:
    state = ConversationState()
    update_state(state, "Show the AR_NPD_Shirting items", sql, rows,
                 "AR_NPD_Shirting", "new_block")
    return state


_DEFAULTED = (
    "SELECT business_object_id, business_object_status "
    "FROM tms_business_object_flat "
    "WHERE business_object_type = 'AR_NPD_Shirting' "
    "AND business_object_status = 'Active'"
)


def test_the_active_filter_is_not_offered_again_once_it_is_in_force():
    """The default already applied it. Offering it would be offering a no-op."""
    followup = explore(_state_after(_DEFAULTED), row_count=5)
    assert followup is not None
    values = [s.action.value for s in followup.suggestions
              if s.action.type == "add_filter"]
    assert "Active" not in values


def test_escaping_the_default_is_offered_as_seeing_every_status():
    """The user never typed this filter, so it cannot be described as theirs.

    The action is unchanged -- remove_filter on the status column is exactly
    right -- but the label has to read like the question a person would ask.
    """
    followup = explore(_state_after(_DEFAULTED), row_count=5)
    escape = [s for s in followup.suggestions
              if s.action.type == "remove_filter"
              and s.action.field == "business_object_status"]
    assert len(escape) == 1, "no way offered to see the other statuses"
    label = escape[0].label.lower()
    assert "remove" not in label, f"still described as removing a filter: {label!r}"
    assert "status" in label


def test_a_filter_the_user_did_state_is_still_offered_as_a_removal():
    """Only the defaults are relabelled.

    A filter the user asked for is theirs to remove, and calling that "show
    every business unit" would be putting words in their mouth.
    """
    followup = explore(_state_after(
        "SELECT business_object_id FROM tms_business_object_flat "
        "WHERE business_object_type = 'AR_NPD_Shirting' "
        "AND business_unit = 'unit1'"), row_count=3)
    removals = [s for s in followup.suggestions if s.action.type == "remove_filter"]
    assert removals
    assert any("remove" in s.label.lower() for s in removals)


def test_a_closed_status_the_user_asked_for_is_not_treated_as_a_default():
    """Closed is a status the default never adds, so it is the user's."""
    followup = explore(_state_after(
        "SELECT business_object_id FROM tms_business_object_flat "
        "WHERE business_object_type = 'AR_NPD_Shirting' "
        "AND business_object_status = 'Closed'"), row_count=5)
    escape = [s for s in followup.suggestions
              if s.action.field == "business_object_status"]
    assert all("remove" in s.label.lower() for s in escape)


def test_every_suggestion_carries_a_valid_action():
    from pipeline.followup import ACTION_TYPES

    followup = explore(_state_after(_DEFAULTED), row_count=5)
    for s in followup.suggestions:
        assert s.action.type in ACTION_TYPES
        assert s.id and s.label


def test_an_empty_result_is_offered_nothing():
    """Nothing to narrow. Suggesting a narrowing anyway is how a helpful
    feature becomes noise."""
    assert explore(_state_after(_DEFAULTED), row_count=0) is None


def test_a_turn_that_never_ran_is_offered_nothing():
    assert explore(ConversationState(), row_count=None) is None
    assert explore(None, row_count=5) is None


def test_at_most_four_and_never_exactly_one():
    followup = explore(_state_after(_DEFAULTED), row_count=5)
    assert 2 <= len(followup.suggestions) <= 4


def test_the_wire_format_survives_having_no_suggestions():
    """Empty or missing suggestion data must not break the response."""
    from pipeline.followup import NO_FOLLOWUP

    wire = NO_FOLLOWUP.to_dict()
    assert wire["follow_up_required"] is False
    assert wire["suggestions"] == []
    assert set(wire) == {"follow_up_required", "type", "reason", "question",
                         "suggestions", "allow_free_text"}
```

- [ ] **Step 2: Run it to verify it fails**

Tell the human partner, then:

Run: `python -m pytest tests/test_suggestions.py -v`
Expected: `test_escaping_the_default_is_offered_as_seeing_every_status` FAILS with `still described as removing a filter: 'remove the business object status filter'`. The rest should already pass — that is the point of writing them: they pin behaviour that must not change.

- [ ] **Step 3: Relabel only the defaulted filters**

In `pipeline/followup.py`, after the `_NOT_GROUPABLE` definition, add:

```python
def _default_values() -> dict[str, str]:
    """Column -> the value the active-first default would have added.

    Read out of the registry rather than written here, so that renaming a
    status value in the rules cannot leave this list quietly wrong. The
    default_to_active policy rule carries no fragment of its own by design, so
    the values come from the two rules it refers to.
    """
    return {
        column: value
        for name, _table, column, value in _rule_predicates()
        if name in ("active_business_object", "open_task")
    }
```

Then, inside `explore()`, beside the existing `in_force = set(state.active_filters)`, add:

```python
    in_force_predicates = dict(state.active_filters)
```

and replace the removal block — currently:

```python
    removable = [c for c in in_force if c not in _NOT_GROUPABLE]
    if removable:
        column = sorted(removable)[0]
        suggestions.append(Suggestion(
            id=f"remove_{_slug(column)}",
            label=f"Remove the {column.replace('_', ' ')} filter",
            action=Action(type="remove_filter", field=column),
        ))
```

with:

```python
    removable = [c for c in in_force if c not in _NOT_GROUPABLE]
    if removable:
        column = sorted(removable)[0]
        # A status filter matching the active-first default was never typed by
        # the user, so "remove your filter" describes it from the system's
        # point of view. Dropping it is the only way out of the default, which
        # makes this label load-bearing: it has to read like the question a
        # person would actually ask.
        defaulted = _default_values().get(column)
        was_defaulted = (
            defaulted is not None
            and f"'{defaulted}'" in (in_force_predicates.get(column) or "")
        )
        label = (
            f"Show every {column.replace('_', ' ')}, not just {defaulted.lower()}"
            if was_defaulted
            else f"Remove the {column.replace('_', ' ')} filter"
        )
        suggestions.append(Suggestion(
            id=f"remove_{_slug(column)}",
            label=label,
            action=Action(type="remove_filter", field=column),
        ))
```

`active_filters` maps a column to the whole predicate string, so the value has to be matched *inside* it — `business_object_status = 'Active'`, not `Active`. That is why the quoted form is used.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_suggestions.py tests/test_followup.py -v`
Expected: PASS. `tests/test_followup.py` must be green unchanged; if it asserts the old removal label anywhere, that is a real conflict — report it rather than editing the older test to agree.

- [ ] **Step 5: Full suite**

Tell the human partner, then:

Run: `python -m pytest tests/ -q`
Expected: the same pass/fail set as before, plus the new passes.

- [ ] **Step 6: Commit**

```bash
git add pipeline/followup.py tests/test_suggestions.py
git commit -m "Offer the way out of the active default in the user's words"
```

---

### Task 9: Mirror the suggestion change into the module

**Files:**
- Modify: `<module>/src/Service/Followup.php`

**Interfaces:**
- Consumes: the Python behaviour from Task 8 as the specification.
- Produces: identical `explore()` output, which the parity harness measures over 1,212 recorded cases.

- [ ] **Step 1: Port the change**

In `<module>/src/Service/Followup.php`, add the helper beside the existing rule-predicate reader:

```php
  /**
   * Column => the value the active-first default would have added.
   *
   * Read out of the registry rather than written here, so that renaming a
   * status value in the rules cannot leave this list quietly wrong. The
   * default_to_active policy rule carries no fragment of its own by design,
   * so the values come from the two rules it refers to.
   */
  protected function defaultValues() {
    $out = [];
    foreach ($this->rulePredicates() as $predicate) {
      list($name, $table, $column, $value) = $predicate;
      if ($name === 'active_business_object' || $name === 'open_task') {
        $out[$column] = $value;
      }
    }
    return $out;
  }
```

Use whatever `rulePredicates()` is actually called in this file and whatever shape it returns — check with `grep -n "sql_fragment\|function rule" src/Service/Followup.php` and destructure accordingly.

Then, in the removal-suggestion block of `explore()`, replace the unconditional label with:

```php
      // A status filter matching the active-first default was never typed by
      // the user, so "remove your filter" describes it from the system's
      // point of view. Dropping it is the only way out of the default, which
      // makes this label load-bearing: it has to read like the question a
      // person would actually ask.
      $defaults = $this->defaultValues();
      $defaulted = isset($defaults[$column]) ? $defaults[$column] : NULL;
      $predicate = isset($inForce[$column]) ? $inForce[$column] : '';
      $wasDefaulted = $defaulted !== NULL
        && strpos($predicate, "'" . $defaulted . "'") !== FALSE;
      $label = $wasDefaulted
        ? 'Show every ' . str_replace('_', ' ', $column) . ', not just ' . strtolower($defaulted)
        : 'Remove the ' . str_replace('_', ' ', $column) . ' filter';
```

`$inForce` must be the map of column to full predicate string, not a set of column names — the value is matched *inside* the predicate, exactly as in the Python. If the PHP currently keeps only the keys, thread the map through as the Python's `in_force_predicates` does.

- [ ] **Step 2: Measure it**

Tell the human partner, then:

```bash
python "<module>/tests/parity/generate_expected.py" /tmp/parity
php "<module>/tests/parity/check.php" /tmp/parity
```

Expected: exit 0, and the follow-up layer's `explore` row back at exact over all 1,212 cases. Anything less means the label or the ordering diverges; the harness prints the first disagreement.

- [ ] **Step 3: Commit (backend repo)**

```bash
cd "c:/xampp/htdocs/dev-arvind-retail-chatbot"
git add web/modules/custom/vf_sql_chatbot/src/Service/Followup.php
git commit -m "Mirror the active-default escape label"
```

---

### Task 10: Suggestions that reflect the rows that came back

**Files:**
- Modify: `pipeline/followup.py`, `scripts/serve_api.py`, `tests/test_suggestions.py`
- Modify: `<module>/src/Service/Followup.php`, `<module>/src/Service/TurnRunner.php`

**Interfaces:**
- Consumes: the result dict from Task 6 (`columns`, `rows`).
- Produces: `explore(state, row_count, result=None)` — a **third, optional** parameter. Every existing two-argument call behaves exactly as before, which is what keeps the parity harness's 1,212 recorded `explore` cases valid without regeneration.

Spec §7 asks that suggestions reflect the data actually returned and avoid ones that cannot be acted on. Today `explore()` sees only `row_count`, so it will offer "Group by business unit" for a result whose every row has the same business unit — one group, which is not a breakdown — and will offer a sort on a column the projection does not contain.

**A warning about how this can go wrong silently.** Because the new parameter is optional, the parity harness will stay green whether or not the PHP passes it, while production behaviour diverges. The harness exercises the two-argument form. Steps 5 and 6 are therefore not optional polish; they are the only thing standing between this task and a divergence no check will report. This is the same shape of blind spot the previous phase recorded for `duration_ms`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_suggestions.py`:

```python
_ONE_UNIT = {
    "columns": ["business_object_id", "business_unit"],
    "rows": [[1, "unit1"], [2, "unit1"], [3, "unit1"]],
}
_TWO_UNITS = {
    "columns": ["business_object_id", "business_unit"],
    "rows": [[1, "unit1"], [2, "unit2"], [3, "unit1"]],
}


def _listed(sql: str = _DEFAULTED, rows: int = 3):
    return _state_after(sql, rows)


def test_grouping_is_not_offered_when_every_row_shares_the_value():
    """One group is not a breakdown.

    The schema says business_unit is enumerated, which is what made it a
    candidate; the rows say this answer holds one unit, which is what makes
    grouping by it useless.
    """
    followup = explore(_listed(), row_count=3, result=_ONE_UNIT)
    grouped = [s for s in (followup.suggestions if followup else [])
               if s.action.type == "add_group_by"
               and s.action.field == "business_unit"]
    assert grouped == []


def test_grouping_is_still_offered_when_the_value_varies():
    followup = explore(_listed(), row_count=3, result=_TWO_UNITS)
    grouped = [s for s in followup.suggestions
               if s.action.type == "add_group_by"
               and s.action.field == "business_unit"]
    assert len(grouped) == 1


def test_a_sort_is_only_offered_on_a_column_the_answer_contains():
    """Sorting by a column that was not projected asks the user to reorder
    something they cannot see."""
    followup = explore(_listed(), row_count=3, result=_ONE_UNIT)
    sorts = [s for s in (followup.suggestions if followup else [])
             if s.action.type == "set_sort"]
    for s in sorts:
        assert s.action.field in _ONE_UNIT["columns"]


def test_omitting_the_result_preserves_the_old_behaviour_exactly():
    """The parity harness calls the two-argument form over 1,212 recorded
    cases. Those must not move."""
    with_rows = explore(_listed(), row_count=3, result=None)
    without = explore(_listed(), row_count=3)
    assert [s.to_dict() for s in with_rows.suggestions] == \
           [s.to_dict() for s in without.suggestions]


def test_a_result_with_no_rows_is_treated_as_no_information():
    """An error result carries no `rows` key at all, and a clarification
    carries no result. Neither may crash the layer nor silently suppress
    every suggestion."""
    followup = explore(_listed(), row_count=3, result={"error": "boom"})
    assert followup is not None and followup.suggestions
```

- [ ] **Step 2: Run them to verify they fail**

Tell the human partner, then:

Run: `python -m pytest tests/test_suggestions.py -v`
Expected: the first three FAIL with `TypeError: explore() got an unexpected keyword argument 'result'`.

- [ ] **Step 3: Make the layer data-aware**

In `pipeline/followup.py`, add above `explore()`:

```python
def _varies(result: dict | None, column: str) -> bool | None:
    """Whether the returned rows hold more than one value for ``column``.

    None means "no information": there was no result, no rows, or the column
    was not projected. None is not False -- a suggestion must not be
    suppressed because the evidence is missing, only because the evidence is
    against it.
    """
    if not isinstance(result, dict):
        return None
    columns, rows = result.get("columns"), result.get("rows")
    if not columns or not rows or column not in columns:
        return None
    index = columns.index(column)
    seen = set()
    for row in rows:
        if index < len(row):
            seen.add(row[index])
        if len(seen) > 1:
            return True
    return False


def _projected(result: dict | None, column: str) -> bool | None:
    """Whether ``column`` is among the columns the answer actually carries."""
    if not isinstance(result, dict) or not result.get("columns"):
        return None
    return column in result["columns"]
```

Change the signature to:

```python
def explore(state, row_count: int | None, result: dict | None = None) -> FollowUp | None:
```

In the grouping block, replace:

```python
        for column in _enum_columns(table):
            if column in _NOT_GROUPABLE or column in in_force:
                continue
```

with:

```python
        for column in _enum_columns(table):
            if column in _NOT_GROUPABLE or column in in_force:
                continue
            # One group is not a breakdown. Only skip on evidence against:
            # _varies returns None when the column was not projected, and
            # that is not a reason to withhold the suggestion.
            if _varies(result, column) is False:
                continue
```

In the sorting block, replace:

```python
        for fragment in _SORTABLE:
            column = next((c for c in _columns(table) if fragment in c), None)
            if column:
```

with:

```python
        for fragment in _SORTABLE:
            column = next(
                (c for c in _columns(table)
                 if fragment in c and _projected(result, c) is not False),
                None)
            if column:
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_suggestions.py tests/test_followup.py -v`
Expected: PASS, including `test_omitting_the_result_preserves_the_old_behaviour_exactly` — that one is the guarantee the parity fixtures stay valid.

- [ ] **Step 5: Pass the rows in, in Python**

In `scripts/serve_api.py` there is no direct `explore()` call — the follow-up is attached inside `pipeline/lean_runner._attach_followup`. Find it:

```bash
grep -n "explore(" pipeline/lean_runner.py pipeline/followup.py scripts/serve_api.py
```

At each call site that has the executed result to hand, pass it as the third argument. Where a call site does not have it, leave the two-argument form: that is what the parameter's default is for.

- [ ] **Step 6: Mirror it in PHP, and pass the rows in there too**

Port `varies()` and `projected()` into `<module>/src/Service/Followup.php` with the same three-state return — TRUE, FALSE, NULL, compared with `===` so that NULL and FALSE cannot be confused, which is the whole point of the tri-state:

```php
  /**
   * Whether the returned rows hold more than one value for $column.
   *
   * NULL means "no information": no result, no rows, or the column was not
   * projected. NULL is not FALSE -- a suggestion must not be suppressed
   * because the evidence is missing, only because it is against.
   */
  protected function varies($result, $column) {
    if (!is_array($result) || empty($result['columns']) || empty($result['rows'])) {
      return NULL;
    }
    $index = array_search($column, $result['columns'], TRUE);
    if ($index === FALSE) {
      return NULL;
    }
    $seen = [];
    foreach ($result['rows'] as $row) {
      if (array_key_exists($index, $row)) {
        $seen[] = $row[$index];
      }
      if (count(array_unique($seen, SORT_REGULAR)) > 1) {
        return TRUE;
      }
    }
    return FALSE;
  }
```

Add the optional third parameter to `explore()`, apply both gates with `=== FALSE` / `!== FALSE` exactly as the Python does, and pass the executed result in from `TurnRunner.php` where the follow-up is attached.

- [ ] **Step 7: Verify parity, and verify the thing parity cannot see**

Tell the human partner, then:

```bash
python "<module>/tests/parity/generate_expected.py" /tmp/parity
php "<module>/tests/parity/check.php" /tmp/parity
```

Expected: exit 0 with `explore` still exact — because the harness calls the two-argument form.

That green is not evidence the mirror works. Prove the three-argument form separately: extend `generate_expected.py` to emit `explore()` output for the `_ONE_UNIT` and `_TWO_UNITS` results above, and compare them in `check.php`. Without that, the divergence this task's warning describes stays invisible.

- [ ] **Step 8: Commit**

```bash
git add pipeline/followup.py pipeline/lean_runner.py tests/test_suggestions.py
git commit -m "Offer only the breakdowns the rows can actually support"
```

```bash
cd "c:/xampp/htdocs/dev-arvind-retail-chatbot"
git add web/modules/custom/vf_sql_chatbot
git commit -m "Mirror the data-aware suggestion gates, and measure the new form"
```

---

## Done when

- `default_to_active` is in both copies of `business_rules.yaml`, byte-identical, and the parity harness's recorded prompt md5 has been updated to match.
- `benchmark/active_first_questions.yaml` runs, and the implicit and explicit halves are recorded separately in the ledger.
- Every turn in `lean_questions.yaml` and `questions.yaml` that active-first affects has either a new predicate or a `note` saying which carve-out spared it.
- `README.md` says plainly that figures recorded before 2026-09-09 do not compare with figures after it.
- A result carries `column_order` and `hidden_columns` as positions, and `order` is a permutation of every position.
- `ColumnOrder.php` agrees with `column_order.py` in the parity harness, duplicated column names included.
- The suggestion layer offers no redundant active filter, and offers the escape from the default in the user's words.
- No grouping is offered on a column every returned row shares, and no sort on a column the answer does not carry.
- The three-argument `explore()` is compared across both implementations — not just the two-argument form the existing fixtures exercise.
- `python -m pytest tests/ -q` passes, and `php tests/parity/check.php /tmp/parity` exits 0.

## Known scope boundaries

Two things spec §7 asks for are deliberately **not** in this plan, and both belong to Plan 2:

- suggestions using **Initiative** terminology — the labels are generated from column names (`business_object_status` → "business object status"), so changing them is part of the terminology migration and needs to move with `pipeline/labels.py`'s `_ACRONYMS`, not before it.
- the rename of the `active_business_object` and `closed_business_object` rule *names*, which `_default_values()` matches on by string. Plan 2 must update both sides together or the relabelling in Task 8 silently stops firing — there is a test for it, `test_escaping_the_default_is_offered_as_seeing_every_status`, and it will catch this.
