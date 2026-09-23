# Sub-2-second answers: find the real bottleneck, then remove it

## The problem

A turn takes 8.1 s (Luna) to 12.4 s (Claude CLI) end to end. Of that, 99% is the
`llm` stage. Everything else in the pipeline — normalize, classify, context,
preflight, parse, schema_check, gate, state_update, followup — sums to under
25 ms. The database is 160–390 ms.

`docs/latency-report-and-drupal-plan.md` already removed 4.1 s of process
startup and that saving still holds. What is left is the model call itself, and
it is one HTTP request with no tool loop, so there are no round trips to delete.

## What the recorded data says

Output length and `llm_ms` move together, on a fixed prompt:

| output tokens | llm_ms | source |
|---|---|---|
| 19 | 1632 | `_out/t1.jsonl` (cited in the latency report) |
| 68 | 2130 | `results/new_views_python` |
| 200 | 3521 | `results/after_meta` |
| 217 | 3951 | `_out/live.jsonl` |

The Luna run in question is ~7.7 s. At the ~200 output tokens the current answer
contract produces, that is roughly 26 tokens per second.

Input is not implicated. `build_lean_system_prompt()` is 42,912 chars (~10.7k
tokens) but 82% of it is served from the provider's prefix cache, so prefill
costs a few hundred ms. Trimming it has been tried: `results/v3_*` cut the
prompt to 868–2,171 tokens and scored 8%–20% accuracy. The prompt stays.

## The open question

Two readings fit an 8-second call, and they lead to opposite fixes:

1. **Generation-bound** — first token arrives quickly, the remaining seconds are
   the model typing ~200 tokens. Fix: take everything but the SQL off the
   critical path, or generate faster.
2. **TTFT-bound** — seconds of dead air before the first token, then a fast
   burst. Fix: only a different provider helps; output length is irrelevant.

`results/new_views_python` argues for (1) on the Claude path: p50 is 2071 ms,
which is impossible if the first token takes 7 s. Luna is unmeasured and may
genuinely differ — a reasoning model or a queued proxy can spend that long
before emitting anything.

Nobody has measured it. That is the first deliverable.

## Piece 1 — `scripts/probe_ttft.py`

A streaming probe against any OpenAI-compatible endpoint, using the real
`build_lean_system_prompt()` and `build_user_prompt(..., lean=True)` so it
measures what production pays rather than a synthetic prompt.

Per run it records four wall-clock marks from a single `stream: true` request:

| field | meaning |
|---|---|
| `ttft_ms` | the first content chunk arrives |
| `sql_done_ms` | the `"sql"` value has fully arrived — the earliest the DB query could start |
| `total_ms` | the last chunk arrives |
| `output_tokens` | from the final usage chunk |

Derived: tokens per second, and `total_ms - sql_done_ms`, which is the time
spent generating `explanation`, `goal`, `recap`, `next` and `group` — content
the user is not waiting for.

`sql_done_ms` is detected by scanning the accumulated text for the close of the
`sql` string value: the first unescaped `"` after `"sql"` `:` `"`. The contract
in `claude/prompts.py` puts `sql` first in the object, so this mark is always
reachable and always early.

Interface: `--base-url`, `--model`, `--api-key-env`, `--question`, `--reps`,
`--out`. The first rep is reported separately as cold. Output goes to
`results/<YYYY-MM-DD>/<name>/`.

Nothing in the pipeline is modified. The script imports the prompt builders and
otherwise stands alone.

The Claude CLI path is out of scope. `scripts/bench_latency.py` already reports
its wall time, and its streaming uses `--output-format stream-json`, a different
mechanism that would need its own parser.

## Piece 2 — Groq

### 2a. List the models

`GET https://api.groq.com/openai/v1/models` with the key, printed as id plus
context window. A hardcoded name is a name that goes stale: `.env` carries a
commented `OPENAI_MODEL = qwen-2.5-32b   # decommissioned by Groq` as proof.

### 2b. A lean branch for `OpenAIProvider`

`llm_api/openai_provider.py` has only the MCP path: it always builds
`build_system_prompt()`, opens `WrenMCPBridge`, and runs an agent loop of up to
8 turns. Only `CLILocalProvider` honours `settings.cli_lean`.

The Drupal port is already lean-shaped — `src/Llm/OpenAiCompatibleProvider.php`
sends one POST with the full schema in the system prompt and no tools. So
running the lean suite against Groq in Python today would measure a shape that
does not ship.

The change: when `settings.cli_lean` is set, skip the bridge and send one
request with `build_lean_system_prompt()` and `build_user_prompt(..., lean=True)`
and no `tools`. The MCP branch is untouched, so nothing working today changes.
This brings Python level with the PHP provider rather than adding a new idea.

### 2c. Run the suite

The 50-turn lean suite against the chosen Groq model, into
`results/<YYYY-MM-DD>/groq_<model>/`. The comparison baseline is
`results/after2_lean`: **100% accuracy, 8.12 s mean, 79.7 mean completion
tokens, 10,929 mean prompt tokens.**

Accuracy is the gate. A Groq model that answers in 0.5 s and scores below the
current 100% is rejected; speed does not buy correctness back.

## Success criteria

1. `probe_ttft.py` returns `ttft_ms` and `sql_done_ms` for Luna, and the answer
   distinguishes generation-bound from TTFT-bound. Either outcome is a result.
2. `OpenAIProvider` in lean mode produces a request body that matches what
   `OpenAiCompatibleProvider.php` sends — same system prompt, same user prompt,
   one call, no tools.
3. The Groq suite run reports accuracy no lower than `after2_lean`'s 100% and
   mean latency under 2 s. If accuracy holds but latency does not, or the
   reverse, that is reported as-is rather than tuned toward the target.

## Conventions

Every run in this work writes to `results/<YYYY-MM-DD>/<run-name>/`. The
existing flat directories under `results/` stay where they are: the latency
report cites them by name.

## Out of scope

- Streaming in the shipping pipeline. It is the fix for reading (1), but it is
  worth building only once the probe says (1) is the reading, and it needs
  frontend work in Drupal that is its own piece.
- Shortening the answer contract. Ruled out by the user.
- Trimming the system prompt. Already tried and abandoned at 8%–20% accuracy.
- The Drupal side of any of this, until the Python measurements land.
