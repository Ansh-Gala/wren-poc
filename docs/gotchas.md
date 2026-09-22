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

Rule: edit in **Python first**, then copy across with a plain file copy, then check:

```bash
md5sum <python>/metadata/X.yaml <drupal>/metadata/X.yaml   # must match
```

**Line endings.** Both copies are currently **CRLF**. Do not "helpfully" convert
to LF. A tool that rewrites the file with different endings breaks the check
even though the words are identical.

Good news: Python turns CRLF into LF when it compiles a `.py` file, so the line
endings of `prompts.py` do **not** change the built prompt. Only the YAML files
and the PHP files matter.

---

## 2. After any prompt or metadata change, re-run the parity check

Every edit to a prompt or to those five YAML files changes the built system
prompt, which is compared byte-for-byte.

```bash
python <drupal-module>/tests/parity/generate_expected.py <tmpdir>
php    <drupal-module>/tests/parity/check.php <tmpdir>      # want: PARITY HOLDS
php    <drupal-module>/tests/context/check.php              # 88 cases
php    <drupal-module>/tests/context/adversarial.php        # 108 cases
php    <drupal-module>/tests/outcome/check.php              # 11 cases
```

If the prompt md5 differs between the two sides, **the prompt text differs** —
usually because a change was made in `claude/prompts.py` but not in the matching
spot in `PromptBuilder.php`. Remember `CONTEXT_GUIDANCE` lives in
`pipeline/context.py` on the Python side but in `PromptBuilder.php` on the PHP
side — easy to update one and forget the other.

**What parity does NOT cover:** `TurnRunner`, `ChatRuntime`, `ConversationStore`,
`Redactor`, `Links`, and the REST endpoints. Changing those cannot break parity,
which also means parity will not catch a mistake in them.

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

**UI testing:** build it, say whether it looks sound, and let the user test it in
the browser. Do not write UI tests. (Backend tests are still expected.)

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

**The standalone PHP harnesses have a hand-written class list.** Add any new
`src/Service/*.php` class to the `foreach ([...])` require list in
`tests/context/check.php`, `tests/context/adversarial.php` and
`tests/parity/check.php`, or they fatal with "class not found".

**`check.php` files are in their own namespace.** Reference service classes
fully qualified (`\Drupal\vf_sql_chatbot\Service\Foo`), not bare.

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
tables the schema file describes. That answer now **decides whether the query
runs** (`lean_runner.py`, `TurnRunner.php`).

Two consequences worth knowing:

- **`schema_description.yaml` is now the boundary of what is answerable.** A
  table missing from it is not "wrong answer", it is "refused". Adding a table
  to the database is not enough; it has to be described.
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

As of September 2026, **10 tests fail on a clean checkout**. Do not chase them:

- `tests/test_metadata.py` — 6 failures. Still expects rule names like
  `active_user` and `workflow_owner_join` that the Initiative rename removed.
- `tests/test_ground_truth.py` — 3 failures. Expects single-letter categories;
  the questions file uses descriptive names now.
- `tests/test_context.py::test_a_bare_fragment_still_continues_the_block` — 1.

Everything else should pass. If you are unsure whether a failure is yours,
revert just your change and run that one test again.

---

## 13. Two design rules that are easy to break

**Never put raw user questions into the prompt as history.** It was tried and
removed. When a user says *"forget the department"*, that counts as an ordinary
follow-up — so a window of past messages would still be showing "open tasks for
Sales" on the very turn that removed the filter, and the model keeps filtering.
The model's own `explanation` is no safer; it is specified to read "the open
tasks for the Sales department". Two tests guard this. Carry a **rolling
summary** instead, which is rewritten from scratch each turn.

**User identity never comes from the browser.** It is read from the Drupal
session on the server. A user id sent from the client can be edited in devtools,
which turns "show my tasks" into "show anyone's tasks". If the user cannot be
identified, ask — never fall back to a default id.
