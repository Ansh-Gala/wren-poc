# Latency: what was done in Python, whether it holds, and how to bring it to Drupal

Two parts. Part 1 reports how the Python pipeline attacked latency and what the
recorded data actually says today. Part 2 is the plan for the Drupal module.

Every number is read out of a file in this repository. Where something is a
claim rather than a measurement, it says so.

**The short version:** the engineering worked — 4.1 seconds of per-turn
overhead was found and removed, and it is still gone. But the system is **not**
under 2 seconds and is currently **slower than it was a week ago**, because the
answers got richer. The regression is in the model leg, not the plumbing.

---

# Part 1 — The report

## 1.1 What was done

The work is one commit, `0fe7659` "Keep the connection and the CLI process
between turns", on `perf/sub-2s-latency`. It is an ancestor of HEAD, so all of
it is live. 12 files, +991 lines. There is no design document — the reasoning
lives in module docstrings, which is where the measurements below come from.

## 1.2 The diagnosis, which is the interesting part

From `llm_api/cli_pool.py:5-9`:

> `claude --version` returns in 0.32s, but `claude -p "reply with one word"` —
> with no system prompt at all — takes 5.7 to 7.7s, and handing it the real 26KB
> system prompt makes it no slower. So the cost is neither the prompt nor the
> inference. It is startup.

That is the whole finding. The obvious suspects — a big prompt, a slow model —
were measured and cleared. The cost was process boot, paid on every question.

The benchmark confirms it. `llm_wall_ms` is what the caller waited; `llm_ms` is
what the model spent:

| | `llm_wall_ms` | `llm_ms` | Overhead |
|---|---|---|---|
| Before (`results/bench_before.json`) | 6363 | 2238 | **4125 ms** |
| After (`results/bench_pool3.json`) | 2204 | 2143 | **61 ms** |

## 1.3 The techniques

**T1 — A warm pool of CLI processes.** `llm_api/cli_pool.py`.
`--input-format stream-json` lets a process sit on stdin already booted, so N
processes are kept parked and one is handed each question.

It is a **replacement pool, not a reuse pool** — each process answers exactly
one question and is killed. That is correctness, not frugality, and it was
measured (`cli_pool.py:29-32`): across four turns in one process
`cache_read_input_tokens` climbed 10,189 → 13,662, and a question repeated as
turn 4 came back faster than as turn 1 because the model had already answered
it. One question per process is what makes this *a latency change and not a
behaviour change* — and `tests/test_cli_pool.py:82-96` enforces it.

**T2 — Sizing tuned by measurement, not preference.** The warm-up curve
(`cli_pool.py:17-22`):

```
warm-up 0.0s -> query 4.54s / 4.71s
warm-up 2.0s -> query 2.22s / 2.58s
warm-up 3.0s -> query 1.87s / 1.87s      <- plateau
warm-up 4.0s -> query 2.16s / 2.39s
```

Size 4 likewise: *"at size 2 the wait showed up as 0.38s on every query; size 3
fixed the average but left a p95 of 3.96s"*. And refill happens **after** the
answer — doing it before *"pushed the CLI's own reported time from ~1.9s to
~2.8s"*.

**T3 — Never lose an answer.** A pool miss returns `None` and falls through to
the old one-shot subprocess (`cli_provider.py:309-322`).

**T4 — Pre-warm at server boot**, so the cost lands in dead time rather than on
the first arrival (`scripts/serve_api.py:287-294`).

**T5 — Per-thread database connections** (`database/connection.py:41-77`):
*"Opening one costs about 110ms... an answer runs one or two statements, so this
was up to 220ms of every turn spent saying hello."*

**T6 — Cache the parsed metadata.** `lru_cache` on the built system prompt
(`claude/prompts.py:256`) — *"three YAML files totalling 32KB re-read and
re-parsed to produce a byte-identical 26KB string, once per question"* — and on
the schema index (`pipeline/sql_semantics.py:452`), *"the second-largest
avoidable cost in a turn after the system prompt"*.

**T7 — Prompt caching.** The prefix is deterministic and a test guards that
(`tests/test_token_budget.py:63-66`). Measured effect: 14,617 of 17,803 prompt
tokens are cache reads — **82%**.

**T8 — Skip the model entirely where possible.** Typo repair and gazetteer
preflight return before `provider.ask` (`lean_runner.py:355-364`, `:467-495`).

**T9 — Effort pinned to `medium`** (`settings.py:40-43`): *"a SELECT does not
need extended reasoning, and this is the one setting that silently multiplies
the bill."*

## 1.4 Is it working? The pool is. The system is not.

**The pool is working, and still is.** Mean `llm_wall_ms − llm_ms` per run:

| Run | Date | Pool overhead |
|---|---|---|
| Before the pool | — | ~4125 ms |
| `lean_pool` | 10 Sep | 108 ms |
| `new_views_python` | 16 Sep | 127 ms |
| `after_meta` | **18 Sep** | **162 ms** |

Four seconds went and stayed gone.

