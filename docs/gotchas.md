# Traps in this project

Things that have bitten us more than once. Read this before changing anything.
Plain language on purpose.

The work spans three folders:

| Short name | Path | What it is |
|---|---|---|
| **Python** | `~/Desktop/Python/wren-poc` | The spec. Pipeline, prompts, metadata. |
| **Drupal** | `c:\xampp\htdocs\dev-arvind-retail-chatbot` | The live backend. A port of the Python. |
| **Frontend** | `c:\xampp\htdocs\WCMS%20-%20Frontend%20-%20Arvind%20Retail` | The React chat page. |

---

## 1. The two repos must stay in step

Python is the source of truth. The Drupal module is a copy of it.

**Five files must be byte-for-byte identical in both:**

```
metadata/business_rules.yaml
metadata/schema_description.yaml
metadata/question_sql_pairs.yaml
metadata/column_hierarchy.yaml
metadata/entity_gazetteer.yaml
```

Rule: edit in **Python first**, then copy across with a plain file copy.

**The md5-of-the-file check no longer passes, and that is fine.** As of
23 September 2026 three of the five differ — Python holds CRLF,
Drupal holds LF:

| file | Python | Drupal |
|---|---|---|
| `business_rules.yaml` | CRLF | LF |
| `question_sql_pairs.yaml` | CRLF | LF |
| `schema_description.yaml` | CRLF | LF |
| `column_hierarchy.yaml` | CRLF | CRLF |
| `entity_gazetteer.yaml` | CRLF | CRLF |

The **content** is identical, which is what matters: both sides parse the YAML
and build the prompt from the result, so the line endings never reach it.
Parity holds and the built-prompt md5 matches on both sides.

So do not chase a file md5 mismatch. **The check that means something is the
prompt md5 printed by `tests/parity/check.php`**, which compares what the
model is actually sent. Compare content, not bytes:

```python
import yaml
yaml.safe_load(open(a).read()) == yaml.safe_load(open(b).read())   # this is the test
```

Still copy the file rather than retyping the change: a second hand-edit is how
the two drift in ways parity *will* catch, loudly, at the worst moment.

**As of 6 October 2026 `column_hierarchy.yaml` content differs.** Drupal
holds the 25 September "Refactor column hierarchy" commit (`65967c3a2`) and
Python does not. That one drift is behind parity's four failures (explore,
explore with a result, display order, hidden columns) and the failing
`test_the_two_copies_of_the_hierarchy_are_byte_identical`. Both were waved
off as "the known drift" for days, and the drift was hiding a real bug (§8,
the YAML slip). A failure you have a story for is still a failure.

Good news: Python turns CRLF into LF when it compiles a `.py` file, so the line
endings of `prompts.py` do **not** change the built prompt. Only the YAML files
and the PHP files matter.

---

## 2. After any prompt or metadata change, re-run the parity check

Every edit to a prompt or to those five YAML files changes the built system
prompt, which is compared byte-for-byte.

Run `generate_expected.py` **from the Python project root**, not from the
module folder — it imports the Python project and puts its own directory on
the path, not the working one.

```bash
python <drupal-module>/tests/parity/generate_expected.py <tmpdir>
php    <drupal-module>/tests/parity/check.php <tmpdir>      # want: PARITY HOLDS
php    <drupal-module>/tests/context/check.php              # 88 cases
php    <drupal-module>/tests/context/adversarial.php        # 113 cases
php    <drupal-module>/tests/outcome/check.php              # 11 cases
php    <drupal-module>/tests/provider/check.php             # 47 cases
```

Counts as of 23 September 2026. The parity run also covers the streaming
scanner — 8,333 partial replies, built by cutting the 1,392 real ones off
before the key, inside the value, one byte short of the close, and at it.
Whole replies agree trivially; the cuts are what tests it.

If the prompt md5 differs between the two sides, **the prompt text differs** —
usually because a change was made in `claude/prompts.py` but not in the matching
spot in `PromptBuilder.php`. Remember `CONTEXT_GUIDANCE` lives in
`pipeline/context.py` on the Python side but in `PromptBuilder.php` on the PHP
side — easy to update one and forget the other.

**What parity does NOT cover:** `TurnRunner`, `ChatRuntime`, `ConversationStore`,
`Redactor`, `Links`, and the REST endpoints. Changing those cannot break parity,
which also means parity will not catch a mistake in them.

**To prove a refactor changed nothing, run old and new side by side.** What
worked on 24 September 2026:

- **Comment-only edits:** tokenise both versions with `token_get_all()`, drop
  `T_COMMENT`/`T_WHITESPACE` (keep `@RestResource(...)`), and compare. Equal
  tokens means only comments moved; strings and the prompt heredocs included.
