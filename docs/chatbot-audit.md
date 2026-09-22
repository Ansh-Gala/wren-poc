# Chatbot end-to-end audit

Read-only audit of the three codebases. **No code was changed.**

- Drupal module — `dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot` (9,353 lines of PHP services)
- React frontend — `WCMS - Frontend - Arvind Retail/src` (chatbot: ~6,100 lines)
- Python spec — `wren-poc` (~6,000 lines in the live path)

`CONFIRMED` = read in the source. `SUSPECTED` = the code implies it, needs a
runtime check. `ASSUMPTION` = labelled inline.

---

## Executive summary

This is a **well-engineered codebase.** The reasoning behind almost every
decision is written down next to the code, usually with the measurement that
motivated it. The parity harness between Python and Drupal is real and it
works. The write-protection story is genuinely strong — four independent
layers, verified on every run by `scripts/verify_readonly.php`. I could not
find a write path.

The problems are concentrated in one place, and they share one shape: **the
system defends writes thoroughly and reads barely at all.** Everything the
model is allowed to *read* — which tables, which tools, which diagnostics — is
governed by instructions in a prompt rather than by enforcement, and in three
places the enforcement that was designed was then shipped disabled or applied
to only the non-deployed code path.

Three findings deserve action before anything else:

1. The deployed LLM path runs with `--permission-mode bypassPermissions` and
   **no tool deny list**, while the project's own comments state that the deny
   list is what provides safety — and this repository contains a measurement of
   the model reaching for Bash when its intended tool was missing.
2. Generated SQL executes on the read-only check alone. `schema_grounded` is
   computed and discarded. The query role can read ~219 tables in the same
   database Drupal uses.
3. `debug` is a field the browser sets, with no permission of its own, which
   turns off the entire redaction layer.

None of these is exotic. All three have cheap fixes that already exist in the
codebase in some form.

Two more that are not security but will bite: an **undeclared cross-module
dependency on `DATE_FORMAT`** that makes both history endpoints a latent PHP 8
fatal, and the fact that the **`Redactor` — the privacy boundary — has zero
parity coverage and has already drifted on three of five constants.**

On dead code the result is genuinely good: a full enumeration of all 140
public/static methods across the PHP services found **exactly one** unused
(`SqlText::scrub()`). This is not a codebase carrying much rot.

On performance: the pipeline is **one LLM call per question, no retry loop** —
which is the right design and is unusually disciplined. The latency problem is
not architectural; it is 52 KB of YAML re-parsed per request, a 24 KB prompt
re-rendered per request, and a model leg that grew when the answer contract
grew. See `docs/latency-report-and-drupal-plan.md` for the measured detail.

---

## Critical issues

### C1 — Deployed LLM path has permission prompts disabled and no tool deny list

**CONFIRMED** (the flags). **SUSPECTED** (whether tools are actually reachable).

`vf_sql_chatbot/src/Llm/ClaudeCliProvider.php:110-127` and
`wren-poc/llm_api/cli_pool.py:184-185`:

```php
'--tools', '',
'--permission-mode', 'bypassPermissions',
```

There is no `--disallowedTools`. The project states its own rule in the *other*
branch, `llm_api/cli_provider.py:151-155`:

> "bypassPermissions so no run can stall waiting for a prompt that nobody is
> there to answer. **Safety comes from `--disallowedTools` below, which is a
> hard deny** ... The deny list is what actually keeps Bash away from the
> database."

And `wren_setup/mcp_config.py:60-64` records that this is not theoretical:

> "Claude Code reported nothing, and Claude quietly answered the question using
> **Bash** instead — which means it could have run psql and pulled real rows
> back into the conversation."

The deny list `all_disallowed_tools()` is referenced only by the MCP branch
(`cli_provider.py:164`), a check script, and `tests/test_token_budget.py:75-89`
— **a test that guards a list the shipped path never passes.** `CLI_LEAN=true`
in `.env` and Drupal is lean-only, so the deny-listed branch is the one that is
*not* deployed.

Compounding it: `claude_config_dir` defaults to `''`, and the code comment at
`ClaudeCliProvider.php:105-109` calls `CLAUDE_CONFIG_DIR` *"the only thing that
stops a plugin hook"*. The isolation was designed, written, and shipped off.

**Scenario.** An authenticated user asks the model to ignore the JSON contract
and use Bash. Instruction-following is not guaranteed — but it does not need to
be reliable. One success is code execution as the web-server user.

**Impact.** RCE / credential theft, if `--tools ''` does not do what is assumed.

**Fix.** Pass `--disallowedTools` with `BLOCKED_BUILTIN_TOOLS` on the lean path
(it already exists), drop `bypassPermissions`, and set `claude_config_dir`.

**Verify it first, for free:** `tool_call_count` is already recorded per turn
(`TurnRunner.php:333`) and persisted (`ConversationStore.php:538`). Query
`sql_chat_turn.metadata->'pipeline'->>'tool_calls'` for any non-zero value. In
lean mode that number should be structurally zero.

### C2 — Generated SQL executes on the read-only check alone; the query role can read the whole database

**CONFIRMED.**

```php
// TurnRunner.php:394-399  — computed
$r['schema_grounded'] = $check['grounded'];
// TurnRunner.php:473      — and never consulted
if ($r['sql_valid'] && $parsed['sql']) {
```

