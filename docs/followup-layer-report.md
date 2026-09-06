# Follow-up intelligence layer — engineering report

Branch: `feature/follow-up-intelligence` (from `main`)

## 1. What was added

A follow-up decision layer between the question and the existing pipeline. It
repairs what the user typed, decides whether the turn continues the thread,
asks which of several things was meant when that is genuinely unclear,
understands the answer, and offers next moves.

**It adds no LLM calls.** In the 115-turn suite it removed six. See
[followup-layer.md](followup-layer.md) for the reasoning.

## 2. Architecture changes

Nothing was replaced. Three additions and three extensions:

| File | New / changed | Role |
|---|---|---|
| `benchmark/normalize.py` | new, 210 lines | Repair against the schema's own vocabulary |
| `benchmark/followup.py` | new, 430 lines | Contract, candidates, suggestions, action→state |
| `benchmark/followup_questions.yaml` | new | 115 turns |
| `scripts/build_followup_suite.py` | new | Builds and validates them |
| `scripts/analyze_followup.py` | new | Failure classification by stage |
| `benchmark/context.py` | extended | Subject-noun topic detection; pending clarification |
| `benchmark/lean_runner.py` | extended | Wiring; follow-up fields on `TurnResult` |
| `benchmark/lean_suite.py` | extended | Three new expectation fields, one new decision |
| `scripts/build_schema_description.py` | fixed | Subject column always enumerated |
| `scripts/run_lean_suite.py` | extended | Follow-up metrics, `--no-followup` |

No new services, no second query planner, no parallel state system. The
existing `ConversationState` was extended rather than duplicated.

## 3. Follow-up schema

```json
{
  "follow_up_required": true,
  "type": "clarification | exploration | none",
  "reason": "ambiguous_entity | unknown_value | ambiguous_request | useful_next_actions",
  "question": "Which AR_YD type did you mean?",
  "suggestions": [
    {
      "id": "set_entity_AR_YD_Suiting",
      "label": "AR_YD_Suiting",
      "action": {"type": "set_entity", "field": "business_object_type",
                 "operator": "=", "value": "AR_YD_Suiting"}
    }
  ],
  "allow_free_text": true
}
```

Nine action types: `set_entity`, `add_filter`, `replace_filter`,
`remove_filter`, `add_group_by`, `set_sort`, `set_limit`, `set_aggregate`,
`drill_down`. A suggestion never carries SQL.

## 4. Results

**New suite** — `benchmark/followup_questions.yaml`, 115 turns:

| Metric | Iteration 1 | Iteration 2 |
|---|---|---|
| SQL accuracy | 109/115 (94.8%) | **114/115 (99.1%)** |
| Repair | 100% (n=20) | **100%** (n=20) |
| Follow-up type | 92.1% (n=63) | **100%** (n=42) |
| Suggested action | 96.9% (n=32) | **100%** (n=32) |
| Turn classification | 98.0% | **100%** |
| Clarified with no LLM call | 8 | 6 |

**Regression** — same provider (Claude CLI, lean mode, sonnet), before is the
layer absent, after is the layer on:

| Suite | Result before → after | Semantic before → after |
|---|---|---|
| lean 50 | 96.0% → **100.0%** | 96.0% → **100.0%** |
| targeted 53 | 96.2% → **98.1%** | 98.1% → 98.1% |
| expansion 100 | 99.0% → **100.0%** | 98.0% → 96.0% |

Nothing regressed. The expansion semantic figure moved on four turns that are
equivalent SQL written differently — `COUNT(*)` versus `COUNT(DISTINCT pk)` on
a table keyed by that column, `display_flag = 0` versus `display_flag <> 1`
where 0 and 1 are the only values. Result accuracy rose on the same run.

## 5. Failure analysis

Iteration 1 produced six defects. Every one had a distinct root cause and none
was patched at the case level.

| Case | Stage | Root cause | Fix |
|---|---|---|---|
| F63 | candidate retrieval | `sales` matched as a substring of `AR_SALESPLAN_Suiting`, so a clear question about the sales team was answered with "which sales type?" | Match runs of whole underscore components |
| F10 | candidate retrieval | `suiting` is the last component of all five types carrying it — a family, not a truncated name | A token ending every match no longer prompts |
| G14.2 | state | The system asked "which one?" and could not read the answer; the reply reached the model as a bare noun with empty context | Pending clarification held on state; reply resolved back into the original question |
| F14/F16 | follow-up generation | Refused to offer "show all again" unless two filters were in force, so a single-filter count got one suggestion and therefore none | One removable filter is enough |
| F65 | benchmark | Asserted SQL where the model correctly said unit7 does not exist | Case corrected to `zero_or_clarify` |
| G08.3 | benchmark | Expected a count where the documented context contract says a grouping does not carry over | Question reworded to ask for the count |

