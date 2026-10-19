# Python vs Drupal chatbot: gap report

Date: 16 October 2026. This was a read-only check. No code, branch or database
was changed.

| | Python (`wren-poc`) | Drupal, the baseline (`vf_sql_chatbot`) |
|---|---|---|
| Branch | `feat/chatbot-charts` | `feat/drupal-11-chatbot-compat` |
| Commit | `17f87cc` | `7392434a4` |
| Working tree | 15 modified, 6 untracked files | clean |

The Python results include its uncommitted work. That work is a partial sync
from Drupal: two rules, the KB unit labels, the "removed filter" text, and one
view migration. If it is thrown away, Python is further behind.

Labels used below:
- **Confirmed**: measured, or seen in a file.
- **Inferred**: follows from the evidence, but not tested.
- **Estimate**: a judgement. The method is stated.

---

## 1. Verdict

**Python is not equal to Drupal today.**

- **The core is the same (Confirmed).** When Python reads Drupal's metadata,
  38 of 39 parity checks pass. The SQL reader, safety gate, schema check,
  context logic, follow-up logic and reply parser all agree with Drupal.
- **The gaps are around the core:** metadata, charts, saved chats, login and
  identity, usage limits, the answer format and the LLM providers.
- **Some gaps are on purpose.** Charts ("Drupal first"), the monthly token
  limit and history rebuilt from the database were built only in Drupal, by
  choice. Parity means building them in Python too.

## 2. Key numbers

| Measure | Result |
|---|---|
| Metadata files with the same content | 1 of 5 (only `entity_gazetteer.yaml`) |
| Parity checks, each side with its own metadata | 29 of 39 pass |
| Parity checks, Python reading Drupal's metadata | 38 of 39 pass. Only the system prompt differs, by Drupal's 43-line chart paragraph |
| Python unit tests | 562 pass, 11 fail (all old, known-stale tests), 53 integration tests not run |
| Drupal test harnesses | 6 of 6 pass (445 cases) |
| Features assessed | 23: 3 Complete, 13 Partial, 6 Missing, 1 Unverified |
| Work items found | 29 app items + 7 database items |
| Time for one developer (Estimate) | 191–317 hours, about 24–40 working days |
| Time for Claude Opus 5.5 (Estimate) | 13–45 hours hands-on, about 1–3 weeks calendar |

## 3. Feature status

Status: **Complete** = same behaviour, verified. **Partial** = some of it
exists. **Missing** = not there. **Unverified** = not enough evidence.

| # | Feature | Status | What differs in Python |
|---|---|---|---|
| 1 | Prompt building | Partial | With the same metadata, the only difference is Drupal's chart paragraph |
| 2 | Metadata and registry | Partial | 1 of 5 files equal. Drupal adds site-module metadata through hooks; Python has no way to do this |
| 3 | Business rules and schema | Partial | 29 rules vs 36. No `vf_report_task_summary`. The attributes table is old: 36 attributes vs 19 in the live view |
| 4 | Question classification | Complete | 506 of 506 turn decisions agree |
| 5 | Standalone questions | Partial | The logic is verified, but the prompt and metadata differ today |
| 6 | Follow-ups and context | Partial | Context logic agrees 100%. Follow-up chips agree 65–71%, and 100% with Drupal's metadata. No way to drop a filter. Chips are chosen from 20 rows |
| 7 | Clarifications | Partial | Same logic. Python ignores `option_ref`, removes the chip `ref`, and never returns `explanation` |
| 8 | State and rolling summary | Partial | Same logic, but kept in memory only. It is lost on restart |
| 9 | SQL repair | Partial | Same trigger and prompt. Python drops the repair's tokens and does not catch repair errors |
| 10 | SQL safety gate | Complete | 1,052 of 1,052 verdicts agree |
| 11 | Schema grounding | Complete | 100% with the same metadata |
| 12 | Query run and errors | Partial | Same read-only run. Timeout is 15 s vs 100 s. Raw error text reaches the user |
| 13 | Answer format and API | Partial | Missing: `explanation`, filter pills, links, chart, "not live" note, download. Sends 20 rows, not 200. No chat endpoints |
| 14 | Saved chats and turns | Missing | Memory plus a log file. No tables |
| 15 | Identity and login | Missing | No login. No signed-in user on live questions. `/debug` is open to anyone |
| 16 | Token use and limit | Missing | No token count per turn, no monthly limit |
| 17 | Logs and diagnostics | Partial | `/health` checks nothing. Step times are not stored |
| 18 | LLM providers and settings | Partial | No Anthropic API provider. No provider error messages. CLI cache and output cap not set |
| 19 | Tests and parity | Partial | 29 of 39 parity checks. 11 stale tests. 6 tests reach the database without the `integration` mark |
| 20 | Charts | Missing | No chart code at all |
| 21 | "Not live" note | Missing | Drupal only |
| 22 | 200-row table and full CSV | Missing | Python sends at most 20 rows and has no export |
| 23 | Same answers with the live model | Unverified | No run on the same day, model, metadata and data for both sides |