`sql_valid` is set only by `SafetyGate` (`:406`), which asks four questions:
single statement, starts `SELECT`/`WITH`, contains `SELECT`, no forbidden
keyword. `SELECT * FROM information_schema.columns` satisfies all four.

The codebase documents this mechanism itself, at
`scripts/verify_readonly.php:130-138`:

> "The grants check above proves the role holds SELECT and nothing else. It
> says nothing about WHICH tables it may select from ... TurnRunner executes on
> sql_valid alone; schema_grounded is recorded and never gated on."

It was mitigated for exactly two tables. `vf_sql_chatbot.install:129-137`:

> "The role holds SELECT on ~219 tables because the grant was made schema-wide,
> so without this a question naming these tables would return other people's
> questions and their SQL."

`sql_chat` and `sql_chat_turn` were revoked. The other ~217 were not. The
generated-SQL connection and Drupal's point at the same database.

**Scenario.** A question that steers the model into emitting
`SELECT ... FROM users_field_data` passes every gate and returns rows to an
ag-Grid with a CSV export button. `rows` is on the public whitelist
(`Redactor.php:64`), so **debug mode is not required to exfiltrate.**

**ASSUMPTION** (not verified — verifying means querying the database, which an
audit should not do): Drupal's `config` table is among the ~217. If it is, the
same path reads the active `pg_readonly_password` and `anthropic_api_key`,
which are stored in config rather than in `settings.php`.

**Fix, in order of value:**
1. `REVOKE ALL ON ALL TABLES IN SCHEMA public FROM wren_ro`, then `GRANT SELECT`
   on the `tms_*` views only. This is the real fix — enforcement at the
   database, not in PHP.
2. Make `schema_grounded` a gate, not a metric.
3. Move the two secrets out of config into `$settings`.

### C3 — `debug` is client-controlled and disables redaction

**CONFIRMED.** `ChatRuntime.php:255`:

```php
return !empty($payload['debug']) ? $full : $this->redactor->publicResponse($full);
```

No permission check. `ChatResource.php:80` does the same from a query string.
There is a `debug` key in `config/install/vf_sql_chatbot.settings.yml` — it is
never read. The operator's switch is inert; the browser's is authoritative.

The `Redactor` docblock states its purpose precisely — *"the wrong way round
for a payload carrying SQL and schema names"* — and one client-supplied boolean
bypasses all of it: `generated_sql`, `raw_error` (names the failing table and
column), `raw_output`, `state` including `previous_sql` and every filter
predicate, and raw DB column names.

**Impact.** Full reconnaissance for C2, available to any chatbot user.

**Fix.** A second permission, `view vf sql chatbot diagnostics`, applied
identically in `AskResource`, `ChatResource` and `DebugResource`, ANDed with
the config flag so it can be killed site-wide.

---

## Performance bottlenecks

| Issue | Location | Why it is expensive | Current impact | Optimization |
|---|---|---|---|---|
| 52 KB of YAML parsed per request | `Metadata.php:54-60`; `ColumnOrder.php:55` | `$this->documents` memoises **per object**, and under PHP-FPM the container is rebuilt per request. No `cache.*` backend anywhere in `src/` | 5 files, 52,293 bytes, every question | Drupal cache backend keyed on file mtimes |
| 24 KB system prompt re-rendered per request | `PromptBuilder.php:155-162` | The YAML *parse* is memoised; the *render* is not. No instance cache | Every question. The code itself says the schema is "77% of the prompt and the prompt is paid on every question" | Cache the built string; this is the cheapest win available |
| `vocabulary()` rebuilt per request, then scanned per token | `Metadata.php:154-193`, `Normalizer.php:185-209` | O(tables × columns × enum values) to build, then O(tokens × vocabulary) edit distance | Grows with the schema | Cache the vocabulary with the prompt |
| Non-persistent PDO connect | `QueryRunner.php:184-192` | Fresh TCP + auth handshake per request, *in addition to* Drupal's own connection | Python measured the equivalent at ~110 ms/connection | `PDO::ATTR_PERSISTENT` |
| 4 statements per query | `QueryRunner.php:75-96` | `BEGIN` / `SET TRANSACTION READ ONLY` / `SET LOCAL statement_timeout` / query / `ROLLBACK` | 4 extra round trips per question | Fold the SETs into the connection setup |
| `fetchAll()` with no `LIMIT` injection | `QueryRunner.php:93-95` | Materialises the **entire** result set, then copies it into a second array — peak memory ≈ 2× — and only then slices to 200 | A model-written unbounded `SELECT` is fetched in full before 200 rows are kept | Inject `LIMIT` into the generated SQL, or use an unbuffered cursor |
| Undocumented second DB query | `Initiative.php:196-199` | Runs during response assembly, **after** `finish()` — outside `latency_ms`, outside every `stage_ms` | Fires whenever the answer projects an initiative id without its colour | Fold into the main query, or instrument it |
| `listChats` correlated subquery | `ConversationStore.php:285-290` | One `COUNT(*)` subquery **per returned row**, up to 200 | N+1 pushed into the engine | `LEFT JOIN … GROUP BY`, or a stored counter |
| No index for the chat-list sort | `.install:53-55` vs `ConversationStore.php:289` | `WHERE uid` is indexed; `ORDER BY updated_at DESC, id DESC` is not | Postgres reads all of a user's chats and sorts them | Add `(uid, updated_at DESC)` |
| Identical query twice per turn | `ConversationStore.php:122` and `:361` | `load()` already returns `chat_id`; `ChatRuntime` discards it and `save()` re-runs the same `SELECT` | 1 wasted round trip per question, under the lock | Thread the id through |
| `openChat` selects JSON it will not use | `ConversationStore.php:324` | `SELECT *` pulls `metadata` and `step_timings` for every turn; `ChatResource::present()` only reads them when `?debug` | Wasted bytes on every history open | Name the columns |
| CLI poll granularity | `ClaudeCliProvider.php:183` | `usleep(100000)` between checks | Up to 100 ms of dead latency per turn, even on a fast reply | Shorter interval, or block on the pipe |
| 3 temp-file writes per request | `ClaudeCliProvider.php:85,142,143` | ~24 KB written to disk and read back by the child | Per question, on the CLI path | Disappears entirely on the API transport |

