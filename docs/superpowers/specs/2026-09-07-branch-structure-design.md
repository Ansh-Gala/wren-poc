# Branch structure: a clean production branch and a development trunk

Date: 2026-09-07
Status: approved, not yet implemented

## The problem

The repository has one working history in which the deployable chatbot and the
apparatus used to measure it are interleaved. There is no branch that could be
deployed as-is: a checkout carries six question suites, nine tracked
result-set directories (forty-three on disk once ignored benchmark output is
counted), two semantic registries, a golden test CSV, sixteen of the eighteen
scripts in `scripts/`, and a retired demo database, none of which the chatbot
needs in order to answer a question through the UI.

The goal is separation, not deletion. Everything currently in the repository
stays reachable; it is redistributed so that one branch holds only what runs.

## What the chatbot actually needs

Determined by loading the runtime and reading back `sys.modules`, not by
reading folder names. `scripts/serve_api.py` is the server that serves the UI,
and its docstring is explicit that there is deliberately no second pipeline:
every request goes through `benchmark.lean_runner.run_turn`.

The local modules the runtime loads:

| Package | Modules |
|---|---|
| `benchmark/` | `context`, `evaluator`, `followup`, `lean_runner`, `lean_suite`, `models`, `normalize`, `safety`, `sql_semantics` |
| `claude/` | `parser`, `prompts` |
| `config/` | `logging`, `settings` |
| `database/` | `connection` |
| `llm_api/` | `factory`, `provider`, `cli_provider` |
| `wren_setup/` | `mcp_config` |

`llm_api/cli_provider` is imported lazily, by `llm_api/factory.py` and by the
`preflight` in `scripts/serve_api.py`, so it does not appear in a bare import
trace but is required on every request. `openai_provider` and `mcp_bridge` are
unreachable while `LLM_PROVIDER=cli`, but they are small and the package is
cohesive, so `llm_api/` is promoted whole rather than split.

Data files read at runtime, all under `metadata/`:
`schema_description.yaml`, `business_rules.yaml`, `question_sql_pairs.yaml`,
`entity_gazetteer.yaml`.

Three findings that rule out a mechanical cleanup:

1. **`benchmark/` is not a testing artifact.** Nine of its modules are the
   production pipeline. Deleting the package to satisfy a naming rule would
   delete the chatbot.
2. **`metadata/question_sql_pairs.yaml` looks like a question dataset but is
   production prompt content.** `claude/prompts.py:224` inlines it into the
   system prompt via `build_lean_system_prompt`.
3. **`database/schema.sql` and `seed.sql` are dead.** They create `users`,
   `workflows` and `tasks`; `metadata/schema_description.yaml` describes six
   real TMS views (`tms_business_object_flat`, `tms_task_flat`,
   `tms_user_flat`, `tms_user_department_flat`, `tms_role_flat`,
   `tms_business_object_attributes_flat`). The runtime has moved to real data
   and the demo schema no longer corresponds to anything it queries.

## Design

### The rename goes on the trunk, not on production

Splitting `benchmark/` into a runtime package (`pipeline/`) and a dev-only
remainder is what makes an honest production branch possible. Doing that
rename *only* on production would make production's tree structurally
different from the trunk's, so every future promotion would have to
re-perform the rename and resolve import conflicts.

Instead the rename happens once on the shared trunk. `pipeline/` becomes the
runtime package on every branch; `benchmark/` retains only `runner.py`,
`classify.py`, `questions.py`, `report.py` and the question suites.

The consequence is the property the whole design rests on: **production is a
pure file-subset of develop.** Promotion deletes paths and never rewrites
code.

### Topology

```
feature/qa-console (13f5489)
        |
        +-- develop        full repository, post-rename; integration trunk
        |
        +-- production     pure subset of develop; deployable
```

`main`, `origin/main`, `update-registry` and
`origin/experiment/session-context-optimization` are not touched. No history
is rewritten and nothing is force-pushed.

`main` is currently 16 commits ahead of `origin/main`, which sits at an older
`1658702`. That divergence is left exactly as it is; reconciling it is a
separate decision.