- **Code edits:** `git archive <old-commit>` the module into a temp folder, then
  run both copies through the same script: the 396 conversations in the parity
  folder's `context.json`, real `TurnRunner`/`ChatRuntime`, the real read-only
  database, only the model scripted. Compare every turn result and response.
  Strip timings and replace the random 12-hex chip token before comparing.
- **Plant a deliberate change once** to prove the comparison can fail. The first
  plant sat on a path the inputs never reached and "passed" — a check that
  cannot fail proves nothing.

---

## 3. Drupal: clearing the cache is harder than it looks

Change a service constructor or `services.yml` and **every request fails** until
the container is rebuilt. The error names the constructor, so it reads like a
code bug when it is really a stale cache.

- `drush status`, `drush php:eval` and most commands are **broken** here (the
  `devel` module needs a `FormatterTrait` this Drush version lacks).
- `drush -l local-arvind-retail-chatbot.wcms.cloud cr` **does** run.
- **But `drush cr` on its own may not be enough.** Drush and Apache keep
  *separate* container cache rows, because the cache key contains the site path
  and they spell the slash differently (`C:/xampp` vs `C:\xampp`). Clearing one
  leaves the other stale.

What reliably works — truncate the cache tables directly (all derived data,
Drupal rebuilds them):

```
vf_cache_container, vf_cache_discovery, vf_cache_bootstrap,
vf_cache_config, vf_cache_default, vf_cache_data
```

Database details are in `<drupal>/.env` (Postgres, table prefix `vf_`).

**Quick check that it worked:**

```bash
curl -k -s -o /dev/null -w "%{http_code}\n" \
  "https://local-arvind-retail-chatbot.wcms.cloud/api/sql-chat/health?_format=json"
```

`403` with a permission message = container is fine. `500` = still broken.

The same truncate works from a script that requires `scripts/bootstrap.php`:
`\Drupal::database()->truncate('cache_container')->execute();` and so on. Use
the bare names — Drupal adds the `vf_` prefix itself.

**Testing as a signed-in user without a browser:** in a bootstrap script,
`\Drupal::service('account_switcher')->switchTo($user)`, use a sentinel
`session_id`, and clean up only that session: delete its `sql_chat` rows and
call the store's `reset($sessionId)`. **Never** `keyValueExpirable(...)->deleteAll()`
— that wipes every user's working context on the live site.

---

## 3b. Renaming a page = two changes that must ship together

A page's **URL** lives in the React route table
(`src/routing/Routs.js`). Its **label** is a row in the Drupal database
(`menu_link_content`, menu `react-menu`) — it is in no file at all.

`PrivateRoute.js` grants access by matching the menu row's stored path against
the browser's path. **If one changes and the other does not, the page shows
"You don't have permission to access this page."** That is not a permissions
bug; it is the two halves disagreeing.

Renaming the menu row is three steps, and skipping the third makes it look like
nothing happened:

1. Update **both** `vf_menu_link_content_data` and
   `vf_menu_link_content_field_revision` (`title`, `link__uri`).
2. **Rebuild the menu link tree.** Drupal keeps a separate `vf_menu_tree` table
   that truncating the cache tables does **not** refresh:
   ```php
   \Drupal::service('plugin.manager.menu.link')->rebuild();
   drupal_flush_all_caches();
   ```
3. Check the API actually changed:
   ```bash
   curl -k -s ".../api/menu_items/react-menu?_format=json" | grep -o 'ask-tms'
   ```

Note `vf_menu_tree.title` is a `bytea` column, so `ILIKE` on it errors. Query by
`id` or go through the entity API instead.

Also: with no redirect, the old URL still returns HTTP 200 — the SPA rewrite
serves `index.html` for everything — but React has no route for it, so the user
lands on Access Denied. A 200 does **not** mean the page works.

---

## 4. Drupal is a multisite

There is **no** `web/sites/default/settings.php`. The real one is:

```
web/sites/site-arvind-retail/settings.php
```

mapped by `BACKEND_SITE_NAME` / `BACKEND_FOLDER_NAME` in `.env`. Looking only in
`sites/default` makes it look like a dead code checkout. It is not.

---

## 5. Frontend build

```bash
npm run dev      # webpack. NOT create-react-app.
```

- **Never** `npm run build` / `react-scripts build`. It produces a CRA-shaped
  build and takes the site down.
- `build/` **is the live web root** that Apache serves. It is gitignored, so git
  will not save you.
- `npm run dev` **empties `build/` first** (`clean: true`), so the site is down
  for the ~45 seconds of the build. Build **once**, after all edits are done.
- To check what actually shipped, **grep the existing bundle** instead of
  rebuilding.
- The chat page is code-split. `SqlChatbotPage` and `ChatResultGrid` land in
  `build/src_pages_SqlChatbotPage_jsx.*.js`, **not** `build/main.*.js`.