**End-to-end latency has regressed anyway:**

| Run | Date | n | p50 | mean `llm_ms` | mean completion tokens | **Under 2s** |
|---|---|---|---|---|---|---|
| `lean_pool` | 10 Sep | 50 | 2194 ms | 2189 | 90 | 15/50 |
| `new_views_python` | 16 Sep | 46 | **2071 ms** | 2130 | 68 | **21/46** |
| `before_meta` | 18 Sep | 50 | 3761 ms | 3658 | 209 | **0/50** |
| `after_meta` | 18 Sep | 50 | 3611 ms | 3521 | 200 | **0/50** |

The correlation is exact: completion tokens 68 → 200, `llm_ms` 2130 → 3521.
The probe files say the same thing in isolation — `_out/t1.jsonl` is 19 output
tokens in 1632 ms; `_out/live.jsonl` is 217 output tokens in 3951 ms, same
prompt.

**The cause is the richer answer contract.** `explanation`, `goal` and `next`
were added to the model's reply. They are worth having — `after_meta` records
the highest accuracy anywhere in `results/` (100% accuracy, 100% semantic) —
but they cost about 1.4 seconds a turn.

> One note on my own change this session: the `group` key I added to the same
> contract will add to output length too, though only a boolean's worth. It is
> not implicated in the numbers above — those runs finished at 13:06 and the
> prompt was edited at 14:37, and no reply in them contains a `group` key.

## 1.5 Did speed cost accuracy? No — and the reverse was tried and failed.

Paired runs on the same 50-turn suite:

| Run | Latency | Accuracy | Semantic |
|---|---|---|---|
| `lean_initiative_2` (pre-pool) | 6.78 s | 98.0% | 98.0% |
| `lean_pool` (pool on) | **2.34 s** | 98.0% | 98.0% |

Identical accuracy, 65% faster. That is what T1's one-question-per-process rule
was for.

The counter-example is on record too. `results/v3_*` cut the prompt to
868–2,171 tokens to hit a token budget and scored **8%–20% accuracy**. Trimming
the prompt for speed was tried, and abandoned.

## 1.6 Can we hold sub-2s? **No.**

Not today (0/50), and not even at the best recorded point — `new_views_python`
managed 21 of 46 turns, p50 2071 ms. The target is named nowhere except the
branch name and that commit message; no test asserts it.

With overhead at ~160 ms, the remaining time *is* the model. The levers, in the
order I would take them:

1. **Stream the answer.** The only lever that cannot cost accuracy. It does not
   reduce latency; it changes what 3.6s feels like, because first token arrives
   far sooner than last. Given §1.4, most of the wait is now output generation —
   which is exactly the part streaming hides.
2. **Shorten the answer contract.** `explanation` is one or two sentences and
   `next` is up to four questions. Capping their length is the direct lever on
   the 200 completion tokens.
3. **Lower effort** to `low` for simple turns. Currently `medium`.
4. **Trim the uncached 18% of the prompt.** 17,803 tokens is up 33% in eight
   days, and nothing guards it (see defect 3 below).
5. **A faster model** — measured against the suite, not assumed.

## 1.7 Defects found while checking

Real, and worth fixing independently of Drupal:

1. **`CLI_POOL_SIZE` and `CLI_POOL_WARMUP_SECONDS` cannot actually be set.**
   They are absent from `.env` and from the OS-env override list at
   `config/settings.py:107-115`, so `os.environ["CLI_POOL_SIZE"]` is silently
   ignored. They work only by code default — which contradicts `settings.py:3`
   ("Everything tunable lives in .env").
2. **Warm processes leak from every benchmark and suite run.**
   `shutdown_pools()` is called only by `serve_api.py`. `bench_latency.py` and
   `run_lean_suite.py` never call it, so up to 4 `claude` processes survive each
   run.
3. **The token-budget test guards the wrong prompt.** It measures
   `build_system_prompt()` (the MCP path, ~422 tokens). The shipped path is
   `build_lean_system_prompt()` at 17,803 tokens and growing. Its own first line
   — *"Guard the prompt against silent growth"* — is not true of what ships.
4. **Session isolation is half-landed.** `CLAUDE_CONFIG_DIR` defaults to empty,
   and `cli_provider.py:100-105` calls it *"the only thing that stops a plugin
   hook"* — so every warm process still fires the operator's plugin
   `SessionStart` hooks, measured at 3,472 bytes of injected instructions.
5. **`warm_ms` is dead instrumentation** — recorded, never surfaced. Nothing can
   report how warm the process that answered actually was.
6. **A pool miss costs 8s before it even starts.** `cli_pool.py:270` waits
   `warmup + 5.0`, then the caller pays a full cold spawn on top. That is the
   10.9–14.6s p99 in the 18-Sep runs, and no metric marks those turns.
7. **`docs/data-flow.md:151-161` is stale** — it quotes "Wall clock 16–25s" for
   the MCP path on a branch that ships lean-only. Five times worse than reality.

---

# Part 2 — Bringing this to Drupal