## 4. Work items

Hours are developer hours (Estimate, ±50%). Each item has an ID so the plan in
section 8 can refer to it.

### P0: security and correctness (23–36 h)

| ID | Item | Hours |
|---|---|---|
| A1 | Pass the signed-in user to `run_turn`, and add a login | 12–18 |
| A2 | Check that a session belongs to the caller. Protect `/debug`. Replace `CORS *` | 4–6 |
| A3 | Return a general error, not the raw exception (`serve_api.py:483`, `:544`) | 1–2 |
| A4 | Copy the 4 changed metadata files from Drupal. Decide where the attributes metadata lives | 6–10 |

A4 is P0 because the old attributes metadata lists 21 columns that the live
view does not have. Python's schema check lets them through, and then the query
fails in the database (Inferred).

### P1: same features as Drupal (101–161 h)

| ID | Item | Hours |
|---|---|---|
| B1 | Charts: prompt text, reply parsing, chart query, chart checks, tests | 32–48 |
| B2 | Saved chats and turns; rebuild recent questions and the summary from them | 18–30 |
| B3 | Endpoints to list and open chats | 6–10 |
| B4 | Return `explanation` | 1–2 |
| B5 | Filter pills, and dropping a filter (`drop_ref`) | 4–6 |
| B6 | Keep the chip `ref`; accept `option_ref` | 2–4 |
| B7 | Make `links` public; add the task link | 3–5 |
| B8 | Send 200 rows, not 20 | 2–3 |
| B9 | Full CSV download | 6–10 |
| B10 | "Not live" note | 3–5 |
| B11 | Repair: count its tokens, catch its errors, set `repaired_from` only on success | 2–4 |
| B12 | Token count per turn, and the monthly limit | 8–12 |
| B13 | Anthropic API provider; let the server use API providers | 8–12 |
| B14 | Clear messages for provider errors (login, rate limit, size limit, outage) | 3–5 |
| B15 | OpenAI: correct settings for reasoning models (`max_completion_tokens`, no `temperature`) | 3–5 |

### P2: reliable operation (32–56 h)

| ID | Item | Hours |
|---|---|---|
| C1 | CLI: 1-hour prompt cache and a 4,000-token output cap. Remove `ANTHROPIC_API_KEY` in the warm pool too | 2–3 |
| C2 | Same default timeouts as Drupal (100 s query, 500 s model) | 1–2 |
| C3 | A `/health` that checks the database, the provider and the read-only role | 3–5 |
| C4 | A session lock that gives up after a wait | 4–8 |
| C5 | A switch to turn streaming off | 1–2 |
| C6 | Store step times. Stop writing result rows to the log file. Usage badge | 4–8 |
| C7 | Fix or remove the 11 stale tests. Mark the 6 database tests `integration` | 5–8 |
| C8 | Parity checks for error text, links, answer format and charts | 12–20 |

### P3: optional (4–7 h)

| ID | Item | Hours |
|---|---|---|
| D1 | Settings that only `.env` can set today (pool size, benchmark user) | 0.5–1 |
| D2 | Edge cases: `"0.00"` read as zero rows, midnight dates, repair of SQL that does not parse | 3–6 |

## 5. New PostgreSQL database

### What Python already has (Confirmed)

- `DATABASE_*` settings, read from `.env` or the environment.
- psycopg 3, with one reused connection per thread.
- A read-only transaction, a timeout per query, and a rollback after each query.
- Errors are returned as data, not thrown.

So Python can use a new database by changing `.env` only. No code change is
needed for that.

### What the new database must hold (Confirmed)

- **8 objects the chatbot reads:** the 7 `tms_*_flat` views and
  `tms_initiative_attributes_flat`. Drupal also reads the table
  `vf_report_task_summary`.
- **17 tables under them:**
  - `vf_business_object`, `vf_workflow`, `vf_bo_wf_mapping`, `vf_process`, `vf_task`
  - `vf_milestone_tracking`, `vf_milestone_master`
  - `vf_user__field_full_name`, `vf_user__roles`, `vf_role_department_list`
  - `vf_bo_attachment`, `vf_bo_attachment_tagging`, `vf_file_managed`
  - `vf_issue_flow`, `vf_master_data_issue_category`, `vf_issue_comment`
  - `vf_report_task_summary`
- **Build order does not matter.** No view reads another view.
- **Not needed:** `vf_sql_chat`, `vf_sql_chat_turn`, `tms_issue_flat`, and
  `vf_input_file_*`. The last ones are needed only to rebuild the attributes view.