- **But the API paths do not.** They are constants in `src/api/Constants.jsx`,
  which the whole app shares, so `api/sql-chat/...` is in `build/main.*.js`.
  Grepping the chat bundle for one finds nothing and looks like a failed build.
- The chat page's helpers and hooks live in `src/components/SqlChatbot/Utils/`,
  the way the rest of the repo does it (`DataTables/AGGrid/Utils/`).

**UI testing:** build it, say whether it looks sound, and let the user test it in
the browser. Do not write UI tests. (Backend tests are still expected.)

**The frontend keeps no test files at all.** The chatbot's eight were deleted
on 24 September 2026 to match the rest of the repo. Check a change with ESLint,
a build, and a one-off script in the scratchpad instead.

**ESLint skips `.jsx` files in a folder unless told otherwise.** Point it at
`src/components/SqlChatbot` and it lints only the `.js` files, then reports
no problems. Pass the extensions explicitly:

```bash
npx eslint --no-eslintrc -c .eslintrc.json \
  --parser-options=ecmaVersion:2022,sourceType:module,ecmaFeatures:{jsx:true} \
  --ext .js,.jsx src/pages/SqlChatbotPage.jsx src/components/SqlChatbot src/api/SqlChatbotApi.jsx
```

Five `react-hooks/exhaustive-deps` warnings in `ChatResultGrid.jsx` are old
ones, not yours.

**Git line endings:** this repo has `core.autocrlf=true`, so the "LF will be
replaced by CRLF" warnings on every `git add` are harmless.

**Commits:** group related work into one meaningful commit, not one per tweak.
`feat/sql-chatbot` was squashed and force-pushed on 24 September 2026 into
three commits: download toast, API client, chatbot page. Commit hashes from
before that date no longer exist on the remote.

**Never force-push `feat/sql-chatbot` again.** Since 25 September the team
merges its ag-grid and filter work into it (about 150 commits by 6 October).
`git fetch` before any squash or rebase: the local branch can look a few
commits ahead while the remote has moved a long way. Squash only what is
unpushed, then merge the remote in.

**Installing dependencies.** Since the team's 24 September lock file:

- **Node 16** (`nvm use 16.20.2`). The lock is v2, which is what npm 7/8 write.
- **`npm ci --legacy-peer-deps`.** Plain `npm ci` stops on an `antd` peer
  conflict (`@formily/antd` wants `<=4.22.8`); the lock already contains it.
- **`@ayushvc/diff-checker` is on the private feed** `tms-npm-packages` on
  `devops.vcgdigital.net`. npm needs a Personal Access Token (Packaging: Read)
  in the *user* `.npmrc`, one `key=value` per line, as `_password=<base64>`.
  Git reaches that server with Windows authentication, so there is no git
  token to reuse, and `vsts-npm-auth` cannot reach a self-hosted server.
- **`npm ci` empties `node_modules` first.** Never switch Node with `nvm` or
  start a second npm in the folder while it runs: on 6 October an `nvm use`
  mid-install killed it and left `node_modules` empty. Stopping the tool call
  that started npm does not stop npm; check `Get-CimInstance Win32_Process
  -Filter "Name='node.exe'"`.
- A missing package after merging the remote shows up as `Module not found`
  in `npm run dev`, not at merge time.
- **A failed build still goes live.** Webpack writes `build/` even when it
  reports an error, so the exit code and the last line are the only warning.
  On 8 October `qrcode.react` (the team's MFA login) was in `package.json` but
  not in `node_modules`; the build "finished", and the login page's chunk
  shipped with a `Cannot find module` inside it. Always read the line
  `compiled with N errors`. To add one missing package without a full
  `npm ci`: `npm pack <name>@<version from the lock>`, compare its sha512 with
  the lock's `integrity`, and untar it into `node_modules/<name>`. Git Bash's
  `tar` reads `C:` as a host name; pass `--force-local`.

**The app's grid styles are scoped, mostly.** `ag-grid-theme.css` styles the
app's tables under `.test_datatable_table` (checkboxes, side bar, Columns
panel). The chat grid does not have that class, so it gets ag-grid's Alpine
defaults instead. The exceptions are unscoped and `!important`, and they do
reach the chat: `.ag-virtual-list-item` is forced to 32px tall, while ag-grid
places list rows `--ag-list-item-height` apart, so the Columns panel's rows
overlapped and were cut off. The chat grid now sets that variable to 28px and
the item height to it. Look for an unscoped rule first when one part of the
chat grid looks wrong.

**Hiding a cell's border hides its column line.** ag-grid draws the line
between columns as the cell's `border-right` (`--ag-cell-horizontal-border`).
Making link cells' borders transparent, to hide the focus box after a click,
removed the Initiative Id column's lines for good. Scope such a rule to
`.ag-cell-focus` / `.ag-cell-range-single-cell` and put `border-right` back.