**Not a bottleneck, and worth saying:** exactly **one LLM call per question,
worst case** (`TurnRunner.php:330`), and zero when the gazetteer settles it
first. There is no repair loop — I grepped for one. The deterministic layers
(normalize, classify, followup, safety, column order) cost ~50 ms against a
~2,100 ms model leg. This is a disciplined design and should not be "optimised".

---

## LLM / token optimization

Measured from `results/*/summary.json`, not estimated.

| What | Tokens | Note |
|---|---|---|
| Prompt per question | 17,803 | up from 13,355 on 10 Sep — **+33% in eight days** |
| Of which cache reads | 14,617 (82%) | prompt caching is working |
| Fresh input per question | ~3,186 | this is the part that actually costs |
| Completion | 200 | up from 68 in mid-September |

**Where the tokens go.** `PromptBuilder.php:191` states the schema is 77% of
the prompt. `renderSchema()` emits every table and every column of
`schema_description.yaml` (34 KB) on every question, regardless of what the
question touches.

**The one that matters right now is output, not input.** Latency tracks
completion tokens almost exactly: 68 → 2,130 ms `llm_ms`; 200 → 3,521 ms. The
probes confirm the mechanism in isolation — `_out/t1.jsonl` is 19 output tokens
in 1,632 ms, `_out/live.jsonl` is 217 in 3,951 ms on the same prompt. The
growth came from adding `explanation`, `goal` and `next` to the answer
contract, which also produced the **highest accuracy recorded anywhere** in
`results/` (100%/100% on `after_meta`). That is a trade that was worth making;
it is not a defect.

**What can be reduced without touching accuracy:**

1. **Cache the built prompt** (Drupal). No token change, pure latency.
2. **Cap `explanation` and `next` length** in the prompt. Direct lever on the
   200 completion tokens.
3. **Stream the response.** Does not reduce tokens or latency; changes what
   3.6 s feels like, and per the above most of the wait is now output
   generation — exactly what streaming hides. This is the only lever with no
   accuracy risk at all.

**What NOT to do.** Trimming the schema to hit a token budget was tried:
`results/v3_*` cut the prompt to 868–2,171 tokens and scored **8%–20%
accuracy**. Dynamic per-question schema retrieval is the principled version of
that idea and might work — but it must be measured against the suite before
being believed.

---

## Security findings

Beyond C1–C3 above.

**HIGH — `readOnlyPosture()` checks privilege *type*, never *scope*.**
`QueryRunner.php:152-170` asks "does the role hold anything other than SELECT?"
A role with `SELECT ON ALL TABLES` passes green. `HealthResource` calls itself
a release blocker; make it block on the table list being a subset of the
metadata's tables.

**HIGH — Python system-prompt temp file is predictably named and never deleted.**
`llm_api/cli_provider.py:41-54`. The name is `sha256(prompt)[:16]` in the
world-writable temp dir, guarded only by a TOCTOU-racy `path.exists()`, and the
comment says outright *"Nothing deletes them."* A local user who can read the
repo can pre-create the file with their own instructions and every subsequent
run — including every pooled process — boots with the attacker's system prompt.
The PHP side does this correctly with `tempnam()`. Fix: `mkstemp()`, delete in
`finally`.

**HIGH — `scripts/serve_api.py` has no auth and `Access-Control-Allow-Origin: *`.**
`serve_api.py:387-390, 431-441`. `POST /debug` returns the last 50 unredacted
turns for any client-supplied `session_id`. Defaults to loopback, but `--host`
is an argument. Its docstring calls it a local tool for one person — so the fix
is to enforce that: refuse non-loopback binds, drop the wildcard CORS.

**MEDIUM — Per-session lock TTL is shorter than the work it protects.**
`ChatRuntime.php:28` uses `LOCK_WAIT = 30` as both the wait *and* the lock TTL,
while a turn may legitimately run 180 s (CLI) + 15 s (DB). At t=30 s the lock
expires mid-turn and a second request acquires it — the exact interleaving the
class docblock says the lock exists to prevent. The lock name
(`'vf_sql_chatbot:' . $sessionId`) is also **not uid-scoped**, and the default
session id is `'default'`, so two users who send no session id serialise
against each other. Fix: TTL ≥ the provider timeout, and namespace by uid.

**MEDIUM — No rate limiting on `/ask`.** `AskResource.php:60-78`. Each call
spawns a subprocess with a 180 s timeout. The only throttle is the per-session
lock, and the session id comes from the request body. 200 requests with 200
distinct session ids → 200 processes and 200 Postgres connections. Fix:
Drupal's `flood` service per uid, plus a global spawn semaphore.