A seventh was found by a test rather than a run: `AR_YD_Shirting` and
`AR_YD_SHIRTING` — 52 rows and 2 rows, genuinely distinct — produced the same
suggestion `id`, so a frontend returning that id would have selected the wrong
one. Ids built from data values now preserve case and are matched exactly.

**Remaining, after iteration 2 — three, all understood:**

- **F36** (`SLA status is Breached`) — the model returns the 635 `Delayed`
  rows without saying it changed the question. Pre-existing: the identical
  T13 fails the same way in the baseline. The follow-up layer cannot catch it,
  because the model never signals doubt.
- **F10** — `ILIKE '%Suiting%'` where the case expects `LIKE '%Suiting'`. Same
  rows; the case picked one of two reasonable forms.
- **G09.3** — the model adds `display_flag = 1` to "my open tasks". The
  `my_tasks` rule's scope note says that condition belongs only to the bare
  concept; the model over-applies it. A registry wording issue, not a layer one.

## 6. Token analysis

Per turn, averaged over each suite:

| Suite | Prompt before → after | Cache read before → after | Effective before → after |
|---|---|---|---|
| lean 50 | 10,549 → 10,930 | 8,120 → 10,636 | 3,341 → 1,437 |
| targeted 53 | 10,516 → 10,898 | 7,896 → 10,676 | 3,501 → 1,380 |
| expansion 100 | 10,613 → 10,922 | 7,948 → 10,745 | 3,549 → 1,330 |

**What the layer costs:** +366 prompt tokens per turn (+3.5%), all of it the
schema fix that enumerates `business_object_type` (~116 tokens on two tables).
Repair, classification, suggestion generation and candidate retrieval cost
zero — they never reach the model.

**What it saves:** six turns in the follow-up suite were answered with no model
call at all. On a suite where 5 of 115 turns are ambiguous entity names, that
is a 5% reduction in calls; in a production mix it would depend on how often
users type partial names.

**A caveat worth stating.** The effective-token column weights cache reads at
0.1×, and it fell 57–63%. Most of that is a higher cache-hit ratio (75% → 97%),
which the stable prompt prefix helps but does not fully explain — cache warmth
also depends on how recently a similar prompt ran, and the after-runs went out
four in parallel against one prefix rather than three. **The layer should not
be credited with that drop.** The honest claim is +3.5% prompt tokens, zero
extra calls, and six calls removed.

**Long-chain growth:** unchanged, and still flat. Context stays a fixed set of
fields, averaging 156 characters on the 115-turn suite against 155 on the
50-turn one. Turn 1 and turn 5 of a thread cost the same.

## 7. Self-correction iterations

Two full loops: implement → run 115 → classify by stage → fix root causes →
re-run 115 → re-run all three regression suites. Plus continuous TDD, where
five defects were caught by tests before any run:

- Plurals being "corrected" into singulars, on 20 of the 203 existing questions
- `Sort by due date` → `short by due date`, `Back to` → `black to`
- `busines` passing as correct because `business` is
- `attribute` rewritten into `attributes`
- Duplicate suggestion ids

## 8. Remaining weaknesses

1. **Silent substitution is not addressable from here.** When the model
   answers a question about a value that does not exist by quietly using one
   that does, there is no signal to act on. Detecting it would need the layer
   to check literals in the generated SQL against the gazetteer before
   execution — a real option, and out of scope for this change.
2. **Relative dates are untested.** "Last month", "last 7 days" would return
   nothing: the data ends July 2026 and the system date is September 2026. The
   suite uses explicit months, as the existing suites do.
3. **Sparse tables get no suggestions.** `tms_user_flat` has no enumerated
   column and no business rule, so a question about users gets nothing worth
   offering. Correct behaviour, but the coverage is thin.
4. **The repair vocabulary is single-token.** "buisness unit" is fixed;
   "bussines objekt" (two errors in a phrase) is fixed word-by-word and would
   not catch a phrase-level confusion.
5. **Three stale test files** (`test_database.py`, `test_metadata.py`,
   `test_ground_truth.py`) still assert the original demo schema and fail on
   `main` as well. Untouched here.

## 9. Recommended next steps

1. **Ground literals before execution.** Check every string literal in the
   generated SQL against the gazetteer; an unknown value becomes a
   clarification with the real values attached. This is the one thing that
   would close F36/T13, and the machinery already exists.
2. **Clarify the `my_tasks` scope wording** so `display_flag` stops being
   applied to "my open tasks" (G09.3).
3. **Retarget or delete the three stale test files** so the suite is green.
4. **Decide the exploration policy for sparse tables** — either leave them
   silent, or add a generic "group by any column with few values" fallback.
