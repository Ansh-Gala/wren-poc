# Where to work

Two long-lived branches. `production` is the application. `develop` is
everything, including the apparatus that measures the application.

```
production     the chatbot, deployable, nothing else
    ^
    | scripts/promote_to_production.py
    |
develop        integration trunk: pipeline + benchmark + datasets + docs
    ^
    | pull request / merge
    |
feature/*  bench/*  experiment/*  data/*
```

## The branches

| Branch | Base | For |
|---|---|---|
| `production` | generated from `develop` | The deployable chatbot. Never committed to by hand. |
| `develop` | — | Integration trunk. Everything lands here first. |
| `feature/<slug>` | `develop` | New behaviour, with the tests for it. |
| `bench/<slug>` | `develop` | Benchmark and evaluation runs, result archives. |
| `experiment/<slug>` | `develop` | Spikes. Expected to be thrown away. |
| `data/<slug>` | `develop` | Registry, gazetteer and question-set changes. |

Use the whole prefix, including the slash. `feature/qa-console`, not
`qa-console`.

## Deciding where something goes

Ask what breaks if the file is absent.

If the chatbot stops answering questions, it belongs on both branches: put it
in `pipeline/`, `claude/`, `config/`, `database/`, `llm_api/`, `metadata/`,
`ui/`, or `scripts/serve_api.py`.

If only a benchmark, an analysis or a regeneration step stops working, it is
development-only: add its path to `EXCLUDE` in
`scripts/promote_to_production.py` in the same commit that adds the file. That
list is the definition of what production is; nothing else needs changing.

The awkward cases are worth stating outright, because each one has been
guessed wrong at least once:

- **`metadata/*.yaml` is production.** It is generated on `develop` from the
  semantic registry, but the generated output is what the model reads at
  runtime. `metadata/question_sql_pairs.yaml` in particular looks like a
  question dataset and is not one -- `claude/prompts.py` inlines it into the
  system prompt.
- **`benchmark/` is not the pipeline.** The nine modules that answer a
  question live in `pipeline/`. `benchmark/` is the scoring apparatus:
  question sets, ground truth, the runner, the report.
- **Tests follow the code they cover.** A test for a `pipeline/` module ships
  to production; a test for `benchmark/` does not.
- **`database/schema.sql` and `seed.sql` are retired**, superseded by the real
  `tms_*` views. They stay on `develop` as history, not as setup.
- **`wren_setup/` and the MCP path are develop-only.** Production runs lean
  (`CLI_LEAN=true`), where `build_command` returns before it touches an MCP
  config or a tool allowlist. `llm_api/cli_provider.py` and
  `scripts/serve_api.py` therefore import `wren_setup` *lazily*, inside the
  non-lean branch. Do not hoist either import to module scope -- that alone
  would put Wren back on production. `llm_api/mcp_bridge.py` and
  `openai_provider.py` go with it.
- **`docs/` is develop-only.** Production carries what a deployer needs in its
  README; everything else is written and reviewed here.
- **`results/` is benchmark output, `logs/` is console turns.** Both are
  gitignored. `scripts/serve_api.py --log` defaults to `logs/console`, so a
  production deployment never creates a `results/` directory.

## Working on a feature

```
git checkout develop
git checkout -b feature/my-thing
# ... work, with tests ...
python -m pytest
git checkout develop
git merge feature/my-thing
```

Nothing goes to `production` at this point. Promotion is a separate, deliberate
step.

## Promoting to production

From a clean `develop`:

```
python scripts/promote_to_production.py --dry-run     # what would ship
python scripts/promote_to_production.py               # do it
```

The script takes `develop`'s committed tree, drops everything in `EXCLUDE`,
lays `promotion/overlay/` over the result, and commits that to `production`.

`production` is regenerated, never merged into. That is the point: a merge
would reintroduce exactly what the branch exists to exclude, every time, and
someone would have to notice and undo it by hand. Regenerating cannot drift.

The consequence is that **you never commit to `production` directly.** A fix
made there is lost by the next promotion. Fix it on `develop` and promote.

### Files that differ rather than being absent

Two files are not the same on both branches, and those live in
`promotion/overlay/`, mirroring their real paths:

| Overlay | Why |
|---|---|
| `README.md` | `develop`'s documents the benchmark; production's documents running the app. |
| `ui/index.html` | Production drops the mock-response toggle along with `ui/mock.js`. |
| `.env.example` | Production has no Wren, no benchmark and no demo database, so it asks for none of their settings. |

Keep that set small. An overlaid file has to be changed in two places forever,
and the second place is easy to forget. Prefer making the shared file tolerate
production's absences: `ui/app.js` and `ui/api.js` check for a missing
`window.MOCK` rather than being overlaid, which is why only the markup differs.

## Checks

`scripts/promote_to_production.py` refuses to run when the working tree is
dirty, when it is not on `develop`, or when any `EXCLUDE` path no longer
exists -- that last one usually means a rename nobody reflected here, which
would quietly start shipping something to production.

## What is not covered here

`main`, `update-registry` and `experiment/session-context-optimization`
predate this scheme. They are left as they are; `main` in particular is 16
commits ahead of `origin/main` and reconciling that is a separate decision.
Nothing in this workflow reads or writes them.