**MEDIUM — CSRF token in `localStorage`, alongside a `dangerouslySetInnerHTML`
sink on the same origin.** `SqlChatbotApi.jsx:26`; sink at `ErrorPage.jsx:395`.
The chatbot components themselves are clean — `sqlHighlight.js` returns tokens
rendered as React children, `show.js` returns strings, the grid uses ag-Grid
renderers. Any XSS on this origin yields the CSRF token *and* the stored
transcript.

**MEDIUM — Result rows are written to `localStorage`.**
`chatPersistence.js:18,112-137` — up to 1.5 MB of real TMS rows, unencrypted,
surviving refresh. Mitigating: `removeUserSession()` sweeps it on explicit
logout. Not cleared on session expiry or tab close. **This is mine, from this
session** — `sessionStorage` for rows would keep the feature and lose the risk.

**MEDIUM — `X-Masquerade-As` header recorded as an audit fact.**
`ConversationStore.php:634-637`. Grants nothing, but a user can write a false
"an admin did this" into their own audit record.

**MEDIUM — `SafetyGate` is regex where the reference used a parser.** Python
uses sqlglot (`pipeline/safety.py:72`); PHP rebuilt it from static checks
because "PHP has no Postgres parser". I tried to break it and could not in the
dangerous direction — literals and comments are masked, stacked statements are
refused, nested block comments and dollar-quoting fail *safe*. The residual
risk is that `QueryRunner.php:79` uses `$pdo->query()`, which goes through
`PQexec` and *does* accept multiple statements — the semicolon check is the
only thing preventing that. `prepare()->execute()` would make it impossible at
the driver level.

**LOW — `AskResource.php:69` returns raw exception messages on the 400 path.**
The `\InvalidArgumentException` arm catches both "question is required" (safe)
and `ProviderFactory`'s "unknown llm provider 'x'" (internal config detail).

**LOW — Python writes full turns to disk.** `serve_api.py:296-310` dumps every
`TurnResult` — question, SQL, rows, raw output — to `logs/console/raw/turns.jsonl`.
Gitignored, but plaintext with no rotation. The redacting formatter
(`config/logging.py:24-30`) covers only the two DB passwords and does not touch
the JSONL at all.

### Checked and clean — worth stating

- **No command injection.** `proc_open($argv, …, ['bypass_shell' => TRUE])`
  (`ClaudeCliProvider.php:155`) and `subprocess.Popen(self._argv(), …)`
  (`cli_pool.py:212`) — array form, no shell, on both sides.
- **No IDOR.** Ownership is a `WHERE` clause on every read path, and `uid` comes
  from `currentUser->id()`, never the request. `openChat()` uses two statements
  so turns are fetched by an id already proved to be the caller's.
  `ChatResource` returns 404 not 403, correctly avoiding id confirmation.
- **Conversation state is uid-scoped** (`ConversationStore.php:390`).
- **All five REST resources check the permission** as their first statement.
- **No SQL injection in the module's own queries** — all parameterised. The one
  concatenation (`Initiative.php:196`) is int-cast and safe, though it exists
  only because `runReadonly()` has no parameter facility.
- **No secrets committed.** `git log --all -S` over both repos is clean.
- **Write protection genuinely holds.** Four layers, and
  `verify_readonly.php` tests both refusals and false positives.

---

## Redundant / unnecessary code

Each item lists what I traced before classifying it.

**CONFIRMED UNUSED — `StateRail.jsx` (95 lines) and its CSS (~60 lines).**
Grepped every `.js`/`.jsx` under `src/`: zero importers. I orphaned it in this
session by removing the debug rail. Its CSS classes
(`.sqlchat-rail`, `-filters`, `-mutations`, `-pending`, `-empty-note`) appear
only in that file. `.sqlchat-kv` is shared with `DebugDetails` and must stay.

**CONFIRMED UNUSED — `sqlchat-debug-on` class.** Still set on the root element
(`SqlChatbotPage.jsx:382`) but no CSS rule references it since the rail went.

**CONFIRMED UNUSED — `.sqlchat-ghost`** (`SqlChatbotPage.css:156,168`). Not
present in any JS/JSX, and not built dynamically (I checked for template-string
construction, which is how `.sqlchat-t-*` is built — those *are* used, via
`` `sqlchat-t-${token.kind}` `` at `DebugDetails.jsx:193`).

**CONFIRMED UNUSED — `clearChat()`** exported from `chatPersistence.js:139`,
imported nowhere. Mine, from this session.

**CONFIRMED INERT — the `debug` config key** in
`config/install/vf_sql_chatbot.settings.yml`. Present in config and in the
schema; `grep` finds no read of it in `src/`. See C3.

**CONFIRMED DEAD ON THE DEPLOYED PATH — the tool deny list.**
`all_disallowed_tools()` is called only from the MCP branch
(`cli_provider.py:164`), a check script, and a test. `CLI_LEAN=true` and Drupal
is lean-only, so nothing in production passes it. The *test* still asserts it is
correct, which is worse than no test — it implies coverage that does not exist.

**SUSPECTED LEGACY — the MCP path in `cli_provider.py`** and
`claude/prompts.py::SYSTEM_PROMPT`. Reachable only with `CLI_LEAN=false`,
which no deployment sets and Drupal cannot express. Keeping it is defensible as
a comparison baseline; it should be labelled as such, because today it holds the
safety flags the live path lacks.