## 2.1 The problem

Drupal has the *same* 4.1-second startup cost and **cannot fix it the same way.**

`config/install/vf_sql_chatbot.settings.yml` sets `llm_provider: cli`, and
`src/Llm/ClaudeCliProvider.php` spawns one `claude` per turn via `proc_open` and
throws it away — exactly the pattern Python replaced.

The Python fix does not port. `llm_api/cli_provider.py:251-253`:

> One pool per (command, model, system prompt). Module-level because the whole
> point is to outlive a single request.

A Python service is one long-lived process. Under Apache/PHP-FPM **every request
is a fresh PHP process**, so there is nothing for a pool to live in. Porting
`ClaudePool` class-for-class would build a pool, warm it for 3 seconds, use it
once and destroy it — strictly slower than today.

Same diagnosis, different remedy.

## 2.2 Recommendation

### Step 1 — Measure first, change nothing

`ChatRuntime.php:461-462` already emits `latency_ms` and `stage_ms`. Turn debug
on, ask the four questions from `results/bench_before.json`, record the split.
Confirm the ~4s gap exists here before acting on a number from another machine.
*Verify:* a large gap between the provider call and the model's own time.

### Step 2 — Switch the transport to `api`

`src/Llm/AnthropicApiProvider.php` already exists, is already wired into
`ProviderFactory`, and already sets `cache_control: ['type' => 'ephemeral']` on
the system block. It is one POST through Drupal core's HTTP client — **there is
no process to spawn, so the 4.1 seconds does not exist to be saved.**

This also deletes the operational problems the CLI provider's own docblock
spends thirty lines on: HOME resolution under PHP-FPM, pipe deadlock on Windows,
credentials under a home directory the web server may not have.

The trade-off is real and it is **yours to make, because it is a billing
decision, not a technical one**:

| | CLI | API |
|---|---|---|
| Startup | ~4.1 s/turn | none |
| Auth | local Claude Code install | API key in config |
| Billing | operator's subscription | metered per token |

*Verify:* re-run step 1; the gap collapses to one HTTP round trip.

### Step 3 — Confirm the cache is really being hit

The provider sets `cache_control`, which proves intent, not effect. Read
`cache_read_input_tokens` back. Zero across repeated questions means something
in the prefix varies per request and caching is doing nothing. Python's figure
is 82% — that is the target.
*Verify:* `tokens.cache_read` is a large fraction of `tokens.prompt`.

### Step 4 — Cache the built system prompt (this is T6, and it is a real win)

`Metadata.php:57` parses each YAML file and memoises it **on the object** — which
under PHP-FPM means once per HTTP request, not once per deployment.
`PromptBuilder` has no cache at all. So Drupal rebuilds a 38 KB system prompt
from five YAML files **on every single question**.

Python measured this as the largest avoidable non-model cost in a turn and fixed
it with `lru_cache`. The Drupal equivalent is Drupal's own cache backend, keyed
on the metadata files' mtimes so an edit still invalidates it.
*Verify:* `stage_ms` for prompt assembly drops to ~0 on the second question.

### Step 5 — Persistent database connections (T5)

Python found ~110 ms per connection, up to 220 ms per turn. Under PHP-FPM the
read-only `wren_ro` connection is opened per request. PDO's `ATTR_PERSISTENT`
is the equivalent. Smaller than steps 2 and 4 — do it after them, and measure.

### Step 6 — Stream, if it still feels slow

Per §1.6 this is the only lever that cannot cost accuracy, and per §1.4 most of
the remaining wait is output generation, which is exactly what streaming hides.
It needs frontend work too, so it is its own piece of work.

### Do not port `cli_pool.py`

If the CLI transport must be kept for billing reasons, the only thing that works
under PHP-FPM is a long-lived daemon outside the web server holding the warm
processes, with Drupal talking to it over a socket. That is a new deployable
component to install, supervise and secure — far larger than step 2, and worth
doing only if the API transport is ruled out.

### Not now: the model id

Config sets `anthropic_model: claude-sonnet-4-5`, a previous-generation id; the
current equivalent is `claude-sonnet-5` ($2/$10 per MTok, 1M context). Worth a
deliberate decision — but on its own, with the suite re-run, so a transport
change and a model change are not entangled.

## 2.3 What must not regress

The Python work was a latency change and not a behaviour change, deliberately
(§1.3, T1). The same bar applies. After each step:

- `php tests/parity/check.php <dir>` — must still report **PARITY HOLDS**
- `php tests/context/check.php` (88) and `tests/outcome/check.php` (11)
- Accuracy re-measured on the suite, not assumed

## 2.4 What this will and will not achieve

It will remove ~4 seconds per turn and bring Drupal level with Python.

It will **not** deliver sub-2-second responses, because Python does not either
(§1.6) — and right now Python is at 3.6s with 0 of 50 turns under two seconds.
Getting there needs the §1.6 levers, which trade against cost, answer richness,
or accuracy. That is a separate decision and it should be made with the suite in
hand, not in advance.
