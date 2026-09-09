# Initiative Phase — Roadmap and Spec Corrections

Recorded 9 September 2026, before any code was written. The spec for this phase
asked for active-first prioritisation, a Business Object → Initiative rename,
richer AG Grid responses, better follow-up suggestions, and initiative
dialog/colour integration — all of it "Python first, then PHP/Drupal".

Most of it is buildable. Several of its claims are not true of this codebase,
and one of them changes the meaning of the project's accuracy figures. This
document records what was checked, what was decided, and how the work is cut.

## Where the code actually lives

Three repositories, and the spec treats them as one:

| | Path | Branch | Holds |
| --- | --- | --- | --- |
| Python POC | `Desktop/Python/wren-poc` | `develop` | the reference pipeline, the rules, the benchmark, a plain QA console |
| Drupal backend | `xampp/htdocs/dev-arvind-retail-chatbot` | `Tms-Sql-Chatbot-Testing` | `vf_sql_chatbot`, a 1:1 port of the Python, plus the parity harness |
| React frontend | `xampp/htdocs/WCMS%20-%20Frontend%20-%20Arvind%20Retail` | `feat/sql-chatbot` | the chat UI, AG Grid, `/track_bos`, the initiative dialog |

The React app is fed by the **Drupal** backend. Nothing in the frontend talks
to the Python.

## What the spec got wrong

**1. "Implement in Python first" cannot hold for §5, §6, §9, §10, §11.**
The Python POC's UI (`ui/index.html`) loads no grid library at all — it is a
plain QA console with a hand-rolled table — and there is no `/track_bos` in it.
Pivot, grouping, the initiative dialog and the colour bar are React-only
concerns. Python can own the *response contract*; it cannot own the rendering.
Decided order: Python contract → PHP mirror under parity → React rendering.

**2. Pivot and grouping are available.** `ag-grid-enterprise` 32.3.3 is
installed alongside community and react at the same version; the licence key is
in the frontend's `.env`, injected by webpack's `DefinePlugin` via `dotenv`; and
`initAgGrid()` runs in `src/index.js`. This was worth checking because pivot and
row grouping are Enterprise-only features and the spec assumed them.

**3. Rows are positional, and this is the crux of the grid design.**
`ChatResultGrid` keys its row objects `c0..cN` **by index**, deliberately,
because duplicate column names in one result are legal (`COUNT(*)` twice; a
join projecting `business_object_ref_id` from both sides). Any `rowGroup`,
`pivot` or `aggFunc` configuration the backend sends must therefore address
columns **by position, not by name**. The spec does not mention this.

**4. "Initiative" is already partly in place.** `business_rules.yaml` already
declares `entity_alias`: Initiative, Order, BO and Business Object are one
entity. `question_sql_pairs.yaml` already contains "Show me Initiative 123" and
"Which initiatives are active?". `pipeline/context.py` already lists
`initiative`/`initiatives` among its subject nouns. The frontend already has
`InitiativeQueueReport.jsx` and `InitiativeTrendReport.jsx`. This is an
extension, not a greenfield migration.

**5. §10's "do not invent a colour mapping" is not satisfiable as written.**
The two tables disagree about what a colour is:

- `tms_business_object_flat.business_object_color` → `Black`, `Green`, `Red`, `White`
- `tms_task_flat.business_object_color` → `a_bl`, `b_re`, `d_gr`, `e_wh`

`ColorBoxRenderer` renders `<div class="ag-color-box-cell … {value}">` and needs
the **class** form. So initiative rows do require a `Black → a_bl`,
`Red → b_re`, `Green → d_gr`, `White → e_wh` mapping, which exists nowhere
today. `c_ye` and `nocolor` are in the frontend's vocabulary
(`Utils/Common.js: tms_priority_colors`) with no corresponding value in the
initiative data.

**6. Those colour classes are CSS-scoped to a different table.** The colour
rules live under `.test_datatable_table` in
`components/DataTables/AGGrid/Styles/ag-grid-theme.css`, with unscoped
definitions in `css/main.scss`. The chat grid's wrapper is
`.sqlchat-grid-body.ag-theme-alpine`. The previous phase lost a whole task to
this same class of scoping bug, and its ledger records why the fix worked.

**7. PHP is ahead of Python on the result contract.** `QueryRunner::summary()`
returns `types` and `duration_ms`; Python's `evaluator.result_summary()` returns
`columns`, `row_count`, `rows`, `truncated` and neither of the other two. So
"Python is the reference implementation" is already false for `types` —
precisely the field AG Grid column typing needs. Python has to catch up before
the grid work can claim a shared contract.

**8. The rename carries measurable risk, not cosmetic churn.** The parity
harness compares the **built system prompt byte for byte** (recorded: 24,316
bytes, md5 `4c5c426e…`). `metadata/*.yaml` exists twice and is currently
byte-identical, so any wording change must land in both copies in lockstep. It
also changes what the model reads, which can move generated SQL and therefore
accuracy. Renaming terms inside those files is a measured change.

**9. The database has no `cancelled` and no `completed` status.** The spec's own
examples — "show me cancelled orders", "my completed tasks" — name values that
do not exist. `business_object_status` is `Active`/`Closed`/`Short Closed`;
`task_status` is `open`/`closed`. Those questions must keep their existing
`zero_or_clarify` behaviour rather than being quietly rescued.

**10. `tms_user_flat` has no status column at all** (`user_id`, `user_name`,
`role_count`, `department_count`). §1's "similar business objects should follow
the same principle where an active/inactive status exists" resolves to exactly
two entities: initiatives and tasks.