---

## 6. The read-only database role

- The role is `wren_ro`.
- The live chatbot's credential lives in **Drupal config**, not in `.env`.
  `SQLSTATE 08006` means the credential is wrong, not the model.
- **Never run `create_readonly_role`.** It resets `wren_ro` to whatever is in
  `.env` (breaking the live chatbot) and re-grants the chat-history tables that
  were deliberately revoked.
- The chat-history tables are revoked from `wren_ro` on purpose. Without that,
  generated SQL could read every user's questions.

---

## 7. Editing files from a script — watch for mangled escapes

Writing files through a shell heredoc has repeatedly turned `\b`, `\v` and `\n`
into real control characters (backspace `0x08`, vertical tab `0x0B`, newline).
It silently corrupts regexes and namespaces — e.g. `\vf_sql_chatbot` became a
vertical tab plus `f_sql_chatbot`.

Always check after writing:

```bash
tr -cd '\000-\010\013\014\016-\037' < FILE | wc -c     # must be 0
```

Build backslashes explicitly (`chr(92)`) when a regex is involved, and re-read
the line to confirm.

Python run from a shell heredoc loses one level of backslashes too:
`'\\'` arrives as `'\'`. It bit twice on 24 September 2026. Write such scripts
to a file with an editor instead, and build backslashes with `chr(92)`.

**A literal newline inside a PHP string is a second trap.** `ClaudeCliProvider`
had `strrpos($seen, "<real line break>")`. It works on an LF checkout, but this
repo has `core.autocrlf=true`, so a CRLF checkout silently turns it into `"\r\n"`
and the stream reader stops splitting lines. Always write `"\n"`.

A raw NUL byte is the same trap with a different symptom. One sat inside a
`join("…")` in the frontend's `chatGridLayout.js`. The code ran fine, but git
treated the file as binary: `grep` printed "Binary file matches" and diffs were
unreadable. Write it as the escape `"\u0000"` instead. The check above catches it.

---

## 8. Small things that cost us time

**A business rule with a single-equality `sql_fragment` becomes a UI chip.**
`followup._rule_predicates` turns `table.column = 'value'` into a clickable
filter labelled *"Only the &lt;value&gt; ones"*. So a rule for unassigned tasks would
render *"Only the na ones"*. Rules that are not a filter a person would toggle
should carry **no** `sql_fragment` — put the SQL in the prose instead. Six rules
already do this.

**New constructor / function parameters go LAST.** Both repos have positional
callers (`scripts/run_suite.php`, `bench_latency.py`, the test harnesses).
Inserting a parameter in the middle breaks them silently.

**A new optional parameter must be passed only when wanted.** Adding
`on_delta=None` to every `provider.ask()` call broke 25 tests at once: a
provider written before it existed, and every test double standing in for one,
takes five arguments and rejects a sixth. Build the keyword argument
conditionally (`**({"on_delta": …} if wanted else {})`) rather than always
sending it.

**A setting can be accepted, stored, and silently ignored.**
`CLAUDE_EFFORT_LEVEL=low` could be written in `.env`, loaded into `Settings`
and printed back by any diagnostic — and then two call sites, clamping to
`("medium", "high")` independently, turned it into `medium` before the CLI saw
it. The Drupal port had the same clamp in two more places. All four now share
one list, asked of the CLI rather than assumed:

```
$ claude --effort bogus -p "hi"
Valid values: low, medium, high, xhigh, max.
```

Keep `medium`. Measured on Sonnet, three reps: `low` 2.77s, `medium` 2.50s,
`high` 4.37s. `low` and `medium` are the same thing; only `high` costs
anything.

**`dump_cli_call.php` builds its own argv.** It claims to print the exact call
the chatbot makes, so every flag added to `ClaudeCliProvider` has to be added
there too. It was missing `--include-partial-messages` and was quietly
describing a call nobody made — while being used to prove the Python and
Drupal prompts matched.

**The standalone PHP harnesses have a hand-written class list.** Add any new
`src/Service/*.php` class to the `foreach ([...])` require list in
`tests/context/check.php`, `tests/context/adversarial.php` and
`tests/parity/check.php`, or they fatal with "class not found".

**`check.php` files are in their own namespace.** Reference service classes
fully qualified (`\Drupal\vf_sql_chatbot\Service\Foo`), not bare.

**The IDE's "Undefined type Symfony/Guzzle/Psr" errors in the module are
noise.** It does not index Drupal's `vendor/`. `php -l` and the checks are the
real test.