### Branch naming

Aligned with the conventions already present in the repository
(`feature/qa-console`, `experiment/session-context-optimization`).

| Branch | Base | Purpose |
|---|---|---|
| `production` | generated from `develop` | Deployable chatbot only |
| `develop` | — | Integration trunk; all development lands here |
| `feature/<slug>` | `develop` | Feature work, including its tests |
| `bench/<slug>` | `develop` | Benchmark and evaluation runs, result sets |
| `experiment/<slug>` | `develop` | Spikes; never promoted |
| `data/<slug>` | `develop` | Registry, gazetteer and question-set changes |

Flow: `feature/*` -> `develop` -> promote -> `production`. Nothing merges into
`production` directly.

### Promotion is generated, not merged

`scripts/promote_to_production.py` on `develop` owns the exclusion list and
regenerates `production` from `develop`'s tip. Development files cannot drift
back into production because production is never merged into -- it is rebuilt.

The exclusion list lives in exactly one place, in that script. A new
development artifact is kept off production by adding one path to that list.
The script is itself on the exclusion list: it is a development tool and does
not travel to production.

## Production branch contents

Every entry traces to a verified runtime import or to the UI.

```
pipeline/    __init__ context evaluator followup lean_runner
             lean_suite models normalize safety sql_semantics
claude/      __init__ parser prompts
config/      __init__ logging settings
database/    __init__ connection
llm_api/     __init__ factory provider cli_provider
             openai_provider mcp_bridge
wren_setup/  __init__ mcp_config
metadata/    schema_description business_rules
             question_sql_pairs entity_gazetteer
ui/          index.html styles.css app.js api.js README.md
scripts/     serve_api.py _bootstrap.py
tests/       conftest.py + 12 runtime tests
docs/        architecture.md privacy.md followup-layer.md branching.md
root         README.md .env.example .gitignore requirements.txt
             claude.md pytest.ini
```

### Tests kept on production

A production branch that cannot be verified is a liability, so the tests
covering production modules travel with them:

`test_claude_cli`, `test_context`, `test_evaluator`, `test_followup`,
`test_normalize`, `test_parser`, `test_prompt_grounding`, `test_runtime_turn`,
`test_safety`, `test_settings`, `test_sql_semantics`, `test_token_budget`,
plus `conftest.py` and `pytest.ini`.

### Why `wren_setup/` shrinks to one module

`wren_setup/mcp_config.py` is a hard runtime dependency:
`scripts/serve_api.py` calls `write_mcp_config` in `Runtime.__init__`, and
`llm_api/cli_provider.py` imports `allowed_tools`.

`helpers.py`, `preflight.py` and `build.py` are reachable only from
`scripts/check_environment.py` and `scripts/build_wren.py`. Once those two
scripts are development-only, the three modules have no importer on
production, so they go with them. `serve_api.py` carries its own startup
preflight, so no capability is lost.

## Excluded from production, retained on develop

**Legacy -- dead against the real TMS views**
`database/schema.sql`, `database/seed.sql`, `database/setup.py`,
`scripts/setup_demo.py`, `tests/test_database.py`.

`test_database.py` imports only the runtime `database.connection`, but every
assertion is a seed invariant on the retired demo tables with hardcoded counts
(`users` = 15, `workflows` = 8, `tasks` = 50). It cannot pass against the real
views.

**Benchmarking and evaluation**
`benchmark/` remainder (`runner.py`, `classify.py`, `questions.py`,
`report.py`, `questions.yaml`, `lean_questions.yaml`, `lean_stress.yaml`,
`followup_questions.yaml`, `expansion_questions.yaml`,
`targeted_questions.yaml`); `results/**`; `scripts/run_benchmark.py`,
`run_lean_suite.py`, `run_single.py`, `rescore.py`, `semantic_rescore.py`,
`analyze_followup.py`, `analyze_lean.py`, `verify_ground_truth.py`;
`tests/test_classify.py`, `test_ground_truth.py`, `test_lean_suite.py`,
`test_metadata.py`, `test_report.py`.