### Problems found (Confirmed)

- The table definitions (DDL) are in neither repo. They must be dumped from
  the current database.
- The function `report_task_summary()`, which fills the summary table, is in
  neither repo.
- Python's `schema.sql` and `seed.sql` are an old demo (`users`, `tasks`,
  `workflows`). They are of no use for this.
- Two Python migrations change views that no file creates. They also grant to
  `wren_sdd`, a role that nothing creates.
- `database/setup.py:65-69` grants SELECT on every table in the schema, now and
  in future. That would also expose chat history. Do not use it as it is.
- Empty tables give empty answers, so the data must be loaded.

### Steps (developer hours, Estimate)

| ID | Step | Hours |
|---|---|---|
| E1 | Dump the DDL for the 17 tables, 8 views and the function; create the database | 6–10 |
| E2 | Load the data. This is one copy; a regular sync costs more | 8–16 |
| E3 | Read-only role: SELECT on the 8 objects only. Keep history in its own schema with its own role | 4–6 |
| E4 | Python: a second connection for history; a connection pool if there are many workers | 4–8 |
| E5 | Rebuild the gazetteer and the value lists from the new data | 3–5 |
| E6 | Tests: compare columns and types with `schema_description`; run the 10 example queries | 8–12 |
| E7 | Write down the settings and the setup | 2–4 |
| | **Total, less about 4 h shared with B2** | **31–57** |

**Needed from you:** a database server, an owner login, network access, the
data source and a refresh plan.

**About the baseline:** Drupal itself cannot use a separate database today
without a code change. Its `QueryRunner` reads the same `DB_*` settings as the
whole site.

## 6. Test results

| Check | Result |
|---|---|
| Parity, each side with its own metadata | 29/39 pass. Fail: system prompt; repair layer 457/463 (2 checks); follow-up "explore" 71% and 65%; column order 11/12 (2 checks); schema check 1019/1023 (2 checks); SQL constructs 117/118 |
| Parity, Python copy with Drupal's metadata | **38/39 pass**. Only the system prompt fails (the chart paragraph) |
| Python unit tests, working tree | 562 pass, 11 fail. Failures: metadata 6, ground truth 3, context 1, hierarchy copy 1 |
| Python unit tests, committed `HEAD` | 548 pass, 17 fail. The 6 extra failures need a database but are not marked `integration` |
| Drupal harnesses | context 149, adversarial 114, outcome 16, provider 47, chart 95, freshness 24. All pass |

**Not run, and why:**
- 53 integration tests: they send queries to the live database, including INSERT and DROP probes.
- Model test suites: they cost tokens.
- `verify_chat_history.php`: it writes rows.
- The live endpoints.

**Disclosure:** the 6 unmarked tests sent constant `SELECT` queries (such as
`SELECT 1`) to the database in `.env`, as the read-only role. Nothing was written.

**Old recorded runs (for context only, not comparable):** on the same 50
`lean_questions` turns, Python scored 90% on 23 September and Drupal 86% on
15 October. The date, metadata, data and setup all differ.

**How to repeat the parity check:**

```
# from wren-poc, with .venv
.venv/Scripts/python <drupal-module>/tests/parity/generate_expected.py <dir>
php <drupal-module>/tests/parity/check.php <dir>
```

## 7. Time estimate

### One developer

**191–317 hours, about 24–40 working days** (Estimate, ±50%). This assumes one
developer who knows both code bases. It includes unit tests and parity updates.
It does not include paid model test runs or review.

| Priority | Hours |
|---|---|
| P0 | 23–36 |
| P1 | 101–161 |
| P2 | 32–56 |
| P3 | 4–7 |
| PostgreSQL | 31–57 |
| **Total** | **191–317** |

### Claude Opus 5.5

**Method.** I measured Claude Opus 5.5 on this session's own work, using the
git reflog and the session log (Confirmed). Then I reduced the speed factor to
stay on the safe side.

| Work done on 16 Oct | Developer estimate, same method | Claude working time | Total time incl. your answers and tests |
|---|---|---|---|
| Full CSV download, 200-row table, then the link, modal and filter changes. Design, code, tests, 3 builds, merge | 14–23 h | 21 min | 78 min |
| This gap analysis: parity runs, test runs, 4 code surveys | 2–3 days (Estimate) | 11 min, plus 4 helper agents running at the same time | 17 min |

On the CSV work, Claude was about 40–70 times faster than the developer
estimate. The remaining work is bigger and less clear, so I use much smaller
factors:

- **10 to 20 times faster** for porting work that has a Drupal reference and a
  parity check. This is most of the items.