**11. The biggest one: active-first inverts the benchmark.** 31 of 50 turns in
`benchmark/lean_questions.yaml` and 30 of 86 in `benchmark/questions.yaml` have
expected SQL with **no** status predicate, and the lean suite's header comment
explicitly calls a leaked `Active` filter a defect: "clean split, so a leaked
'Active' filter is visible as 5 instead of 10". Active-first does not add
behaviour on top of the benchmark; it redefines a correct answer for roughly
62% of it, and makes every figure recorded in `results/` non-comparable. Some of
those turns are also cases where defaulting to active is plainly wrong — `S12`
counts distinct types, `S21` counts rows with a missing workflow name.

## Decisions on record

Taken by the human partner, 9 September 2026:

1. **Active-first mechanism** — a business rule plus a measured compliance
   gate, not a post-generation SQL rewrite. Keeps one thing writing SQL, and
   reaches both provider modes through the one file that feeds both.
2. **Benchmark** — re-baseline the affected turns and record that pre-change
   figures do not compare. The benchmark should keep measuring the product that
   actually ships.
3. **Rule scope** — listings and counts of records, with carve-outs written into
   the rule's own `scope`: a stated status, all/history, distributions across
   status, counts of distinct values, and missing-data questions.
4. **Column-hierarchy YAML** — presentation metadata only. It does not touch
   SQL, so it cannot move accuracy or the byte-identical prompt.
5. **Ordering** — Python contract → PHP mirror → React rendering.
6. **Plan shape** — four plans, each shipping working, testable software alone.

## The four plans

Each plan carries its own PHP mirror for the layers the parity harness covers.
That is not a departure from "Python first": within every plan the Python is
written and tested before the mirror. It is forced by the harness — leaving the
PHP to a later plan would leave `check.php` failing for the whole interval, and
a parity check that is known to be red stops being read.

### Plan 1 — Active-first and the column hierarchy *(written)*

`docs/superpowers/plans/2026-09-09-active-first-and-column-hierarchy.md`

The `default_to_active` rule; its mirror; a paired implicit/explicit compliance
suite; re-baselining the two existing suites; `metadata/column_hierarchy.yaml`
with a positional resolver in both languages; the follow-up suggestion suite
plus the one label change the default forces; and data-aware suggestion gating,
so a breakdown is only offered where the returned rows can support one. Ten
tasks.

Ships: the chatbot defaults to active, with the behaviour measured and the
benchmark honest about it.

### Plan 2 — Business Object → Initiative

Scope: the domain-terminology migration, in lockstep across both
`metadata/` copies, `pipeline/context.py`'s subject nouns, `pipeline/labels.py`'s
`_ACRONYMS` (which currently expands `bo` → `BO`), the suggestion labels, the
frontend's user-visible strings, and a dedicated migration suite (§3).

Boundaries, decided by finding 8 and §2's own backward-compatibility clause:
the technical identifiers stay. `tms_business_object_flat`,
`business_object_id`, `business_object_status`, `bo_id` and the REST field names
are the database and the API contract; renaming them would break both
implementations and every recorded suite. What changes is what a **person**
reads: definitions, descriptions, terminology entries, labels, suggestion text.

Must include: a re-run of both suites, because this edits the system prompt, and
a parity re-run with the recorded md5 updated.

### Plan 3 — The grid response contract, and pivot/grouping

Scope, in order: add `types` to Python's `result_summary` so it matches the PHP
already shipping it (finding 7); agree a grid-configuration block that travels
with a result, addressing columns **by position** (finding 3), saying which
columns are groupable and pivotable and what aggregation suits each measure;
mirror it in PHP under parity; then implement rendering in
`ChatResultGrid.jsx` — `rowGroup`, `pivot`, `aggFunc`, the tool panel — against
the existing pagination, resize and `sizeColumnsToFit` behaviour.

Constraints already known: the grid must not hard-code pivot or grouping on
(§6); `onGridSizeChanged → sizeColumnsToFit()` is load-bearing and was
established by the previous phase's final review; and the enterprise features
are licensed, so no new dependency is needed.

### Plan 4 — Initiative dialog and colour

Scope: make an initiative id in a chat result open the **existing** dialog, and
give initiative rows the existing left-hand colour bar.

Reuse targets, all located: the dialog is `components/Modals/BODetails.jsx`,
dispatched through the `ModalContext` registry in `components/Modals/index.jsx`
as `modalType: "BODetails"` with `data: { location: "CELL", bo_id }` — the
canonical call sites are `CellRenderers/CustomListRenderer.jsx` and
`Generator/config/CellFunctios.jsx`. The colour bar is
`CellRenderers/ColorBoxRenderer.jsx`, selected by column type `colorBox` in
`CellRendererFactory.jsx`, rendering the value as a CSS class.

Must resolve first: the `Black → a_bl` mapping that finding 5 shows does not
exist, and where it belongs — a backend that emitted the class form directly
would keep the frontend free of a second colour vocabulary; and the
`.test_datatable_table` scoping of finding 6.

## Before any of it starts

The frontend working tree is dirty: 13 modified files and 2 untracked
(`HistoryMenu.jsx`, `chatHistory.js`) from the previous phase's fix wave, whose
ledger records a final review with 1 Critical and 3 Important findings and a fix
wave dispatched. That work should be settled and committed before new work lands
on top of it.

Two pre-existing failures are known and are **not** ours to fix: `src/App.test.js`
fails because `react-secure-storage` needs `canvas` in jsdom, and
`react-scripts build` exits 1 on eslint debt across ~129 unrelated files. The
frontend is built with `npm run dev` (webpack), never `react-scripts build` —
`build/` is the live Apache web root.