**NOT DEAD — `wren-poc/ui/`. I was wrong about this.** It is the live Python QA
console: `serve_api.py:46` sets `UI_DIR = ROOT / "ui"` and `do_GET` at `:413-427`
serves every file from it. It is the reference implementation the React app was
ported from. The real observation is narrower: it is the least-recently-touched
live directory (last commit 10 Sep, vs 16 Sep for `pipeline`/`claude`/`metadata`),
so it predates the Initiative-identifier migration and the links feature and is
drifting from the contract it documents.

**Doc drift, CONFIRMED — `docs/data-flow.md:151-161`** quotes "Wall clock
16–25 s" for the MCP path on a branch that ships lean-only. Five times worse
than reality; anyone reading the docs gets a wrong number.

### Backend sweep — confirmed dead

A full enumeration of all 140 public/static methods across the PHP services,
grepped over all three repos including `tests/parity/`, `tests/context/`,
`tests/outcome/` and `scripts/`, found **exactly one** unused method:

- **`SqlText::scrub()`** (`SqlText.php:157-162`) — zero callers anywhere, and a
  no-op besides: it calls `self::mask()` and returns the result. `SafetyGate`
  calls `mask()` directly. Ported from `safety._strip_noise` and never wired up.

Everything else on the service surface has at least one live caller. That is a
genuinely good result for a 9,353-line codebase.

Also confirmed dead:

- **`TurnRunner::CONTEXT_MODES`** (`:43`) — zero programmatic uses. Python's
  equivalent *is* enforced (`lean_runner.py:757`), and the two have drifted:
  Python is `("none","history","state")`, PHP is `['none','state']`. PHP branches
  only on `'none'`, so `'history'` silently degrades to `'state'`.
- **`Followup::FOLLOWUP_TYPES`** (`:47`) and Python's `followup.py:52` — both
  unused; `lean_suite.py:47` defines the list that is actually validated against.
- **`pipeline.followup.label_for_ref`** (`followup.py:818`) — imported at
  `lean_runner.py:30` and never called. The feature exists only in the Drupal
  port (`Followup::labelForRef` ← `ChatRuntime.php:175`, driven by `option_ref`
  from the React client). `grep option_ref` over wren-poc returns **0 hits** —
  a one-way port that was never reverse-merged.

**SUSPECTED DEAD FEATURE — chat-list pagination.** `ChatsResource.php:85`
returns `total` from `countChats()` and `ConversationStore::listChats` accepts
`offset`, but the only frontend caller is `SqlChatbotPage.jsx:262` →
`listChats({})`, with no arguments and no pager in the UI. A server round trip
per listing for a number nothing displays.

**SUSPECTED — `SYSTEM_PROMPT` / `build_system_prompt()` are production-dead but
test-alive.** Reached only from the non-lean branch and `openai_provider.py`,
both excluded from the production branch — but `tests/test_token_budget.py`
exercises them and is *not* excluded, so it ships and keeps them alive. This is
also the test I noted above as guarding the wrong prompt.

**SUSPECTED DEAD AT RUNTIME — `Comparator` (391 lines).** Reached only from
`TurnRunner.php:482-490`, guarded by `$scoring = $turn['expected_sql'] !== NULL`.
`ChatRuntime::ask()` hardcodes `'expected_sql' => NULL` (`:207`), so only
`scripts/run_suite.php` ever triggers it. It is a benchmark-only service wired
as a **hard constructor dependency of the production `TurnRunner`**, along with
`classifyFailure` and the `result_match`/`match_mode` machinery.

**Dev files that would ship to production.** `promote_to_production.preflight()`
only checks that EXCLUDE entries still exist; it cannot notice a *new* dev file.
Five are missing from the list, and three of those are broken on arrival because
they read from `benchmark/`, which production excludes:
`build_answer_shape_suite.py`, `build_new_views_suite.py` (which also contains a
hardcoded `C:\Users\ansh.gala\...` path at `:84`), `verify_new_views_suite.py`,
`tests/test_active_first.py`, `tests/test_rename_equivalence.py`.

---

## Architecture / structure issues