- **5 to 10 times faster** for work that needs new design or outside systems:
  login (A1, A2), saved chats (B2, B3), the lock (C4), and the new database (E1–E7).

| Priority | Developer hours | Claude Opus 5.5 hands-on hours |
|---|---|---|
| P0 | 23–36 | 2–6 |
| P1 | 101–161 | 6–20 |
| P2 | 32–56 | 2–6.5 |
| P3 | 4–7 | 0.2–0.7 |
| PostgreSQL | 31–57 | 3–11 |
| **Total** | **191–317** | **13–45** |

**Time that Claude cannot shorten:**
- **Model test runs:** about 20–30 runs of 5–15 minutes each, about 3–5 hours
  in total. For example, one 50-question suite run took 5.8 minutes on
  15 October.
- **Your decisions:** the login method, where saved chats are stored, and
  whether to bring the Drupal-only features into Python.
- **Access:** the new database server, an owner login, the data, and any paid
  API keys. Claude does not spend on paid APIs without your OK.
- **Your browser tests and merge approvals.** On the CSV work, your part was
  57 of the 78 minutes.

**Calendar time:**

| | One developer | Claude Opus 5.5 |
|---|---|---|
| Hands-on time | 191–317 h | 13–45 h |
| Waiting for model test runs | included | 3–5 h |
| Calendar time | 24–40 working days | about 1–3 weeks |

The Claude calendar assumes you answer questions on the same day and that
database access is ready. If reviews take as long, relative to the work, as on
the CSV work (3.7 times Claude's time), the top end is about 4 weeks.

**How reliable this is:** the Claude figure is less certain than the developer
figure. It rests on one measured feature and this analysis, and both were small
and clearly defined.

## 8. Recommended order

1. **Security, P0:** A1, A2, A3. Do not put Python in front of users before this.
2. **Metadata, A4.** After this, parity should be 38/39.
3. **Saved chats, B2 and B3.** These unblock B9, B12 and the history rebuild.
4. **Answer format and the 200-row table, B4–B8.** Then the CSV download, B9.
5. **Providers, B13–B15 and C1–C2.**
6. **Charts, B1.** This is the largest item. It needs B4–B8 first. Finish
   with C8, so that parity reaches 39/39.
7. **New database, E1–E7.** This can run in parallel from step 2. E3 and E2 do
   not depend on the app work.
8. **P2 and P3**, then one same-day run of the same suite on both sides, to
   settle row 23 of the feature table.

## 9. Risks and unknowns

- **What Python is for.** `serve_api.py` says it is a local tool for one
  person. If that is still true, much of P1 may not be needed.
- **Deployment.** The login method and the number of workers are unknown. They
  change A1 and C4.
- **Missing DDL.** The table definitions and the `report_task_summary()`
  function are not in either repo.
- **Data.** The data size and refresh needs are unknown. They change E2.
- **The live Drupal prompt.** It also holds the site module's 19 attribute
  columns. Parity does not measure them.
- **The live Drupal provider.** It was on the API, not the CLI, when last
  checked. That sets the priority of B13–B15.
- **The uncommitted Python work.** If it is discarded, the gap grows.

## 10. Evidence

**Python** (`C:\Users\ansh.gala\Desktop\Python\wren-poc`):
- `scripts/serve_api.py`:
  - `:361-367`: no identity is passed
  - `:426`: `CORS *`
  - `:483`, `:544`: raw errors
  - `:493-494`: `/health`
  - `:515`: `/debug`
- `pipeline/evaluator.py:147`: 20-row cap
- `pipeline/redact.py:44-50`, `:70-72`, `:82`: public fields
- `pipeline/lean_runner.py:476-487`: repair tokens dropped
- `pipeline/safety.py:80`: SQL that does not parse is refused
- `llm_api/openai_provider.py:33`: 2,048-token cap
- `llm_api/cli_pool.py:210-216`: pool environment
- `database/connection.py`: read-only run
- `database/setup.py:65-69`: schema-wide grant
- `database/schema.sql`: demo tables only

**Drupal** (`...\web\modules\custom\vf_sql_chatbot`):
- `src/Service/PromptBuilder.php:80-120`: chart paragraph
- `src/Service/ChatRuntime.php`: identity, limit, pills, 200 rows, "not live" note
- `src/Service/ConversationStore.php` and `vf_sql_chatbot.install`: chat tables
- `src/Service/Redactor.php:48-61`, `:71-104`: provider errors, public fields
- `src/Service/ChartCheck.php`: 527 lines
- `src/Controller/CsvController.php`: CSV download
- `src/Llm/*`: providers
- `sql/views/*.sql`: the 7 views

**Site module:** `web/sites/site-arvind-retail/modules/custom/vf_arvind_retail_chatbot`
(the attributes metadata and view).