**A YAML list item where a key belongs parses fine and breaks quietly.** In
`column_hierarchy.yaml` the heading `row_groups:` became `- row_groups`
(25 September). That made `row_groups` and `task_department` two more entries
in `hidden`: the grid stopped showing the department, and grouping by it was
lost. Nothing validates the file. After editing it, ask the real code:
`\Drupal::service('vf_sql_chatbot.column_order')->presentation($columns, [$table])`
returns `order` and `hidden` (positions, not names).

**Never print a credentials file, not even "redacted".** A `sed` that hid
`_password=` missed a hand-written `password=` and put a feed token in the
transcript (6 October). Print key names only: `grep -o '^[^=]*=' FILE`.

**Drupal history:** `Tms-Sql-Chatbot-Testing` was squashed and force-pushed on
24 September 2026 into eight commits (metadata and prompt; SQL reading and
safety; providers; conversation; turn and storage; module and API; tests;
scripts). Commit hashes from before that no longer exist on the remote. The
module keeps its `tests/` — they are the backend's proof and still run — but
the frontend keeps none.

---

## 9. Facts about the data

Checked against the live database, September 2026.

- `tms_task_flat.assigned_user_name = 'NA'` means **not assigned**. 885 of 3354
  tasks. There are **zero NULLs** in that column or in `assigned_user_id`, so
  `IS NULL` never matches anything.
- `NA` is a real user row: `tms_user_flat.user_id = 2`, name `NA`.
- The Drupal uid **is** the TMS user id. No mapping table needed.
- **Most people belong to more than one department.** Only six users have
  exactly one; 40 have two, 11 have three, one has thirteen. Anything about "my
  department" must match *all* of them.
- The department wording mostly lines up between tables, but not perfectly:
  `tms_task_flat.task_department` says "Design Team block" where
  `tms_task_issue_flat.issue_sub_department` says "Design Team".
- The table is `tms_task_flat`, not `task_flat`. The task table has
  `assigned_user_name`, not `user_name` — `user_name` is on the user tables.

---

## 10. Three ways a database name reaches the screen

Fixing one is not fixing the leak. They need different fixes.

| Channel | What it is | What stops it |
|---|---|---|
| The sentence | model prose (`clarification`, `explanation`) | the text guard in `Redactor` |
| The chips | model-written `options` → chip labels | the filter in `Followup` |
| **The results table** | actual query rows | **only refusing to run the query** |

The third one is the one that bites. If the model queries `information_schema`,
the rows *are* the schema, and no text filter can reach them.

**The guard lives in ONE place** — `names_a_database_object()` in
`pipeline/redact.py`, mirrored by `Redactor::namesDatabaseObject()`. It used to
be copied into three files and they drifted. Do not copy it again; import it.

**Do not run the guard over chips built from real data.** Gazetteer and enum
chips come from the database, and a real value like `AR_YD_Suiting` looks
exactly like an identifier. Only model-written options get filtered, and that
filtering happens in `Followup` where the provenance is known — not at the
boundary, which cannot tell where a chip came from.

## 11. Grounding is the gate, not a label

`check_against_schema` / `SchemaChecker` says whether the query only touches
tables **and columns** the schema file describes. That answer now **decides whether the query
runs** (`lean_runner.py`, `TurnRunner.php`).

Two consequences worth knowing:

- **`schema_description.yaml` is now the boundary of what is answerable.** A
  table missing from it is not "wrong answer", it is "refused". Adding a table
  to the database is not enough; it has to be described.
- **An unknown column is refused before the database sees it**, so it never
  reaches the SQL-repair retry, which only runs on a database error. To test
  the repair path, use a grounded query the database rejects, such as
  `SELECT COUNT(*) / 0 AS n FROM tms_task_flat`.
- **A CTE is not a missing table.** `WITH x AS (...) SELECT FROM x` used to be
  reported as ungrounded on both sides, on purpose, because it only affected a
  label. Once the label became the gate, that would have refused every `WITH`
  query — which the prompt explicitly permits. Both sides were corrected; keep
  them corrected.

The system catalogue is blocked separately at the safety gate
(`information_schema`, `pg_catalog`, `pg_*`, and `pg_*()` functions), because
"read only" says nothing about it — a catalogue read is a perfectly valid
SELECT. A catalogue refusal is mapped to SQLSTATE `42703` so the user sees
"ask about tasks, initiatives, users, departments or roles" rather than
"please try rephrasing", which is useless advice for a question that is not
about the work.

---

## 12. Test failures that are NOT yours

As of 23 September 2026, **27 tests fail on a clean checkout** — not the 10
this section used to claim. Do not chase them:

| file | n | why |
|---|---|---|
| `tests/test_database.py` | 16 | Expects the old demo schema — `users`, `tasks`, `tasks_assigned_user_id_fkey`. Those tables are gone; the database holds the `tms_*` ones. |
| `tests/test_metadata.py` | 6 | Still expects rule names like `active_user` and `workflow_owner_join` that the Initiative rename removed. |
| `tests/test_ground_truth.py` | 3 | Expects single-letter categories; the questions file uses descriptive names now. |
| `tests/test_runtime_turn.py` | 1 | Expects `SCHEMA_ERROR`, gets `TOOL_PIPELINE_ERROR`. |
| `tests/test_context.py` | 1 | `test_a_bare_fragment_still_continues_the_block`. |

Every one of them is the **Initiative rename**, not a defect. They were written
against a schema that no longer exists.

**Since 6 October it is 28.** The extra one is
`tests/test_column_order.py::test_the_two_copies_of_the_hierarchy_are_byte_identical`,
and it is **not** harmless: it is the `column_hierarchy.yaml` drift from §1,
which was hiding the §8 YAML slip. It goes away when the two copies are
re-synced.

**Check the count, not the list.** `28 failed, N passed` means you broke
nothing. The way to be sure a failure is yours:

```bash
git stash -u && python -m pytest tests/ -q | tail -2 && git stash pop
```

If the count is the same before and after, it is not yours. This takes thirty
seconds and has settled the question twice.

**Frontend tests:** there are none any more (see §5). Only the untouched
create-react-app `src/App.test.js` is left, and it is not ours.

---

## 13. The question suites drift too, and nothing checks them

The five metadata files are guarded by parity. **The question suites are not.**
They live in both repos, nobody compares them, and on 23 September 2026 two of
the three in Drupal were still asking about `tms_business_object_flat` — a
table the Initiative rename deleted. 183 stale references in
`lean_questions.yaml`, 304 in `expansion_questions.yaml`.

The result: **the suite reported 2% accuracy for a system answering at 94%.**
Every expected answer named a table that does not exist, so every correct
answer was scored wrong. `new_views_questions.yaml`, the one file already in
step, scored 100% throughout.

A benchmark that says 2% for a working system is worse than no benchmark,
because it hides the three failures that are real. Nobody had run the lean
suite on Drupal for exactly this reason: the number looked absurd, so it was
not trusted, so it was not run.

**Check before believing a bad score:**

```bash
grep -c business_object <drupal-module>/tests/*.yaml    # want 0 everywhere
```

Fix by copying from Python, which is the spec, byte for byte.

**Two more things about running the suites:**

- **`run_suite.php` passes no caller identity.** `runTurn` is called without
  one, so *"Show my tasks"* is answered with a clarifying question — correctly,
  since nobody is signed in. Those turns fail in the harness and work in the
  app, where `ChatRuntime` passes `$this->identity->current()`. Two of the
  three remaining lean-suite failures are exactly this and neither is a bug.
- **`--out` is relative to the working directory, not the module.** Run from
  the module folder and the results land in `web/results/...`, not
  `web/modules/custom/vf_sql_chatbot/results/...`. Pass an absolute path, or
  go looking afterwards.
- **`results/**/*.json` is gitignored in the Drupal module**, so a run you want
  to keep needs `git add -f` or a note of the numbers somewhere else.

**Reading the suite files:** conversations are nested under a `turns:` key, not
flagged by a `conversation_id` column. Counting top-level `conversation_id`
returns zero and makes a suite full of follow-ups look like it has none. The
lean suite is 32 entries → 50 turns, of which 18 are follow-ups.

---

## 14. Streaming: the table arrives before the sentences

`/api/sql-chat/ask/stream` sends two Server-Sent Events — `rows` when the
query has run, `answer` when the model has finished writing. `/api/sql-chat/ask`
is untouched and still returns one body.

- **The switch is a checkbox** at `/admin/config/system/sql-chatbot-llm`.
  Turned off, the stream endpoint still answers correctly; it just sends
  nothing until the whole reply is in hand. Honoured in `StreamController`, not
  in the page, so the frontend can never be left waiting for a `rows` event the
  operator has switched off.
- **`answer` always arrives and is the whole response.** A client may ignore
  `rows` entirely. Keep it that way — the moment `answer` stops being complete,
  this becomes a second contract to maintain.
- **`rows` never arrives for a clarification**, which carries no SQL. Anything
  waiting on it will wait forever.
- **The early query applies the grounding check first.** Skipping it would
  reopen §11's leak from behind `TurnRunner`'s back — the rows *are* the
  schema. `tests/test_stream_early_sql.py` guards this.
- **Buffer the SSE reader.** A network chunk can end between the two newlines
  that separate events, inside a JSON string, or mid-character. Getting it
  wrong still works locally, where the whole body arrives at once, and fails on
  a slow connection. Both readers are tested at one byte per chunk.