**God classes.** `Followup.php` 959, `TurnRunner.php` 831, `SqlReader.php` 803,
`ConversationStore.php` 639, `ConversationContext.php` 615. On the Python side
`followup.py` 833, `lean_runner.py` 788, `context.py` 659. `TurnRunner` alone
runs normalization, clarification resume, classification, context rendering,
preflight, the model call, five parsers, schema checking, the safety gate, query
execution, state update, follow-up decisions, and failure classification — and
`runTurn()` does it in **one 446-line method** (`TurnRunner.php:130-576`;
Python's `run_turn` is 414). It is readable because it is commented, not
because it is small. `ChatRuntime` takes 13 constructor arguments and
`TurnRunner` 11; four of `ChatRuntime`'s exist only to build one nested
presentation expression at `:426-437`.

**The same SQL is parsed twice per turn.** `SqlReader::analyze()` during the
schema check, then `SqlReader::state()` during the state update re-masks and
re-parses the same statement (`TurnRunner.php:546-562`).

**Two sources of truth for presentation.** `column_hierarchy.yaml` decides
grouping columns; `chatGridLayout.js:202` decides whether grouping is viable;
the model now decides whether to group at all. Three places, one behaviour. It
works, but a change to grouping needs all three checked.

**Duplicated magic numbers across the boundary.** `MAX_ROWS = 200`
(`QueryRunner.php:39`) versus Python's 20 — flagged as an unresolved divergence
in its own docblock. `DROP_ZONE_HEIGHT` in CSS must match `chatGridLayout.js`,
and a comment says so. The 740→820px measure was a literal repeated in six CSS
rules until this session.

**Inconsistent error semantics.** Lock contention throws `\RuntimeException` →
falls through to the `\Throwable` arm → **500**, when it is a 409 and the user
is told to rephrase a question that was fine. Provider misconfiguration throws
`\InvalidArgumentException` → **400** with the internal message.

**A silent-failure shape in the response contract.** When the model returns no
SQL and no clarification, the user gets a 200 with `error: null`,
`clarification: null`, `explanation: null`, `result: []` — an empty bubble. The
only record is `failure_category`, which the redactor strips
(`TurnRunner.php:534`, `Redactor.php:54`).

---

## Python ↔ Drupal drift

The parity harness is real: it compares the built system prompt byte-for-byte
plus ten logic layers on recorded corpora, and it currently reports **PARITY
HOLDS**. That is a genuine asset.

**What it does not cover — broader than expected.** Grepping `check.php` for
each class name returns **zero hits** for: `TurnRunner` (831 lines),
`ChatRuntime` (469), `ConversationStore` (639), **`Redactor` (205)**, `Links`
(125), `Comparator` (391), and every REST resource and LLM provider.
`ColumnLabels` and `QueryRunner` are `require`d only so other classes can load;
neither is ever asserted. Of `ResponseParser`'s seven readers, only `parseSql`
and `parseClarification` are measured.

**The Redactor gap is the one that matters.** It is the privacy boundary — the
class whose whole job is deciding what may reach a browser — it has **zero**
automated coverage, and it has **already drifted on three of five constants**:

| | Python | Drupal |
|---|---|---|
| `PUBLIC_FIELDS` | 5 entries | 7 — adds `explanation`, `context` |
| `PUBLIC_SUGGESTION_FIELDS` | `{label}` | `['label','ref']` |
| `safeExplanation()` + `EXPLANATION_TELLS` | **does not exist** | `Redactor.php:120-154` |

That last row is a schema-leak guard on model prose that exists on only one
side. (I widened this drift myself this session by adding `grouping` to the PHP
result list — correctly, to match Python, but the harness could not have told
me either way.)

**Metadata files.** All five are byte-identical right now (verified by md5), but
there is **no direct check** — `check.php` md5s the built *prompt*, not the
files. Three of the five are covered indirectly because they feed the prompt;
`column_hierarchy.yaml` and `entity_gazetteer.yaml` are not in the prompt and
are covered only by positional fixtures. That has already failed once:
`tests/parity/README.md:49` records the two copies of `column_hierarchy.yaml`
drifting on one column's position while all ten fixtures still agreed. A
five-line md5 comparison would close it permanently.

**The question suites have silently drifted.** `lean_questions.yaml` differs
between the repos (567 vs 483 lines) and so does `expansion_questions.yaml`. So
`run_suite.php` and `run_lean_suite.py` are measuring different suites, and
their accuracy numbers are not comparable.

**Known divergences:**
- Safety gate: sqlglot AST (Python) vs regex (PHP). Documented and accepted.
- `semantic_match` is permanently `NULL` in PHP — `pipeline/sql_semantics.py`
  (536 lines) was never ported (`TurnRunner.php:510-513`). The field exists on
  both sides and means something on only one.
- `CONTEXT_MODES`: Python enforces `("none","history","state")`; PHP's constant
  is dead and branches only on `'none'`, so `'history'` degrades to `'state'`.
- `MAX_ROWS`: 200 vs 20.
- Redactor field lists: Python allowed `grouping`, Drupal did not, until this
  session. That is exactly the class of drift the harness misses — both sides
  were "correct" and the UI behaved differently in two modes.
- The grouping-nomination parity check was **passing vacuously** until this
  session: no test case used a table that nominates a grouping.

---

## Database / SQL issues

Covered in the performance table. The structural points:

- **Indexes are correct and deliberate** — `(uid, session_id)` unique and
  `(chat_id, sequence_number)` unique, with comments explaining that the latter
  also serves the transcript read. My initial grep for `'indexes'` returned
  nothing and I was wrong; they are declared as `unique keys`. The one real gap
  is the `listChats` sort.
- **No `LIMIT` is ever injected** into generated SQL. The 200-row cap is applied
  in PHP after full materialisation.
- **`statement_timeout` is applied correctly** — `SET LOCAL` inside the
  transaction, `(int)` cast, `ROLLBACK` on both paths.
- **Two connections per request** (Drupal's and `QueryRunner`'s), neither
  persistent.
- Transactions are used only to hold `READ ONLY` and the timeout; there is no
  multi-statement transaction to get wrong.

---

## Frontend issues

- **Duplicate-question key collision — CONFIRMED BUG.** `turnNodes` is keyed by
  question **text** (`SqlChatbotPage.jsx:475`) and `HistoryMenu` uses
  `key={entry.question}` (`:171`). Ask the same question twice — trivially easy,
  the starter chips invite it — and you get duplicate React keys, one node
  entry for two turns, and a ref-cleanup that deletes the wrong one. This is
  also my best remaining candidate for the rail crash reported earlier, though I
  have not reproduced it. Fix: key by `turn.key`, which already exists.
- **`Composer` is memoized but always re-renders** — it receives
  `onSubmit={() => send(input)}`, a fresh closure each render
  (`SqlChatbotPage.jsx`). Harmless in isolation; the memo is simply not doing
  anything.
- **Persistence writes on every `turns` change** — two full `JSON.stringify`
  passes of the whole transcript per question, and `fit()` re-stringifies in a
  loop when trimming. Measured on real data this is ~1 KB/result typical,
  ~27 KB at the 200-row cap — so **a few milliseconds, not a real bottleneck**.
  I am flagging it for completeness, not for action.
- **Result grids do not re-render on keystrokes.** `ChatResultGrid` is memoized
  and its props are referentially stable, so typing in the composer does not
  touch them. I checked this expecting a problem and did not find one.
- **`useStickyScroll` is well built** — passive listener, ref not state, one
  `ResizeObserver`. No issue.

---

## Reliability issues

- **CONFIRMED LATENT FATAL — undeclared cross-module dependency on
  `DATE_FORMAT`.** `ChatResource.php:160,181,183` and `ChatsResource.php:76,78`
  call `date(DATE_FORMAT, …)`. It is not a PHP core constant and is defined
  nowhere in this module — it comes from a **different** module,
  `vf_common/vf_common.module:78`. `vf_sql_chatbot.info.yml` declares only
  `drupal:rest` and `drupal:serialization`. If `vf_common` is ever disabled, or
  the module is installed standalone, both history endpoints throw
  `Error: Undefined constant "DATE_FORMAT"` — fatal on PHP 8. Fix: declare the
  dependency, or define the constant locally.
- **A hardcoded ceiling silently halves a configured timeout.**
  `llm_api/cli_provider.py:280` passes
  `reply_timeout=min(90.0, float(settings.claude_timeout_seconds))` to the pool.
  `CLAUDE_TIMEOUT_SECONDS` is 180 by default and configurable; on the pooled
  path anything above 90 is silently discarded. Whoever raises the setting to
  cope with a slow question will see no effect.
- **The frontend has no request timeout at all.** `SqlChatbotPage.jsx` uses an
  `AbortController` only for unmount and the Stop button. A backend turn is
  bounded at 180 s; the browser is bounded by nothing.
- **A swallowed error with no log.** `ChatRuntime.php:157-160` catches an
  invalid clicked action and discards it silently. Python logs the same case at
  `warning` (`serve_api.py:337`). Same path, different observability.
- **`DebugResource` and `HealthResource` have no error handling.** The other
  three resources each wrap their work in `catch (\Throwable)` → logged +
  generic 500 JSON. `DebugResource.php:65` calls `chatRuntime->debug()` bare, so
  a store failure returns a Drupal error *page* — and the React client's
  `getChatbotDebug` then tries to parse HTML as JSON. `HealthResource` uses a
  fourth, inline error shape (`:48`).
- **Lock TTL < work duration** (above). The highest-value reliability fix.
- **No `set_time_limit`** anywhere in `src/` or `scripts/`. A 180 s provider
  timeout cannot complete under a default 30 s PHP limit — the request dies
  mid-turn with no history row and no response.
- **Hallucinated schema is executed** (C2) — fails at Postgres rather than being
  refused, wasting a round trip and returning a generic error.
- **Parser fallback scrapes prose.** `ResponseParser.php:370-373` deliberately
  returns the last `SELECT`-ish match so a failure is recorded as generated SQL.
  `looksLikeSql()` only checks the leading keyword, so prose containing "SELECT"
  reaches the gate and the database.
- **`parseGroup` accepts only `is_bool`** (`:193-200`) — `{"group":"true"}`
  silently reads FALSE, and grouping is lost with no diagnostic. Mine, from this
  session; the strictness is deliberate but the silence is not ideal.
- **All-or-nothing list parsing** — one malformed entry drops the whole
  `options`/`next` list (`:228-244`). Documented and defensible.
- **Temp-file leak** on two `ClaudeCliProvider` error paths (`:145`, `:159`).
- **No `connect_timeout` on the Anthropic HTTP path** (`AnthropicApiProvider.php:100`)
  — a black-holed TCP connect can consume the full 180 s. No retry, no backoff.

---

## Scalability risks

**Current bottlenecks** (hurting now): the per-request YAML parse and prompt
render; the non-persistent DB connect; `listChats`' correlated subquery; the
per-question CLI process spawn on the Drupal side (~4 s, see the latency
report).

**Future risks** (fine today, structural later):

- **50–100+ tables / thousands of columns.** The whole schema goes into every
  prompt. At 34 KB today it is 77% of the prompt; at 10× it stops fitting
  usefully, and the cached fraction stops helping because the *uncached* delta
  grows too. This is the one architectural decision that will force a change:
  per-question schema retrieval. The `v3_*` results show the naive version of
  that idea scored 8–20%, so it needs real design — the MCP branch's on-demand
  `describe_model` is the sketch of the right answer.
- **Concurrent users.** One subprocess and two DB connections per question,
  no pooling, no flood control. A few dozen concurrent questions will exhaust
  PHP workers or Postgres connections.
- **Large chat histories.** `listChats` sorts unindexed; `openChat` selects
  JSON columns it may not use; the browser keeps the whole transcript with rows
  in `localStorage` against a 5 MB origin quota.
- **Large result sets.** `fetchAll()` with no `LIMIT` is the sharpest edge here —
  it scales with what the model asks for, not with what is displayed.

---

## Observability gaps

What exists is good: `stage_ms` for twelve named stages, `latency_ms`,
`llm_ms`, token counts, `parse_strategy`, `failure_category`, `row_count`, all
persisted per turn in `sql_chat_turn.step_timings` and `.metadata`.

What is missing:

- **Nothing performance-related is ever logged.** All eight logger calls in the
  module are `->error()`. A turn that took 179 s and burned 30k tokens writes
  nothing to `watchdog`.
- **In production none of it reaches the caller** — the telemetry fields are all
  outside `Redactor::PUBLIC_FIELDS`, so with debug off the response carries
  none of it. The durable record is the JSON column, which has no index, so
  "how slow is this?" is a full table scan.
- **`cost_usd` is parsed and discarded** (`ClaudeCliProvider.php:260` vs
  `TurnRunner.php:331-339`) — along with `exit_code`, `stderr`, `num_turns`.
  The one number that gives cost per question is read and thrown away.
- **Untimed:** the second DB query in `Initiative`, the YAML parse, the prompt
  render, `toResponse()`, redaction, all persistence, and the lock wait — the
  last being the worst, because `turn_started` is set *after* it, so a request
  that waited 30 s reports a fast `latency_ms`.
- **No aggregates.** No counters, no histograms, no cache hit/miss rate.

---

## Quick wins

Low risk, meaningful benefit.

1. **Pass `--disallowedTools` on the lean path** and drop `bypassPermissions`.
   The list already exists. First check `tool_calls` in stored turns. (C1)
2. **Narrow the `wren_ro` grants** to the `tms_*` views. One SQL statement,
   removes the entire C2 blast radius.
3. **Gate `debug` on a second permission.** (C3)
4. **Cache the built system prompt** in Drupal's cache backend. Largest
   non-model latency win available.
5. **Raise the lock TTL** above the provider timeout and namespace it by uid.
6. **Set `claude_config_dir`.**
7. **Key the history rail by `turn.key`** instead of question text.
8. **Declare the `vf_common` dependency** (or define `DATE_FORMAT` locally).
   One line; removes a latent fatal on two endpoints.
9. **md5 the five `metadata/*.yaml` files in `check.php`.** Five lines, and it
   retires the only parity failure that has actually bitten you.
10. **Add `try/catch` to `DebugResource` and `HealthResource`**, and replace the
    duplicated generic-error literal at `AskResource.php:76` with
    `Redactor::GENERIC`.
11. **Delete the confirmed-dead set:** `SqlText::scrub()`,
    `TurnRunner::CONTEXT_MODES`, `Followup::FOLLOWUP_TYPES`, the inert `debug:`
    config key, `pipeline.followup.label_for_ref` + its import, `StateRail.jsx`
    and its CSS, `.sqlchat-ghost`, the `sqlchat-debug-on` class, `clearChat()`.
12. **Fix the two temp-file leaks** and Python's predictable prompt file.
13. **Return 409, not 500, on lock contention**, and stop returning raw
    exception messages on the 400 path (both repos — `serve_api.py:456` echoes
    the exception class and message).

## Medium-term improvements

1. **Make `schema_grounded` a gate**, plus a table allowlist in `SafetyGate`.
2. **Switch Drupal to the API transport** — removes ~4 s/turn and the whole
   subprocess attack surface. See the latency report; it is a billing decision.
3. **Inject `LIMIT` into generated SQL** and stop materialising unbounded
   result sets.
4. **Flood control and a spawn semaphore** on `/ask`.
5. **Move secrets out of config** into `settings.php`.
6. **Add a `Redactor` layer to the parity harness** — it is a privacy boundary
   with zero coverage that has already drifted. Then extend to the
   orchestration layer, and reconcile `to_response` ↔ `toResponse`
   field-for-field.
7. **Sync the question suites** between repos, then md5 them too — today the
   two implementations' accuracy figures are not comparable.
8. **Settle `MAX_ROWS` 20 ↔ 200**, since `truncated` currently means different
   things on the two sides and the React grid renders it.
9. **Add the five missing paths to `promote_to_production.EXCLUDE`** — three of
   them are broken on arrival in production.
10. **Move `Comparator` and the scoring path out of the production
    `TurnRunner`**, where they are a hard dependency for code that never runs.
11. **Log slow turns and token counts**; index what you want to query.
12. **Persist result rows to `sessionStorage`**, not `localStorage`.
13. **Stream the answer** — the only latency lever with no accuracy risk.

## Long-term improvements

1. **Per-question schema retrieval.** The single decision that will not survive
   10× the tables. Must be measured against the suite — the naive version
   scored 8–20%.
2. **Split `TurnRunner` and `Followup`** along their existing stage boundaries.
3. **Row-level authorisation.** Today every user with the permission reads
   every row of every `tms_*` view. If the TMS has departmental visibility, the
   chatbot ignores it.
4. **One source of truth for presentation** across the YAML, the backend
   resolver, and the grid.
5. **Decide the fate of the MCP path and `wren-poc/ui/`** — keep them as
   labelled baselines or remove them.