**Datasets and source registries**
`TMS_Semantic_Registry_v2 (1)/`,
`TMS_Semantic_Registry_Learning_Material (1)/`,
`TMS_AI_Golden_Challenge_Test_Set (1).csv`.

**Metadata generators**
`scripts/build_gazetteer.py`, `build_schema_description.py`,
`build_expansion_suite.py`, `build_followup_suite.py`,
`build_targeted_suite.py`, `build_wren.py`, `check_environment.py`,
`promote_to_production.py`; `wren_setup/build.py`, `helpers.py`,
`preflight.py`.

Of the eighteen scripts in `scripts/`, production keeps two: `serve_api.py`
and the `_bootstrap.py` it imports.

These generate production assets under `metadata/`, so production cannot
regenerate them. That is intentional: `build_schema_description.py` reads
`TMS_Semantic_Registry_v2 (1)/table_registry.yaml`, and shipping a source
registry to production to make a generator runnable there would defeat the
separation. Regeneration is a development activity; its output is promoted.

**Development documentation**
`docs/followup-layer-report.md`, `docs/scalable_text_to_sql_architecture.md`,
`docs/v2-chat-context.md`, `docs/wren-findings.md`, `docs/superpowers/`.

`docs/data-flow.md` stays on develop too: it is a captured benchmark trace
citing `scripts/run_single.py`, which production does not have.

**Fixtures and stray files**
`ui/mock.js`, `claude/.cph/.prompts.py_*.prob` (editor artifact), `gemini.md`.

## Edits required, beyond moving files

Three files cannot simply be included or excluded.

1. **`ui/index.html`** loads `mock.js` at line 79 via a `<script>` tag, and the
   header carries a "use mock responses" control. Production drops the file, so
   the tag and the control are removed and `app.js` / `api.js` are checked for
   references to the toggle. Production's console then only ever talks to the
   real backend.

2. **`README.md`** is rewritten for production. Eleven of its twenty sections
   describe the benchmark, the retired demo schema, and scripts that production
   does not contain. Production gets a short install / configure / run
   document. The current README stays on develop unchanged.

3. **`docs/branching.md`** is new, on both branches: the table above plus the
   promotion procedure, so the workflow is recorded in the repository rather
   than only in a commit message.

## Known drift, deliberately not fixed

`.env.example` still carries `DATABASE_NAME=wren_demo`, a default from the
retired demo database. It is stale on a production branch. Left unchanged to
keep this change strictly about branch separation; recorded here as a
follow-up.

`docs/architecture.md` and `docs/privacy.md` were reviewed and describe the
current runtime accurately.

## Verification

The rename is the only step that can break working code.

1. `pytest` on `develop` before the rename -- record the result as the
   baseline.
2. `pytest` on `develop` after the rename -- must match the baseline. No
   import of `benchmark.context`, `benchmark.lean_runner`,
   `benchmark.followup`, `benchmark.evaluator`, `benchmark.normalize`,
   `benchmark.safety`, `benchmark.sql_semantics`, `benchmark.models` or
   `benchmark.lean_suite` may remain anywhere in the tree.
3. On `production`: `pytest` green, and `python scripts/serve_api.py` starts,
   serves `GET /health` with `{"ok": true}`, and returns `index.html` at `/`.
4. On `production`: no file references a path that is not on the branch --
   checked by grepping for the excluded directory names.

Baseline caveat: five files are modified in the working tree
(`benchmark/context.py`, `benchmark/lean_runner.py`, `scripts/serve_api.py`,
`tests/test_context.py`, `tests/test_runtime_turn.py`). They are committed to
`feature/qa-console` first, so the baseline is taken from a clean tree.

## Out of scope

- Reconciling `main` with `origin/main`.
- Pushing anything to `origin`. Everything is created locally for review.
- Deleting or rewriting `main`, `update-registry`, or the remote experiment
  branch.
- Any change to pipeline behaviour. This is a reorganisation; the only code
  edits are import paths and the `index.html` mock removal.