- **The live site currently has streaming OFF** (`stream_answers: false`, as of
  24 September 2026). So `/api/sql-chat/ask/stream` sends only `answer`, and
  "no `rows` event" is the setting, not a bug. To test the streaming path
  without touching the live setting, override it in-process in a bootstrap
  script: `$GLOBALS['config']['vf_sql_chatbot.settings']['stream_answers'] = TRUE;`
  then `\Drupal::configFactory()->reset('vf_sql_chatbot.settings');`.
- **Capturing the stream in a script:** the emitter calls `ob_flush()`, so the
  events bypass your `ob_start()` and go straight to stdout. Redirect the
  script's output to a file and read that.
- **Permission is enforced by the route** (`_permission` in `routing.yml`),
  before `StreamController` runs. The controller has no check of its own.

**Groq cannot run this system.** The free tier caps the org at 8,000 tokens per
minute and one request is 10,548, so every call is rejected before a model sees
it — not a throttle to wait out. Fitting would mean cutting 24% of the prompt,
which `results/v3_*` already tried at 8–20% accuracy.

---

## 15. Two design rules that are easy to break

**Raw user questions travel only as a safety net under the recap.** An
unbounded window of past messages was tried and removed: when a user says
*"forget the department"*, a window still showing "open tasks for Sales" kept
the model filtering. The main carrier is the **rolling recap**, rewritten from
scratch each turn. Since 22 September (`0c146bb`) the **last 10 questions**
(`RECENT_QUESTIONS`, 160 characters each) travel too, because a summary can
lose a detail like "last week". The old risk is still real: a question that
named a filter the user has since dropped can pull it back, and that is
exactly what the next rule had to fix. The model's own `explanation` is never
carried.

**Dropping a context pill only reaches the model if it is named.** The model
never sees the state, so taking a filter off the state changes nothing it
reads. Left to the question's wording ("Remove the filter ... and show the
same results"), the open-by-default rule put a dropped `task_status = 'open'`
back in 4 of 10 runs (chat 123, 6 October 2026). `dropByRef` now records the
predicate in `droppedFilters`, `renderContext` names it for that one turn, and
`runTurn` clears it: 0 of 10 after. Python has the field and the rendering
(so the two renderers stay identical) but no pills of its own.

**User identity never comes from the browser.** It is read from the Drupal
session on the server. A user id sent from the client can be edited in devtools,
which turns "show my tasks" into "show anyone's tasks". If the user cannot be
identified, ask — never fall back to a default id.

---

## 16. The monthly token limit

Set on `/admin/config/system/sql-chatbot-llm`. **0 means no limit.** One
budget for all users together, counted from 00:00 on the 1st.

- **Counted from `sql_chat_turn.effective_tokens`**, written by `recordTurn()`
  with `TurnOutcome::effectiveTokens()`: prompt minus cache reads, plus a
  tenth of the cache reads, plus the reply. Rows from before 6 October 2026
  were filled in from their metadata by `update_9011`.
- **Checked before anything else** in `ChatRuntime::ask()`: before the state
  loads, so a refused question never enters the recent-questions window and
  costs nothing. Refusal is HTTP 429 with `code: monthly_token_limit`.
- **It can go over by one question.** A question's cost is only known after
  it runs.
- **PHP-only:** the Drupal `repairSql()` adds the retry's tokens to the turn.
  Python's `lean_runner._repair` still drops them. Do not "fix" the two back
  into step.
- **Testing it costs nothing** with a scripted provider: replace
  `vf_sql_chatbot.provider_factory` in the container before asking for the
  runtime, and override the limit in memory with
  `$GLOBALS['config']['vf_sql_chatbot.settings']['monthly_token_limit']`.
  Never save a test limit to config: it would lock out the live site.
- **If the chatbot refuses every question with the token message, check the
  live limit first.** On 6 October the limit was set to 198,000 while the
  month's usage was already past 199,000, so every question was refused. That
  is the feature working, not a bug. Read both numbers with a bootstrap
  script: the config's `monthly_token_limit` and
  `conversation_store->monthlyEffectiveTokens()`.
- **Debug mode shows usage in the top bar** ("NN% used", or "Unlimited" when
  the limit is 0). The pill is read from the latest answer, so it is empty
  until a question has been asked with debug on.

---

## 17. Recent questions and the recap come from the database (PHP only)

Since 6 October 2026 the Drupal module rebuilds the last-10-questions window
and the recap from `sql_chat_turn` on every turn, so an old chat reopened
after an hour still remembers what it was about. The rest of the working state
(filters, previous SQL, goal, pending clarification) is still in the 1-hour
key-value store.

- **Read by `ConversationStore::history()`**, called from `load()`, and applied
  in `ChatRuntime::ask()` through `rememberQuestion()`, so the clip is shared.
  The window uses `metadata.pipeline.normalized_question` when it is set (a
  resumed "4" becomes the whole question) and otherwise the `question` column.
  The recap is the newest row's `metadata.state.rolling_recap`. A row whose
  `state` was shed for size is skipped.
- **Resets cut the window.** The cut is a "forget that"-style phrase in the
  question, or `metadata.pipeline.context_reset`, which is written by both
  `TurnRunner` (the phrase) and `ChatRuntime` (`reset_context`). On a
  `reset_context` turn the history is not applied at all, because the marker
  row is not written yet.
- **`recordTurn()` now runs inside the session lock**, so the next turn cannot
  load before this turn's row exists. A history row that fails to save is
  missing from the next window.
- **`ConversationStore::load()` returns `history` raw.** It does not set it on
  the state. `verify_chat_history.php` relies on `load()` round-tripping the
  key-value state byte for byte.
- **PHP-only.** Python's `lean_runner` still keeps both in its own state. Do
  not "fix" the two back into step. Parity does not cover this.
- **Check:** `php scripts/verify_chat_history.php --write` (section "recent
  questions and recap, from the turns").

---

## 18. Time, size and cache limits (Drupal, since 6 October 2026)

- **LLM call timeout: 500 s** (`claude_timeout_seconds`, all three
  transports). Worked back from PHP's `max_execution_time = 1200`: a turn
  can make two model calls (answer, then SQL repair) and two 100 s queries.
  Raising it further means raising PHP's limit first.
- **Postgres: 100 s** (`statement_timeout_ms = 100000`, applied with `SET
  LOCAL` per query).
- **Session lock lives 1200 s** (`ChatRuntime::LOCK_TTL`). It used to live
  30 s, shorter than a turn, so a long turn could lose its lock halfway.
  The wait for a busy session is still 30 s (`LOCK_WAIT`).
- **Output cap: 4000 tokens** (`LlmProviderInterface::MAX_TOKENS`). The CLI
  gets it as `CLAUDE_CODE_MAX_OUTPUT_TOKENS`. Reasoning tokens count against
  it on OpenAI and Anthropic. Real answers average about 350.
- **Caching.** Anthropic API: the system prompt is cached with `ttl: 1h`. The
  CLI gets `ENABLE_PROMPT_CACHING_1H=1` (and `CLAUDE_CODE_PROMPT_CACHE_TTL=1h`
  for newer CLIs), and any `DISABLE_PROMPT_CACHING*` or
  `FORCE_PROMPT_CACHING_5M` from the server is removed. OpenAI GPT-5.6
  caches implicitly at a fixed 30 min with no parameter needed, and was
  already hitting on about 90% of turns. Its new `prompt_cache_options` is
  documented for the Responses API only, so it is not sent.
- **Python still has 2048 tokens and 180 s.** These are PHP-only.

---

## 19. Initiative attributes: a site module adds to the prompt (Drupal only)

`vf_arvind_retail_chatbot` (under `web/sites/site-arvind-retail/modules/custom/`)
owns the view `tms_initiative_attributes_flat`. Since 8 October 2026:

- **The server cannot write files.** So nothing is generated to disk.
  `\Drupal::service('vf_arvind_retail_chatbot.initiative_attributes')->show();`
  in `/devel/php` shows the labels, the view SQL, and the three YAML blocks,
  each with a Copy button. The view SQL is run by hand; nothing builds it.
- **Columns come from the label tables, not the data.** The active
  `vf_input_file_tagging` rows with `unique_col_name = 'reference_id'`
  (today tags 13, 14, 15, 18), joined to `vf_input_file_display_label` on
  `tag_id`. The label becomes the description; every column is VARCHAR. Keys
  `tms_initiative_flat` already has, and `initiative_id`, are in `SKIP`.
- **Three files are read on every question**, with no cache:
  `metadata/attributes_schema_description.yaml`, `attributes_business_rules.yaml`
  and `attributes_column_hierarchy.yaml`. The module's hooks add each to the
  common file in `vf_sql_chatbot/metadata/`. Empty, they change nothing: the
  built prompt is byte-identical.
- **A YAML mistake in one of them breaks every question**, the same as one in
  a common file. Nothing validates a paste.
- **The column hierarchy never reaches the model**, common or attributes. It
  only orders, hides and groups the results table. Only schema and rules are
  in the prompt.
- **Drupal-only, and parity cannot see it.** The hooks
  (`hook_vf_sql_chatbot_rules_alter`, `hook_vf_sql_chatbot_column_hierarchy_alter`,
  next to the schema one) do not exist in Python, and parity builds `Metadata`
  with no module handler. Do not paste attribute content into the common
  `schema_description.yaml` instead: that file must match Python (§1).
- **Deploying it needs one cache clear**: `services.yml` and the hooks
  changed. Without it every chatbot request fails (§3).
- **`/devel/php` keeps the last code that ran.** After the snippet changed,
  the old one was run again and looked like a bug. Clear the box first.
