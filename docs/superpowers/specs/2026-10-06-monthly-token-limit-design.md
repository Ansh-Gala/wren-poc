# Monthly token limit — design

Date: 6 October 2026
Repos touched: **Drupal** (`vf_sql_chatbot` module) and **Frontend** (React chat page).
No Python change: the setting only exists in Drupal, and `ChatRuntime`,
`StreamController` and `TurnRunner` are outside the parity harness.

## Goal

Stop the SQL chatbot from spending more than a set number of tokens per
calendar month. One limit, one shared budget for **all users together**.
When the budget is used up, nobody can ask until the 1st of next month.

## Decisions already made

- **Shared budget.** Every user's turns count against the one limit.
- **Effective tokens**, worked out the way the debug panel already does
  (`DebugDetails.jsx`):
  `effective = (prompt − cache_read) + cache_read × 0.1 + completion`
- **Store effective tokens per turn.** A new column
  `sql_chat_turn.effective_tokens`, written with every turn, so the monthly
  total is a plain `SUM`. Rows from before the column existed are filled in
  once from the token counts already in `sql_chat_turn.metadata`.
- **The SQL-repair retry counts.** Today `TurnRunner::repairSql()` makes a
  second model call and throws its token counts away. They will be added to
  the turn's totals.
- **Check before anything else.** The limit is checked at the start of
  `ChatRuntime::ask()`, before the chat state is loaded, before the last-10
  question window is touched, and before any model call.

## 1. The setting

- New field **"Monthly token limit"** on `/admin/config/system/sql-chatbot-llm`
  (`LlmSettingsForm`). A whole number, minimum 0.
- Saved as `monthly_token_limit` in `vf_sql_chatbot.settings` (Drupal config,
  stored in the database, so it survives reloads and restarts).
- Added to `config/schema/vf_sql_chatbot.schema.yml` (type `integer`) and to
  `config/install/vf_sql_chatbot.settings.yml` with default `0`.
- **0 or missing means no limit.** The live site has no value yet, so
  deploying this changes nothing until an admin types a number.

## 2. Storing and counting usage

### The column

- New column on `sql_chat_turn`:
  `effective_tokens` — `int`, unsigned, not null, default 0.
- Added to `vf_sql_chatbot_schema()` in `vf_sql_chatbot.install`, so a fresh
  install gets it.
- **`recordTurn()` writes it** for every turn, from the turn result `$r`
  (which by then includes the repair retry, see §3):

  ```text
  effective_tokens = round((prompt - cache_read) + cache_read * 0.1 + completion)
  ```

  A turn that never called the model (a clarifying question asked before the
  model) stores 0. A question refused by the limit is not saved at all.

### Filling in the old rows

New update hook `vf_sql_chatbot_update_9011()`:

1. adds the column if it is missing (the same pattern as `update_9005`);
2. fills it in once for every existing row from the metadata JSON:

   ```sql
   UPDATE {sql_chat_turn} SET effective_tokens = ROUND(
       (COALESCE((metadata->'tokens'->>'prompt')::numeric, 0)
        - COALESCE((metadata->'tokens'->>'cache_read')::numeric, 0))
       + COALESCE((metadata->'tokens'->>'cache_read')::numeric, 0) * 0.1
       + COALESCE((metadata->'tokens'->>'completion')::numeric, 0))
   ```

Without step 2, the tokens already used this month (about 170,000 on
6 October 2026) would be missing from the budget. Old repair retries were
never recorded, so those rows stay slightly under their true cost. Accepted.

### Counting

New method `ConversationStore::monthlyEffectiveTokens()`, returning an int:

```sql
SELECT COALESCE(SUM(effective_tokens), 0)
FROM {sql_chat_turn}
WHERE created_at >= :month_start
```

- **All users.** Unlike the rest of `ConversationStore`, this method does not
  filter by `uid`. That is the point: the budget is shared.
- `:month_start` is 00:00 on the 1st of the current month in the site's time
  zone (`date_default_timezone_get()`, the same zone `stamp()` uses), as a
  unix time.
- 480 rows on 6 October 2026. No index needed at this size.
- The debug panel still works out its per-turn "Effective" figure itself, with
  the same formula, so the two agree.

Known blind spots, accepted:

- A turn whose history row failed to save (`recordTurn` swallows errors) is
  not counted.
- `purgeUser()` deletes a user's turns, which also removes them from the
  month's total.

## 3. Counting the repair retry

`TurnRunner::repairSql()` calls the provider a second time. Its
`prompt_tokens`, `completion_tokens`, `cache_read_tokens` and
`cache_write_tokens` are added onto the turn result `$r`, so they are saved
with the turn and counted in the budget.

Side effect: on turns that needed a repair, the per-turn token figures in the
debug panel and in history rise to the true cost.

Python's `lean_runner._repair` has the same gap and is left alone, so this is
a PHP-only difference, like the ones in `Redactor` and `Links`. It gets a line
in `docs/gotchas.md` so nobody "fixes" the two back into step by mistake.

## 4. Blocking

At the start of `ChatRuntime::ask()`, after the "question is required" check
and before taking the session lock:

```text
limit = config monthly_token_limit
if limit > 0 and monthlyEffectiveTokens() >= limit:
    throw TokenLimitException
```

- New class `src/Service/TokenLimitException.php` (extends
  `\RuntimeException`), next to `UnsafeSqlException`.
- **Message, the only text the user sees:**
  "You have exceeded your monthly token limit. Please try again next month."
- **`AskResource`** catches it and returns **HTTP 429**:
  `{"error": "<message>", "code": "monthly_token_limit"}`.
- **`StreamController`** catches it before its generic `\Throwable` catch and
  sends the same body as its `error` event.
- The frontend already shows the server's `error` text before falling back to
  its own wording, so the message appears with no frontend change.
- A refused question is not recorded and does not enter the last-10 window.
- **If the usage query fails, the question is allowed** and the failure is
  logged. A broken counter must not take the chatbot down.
- **May go slightly over.** A question's cost is only known after it runs, so
  the last allowed question can take usage past the limit by roughly one
  question's tokens. This matches the rule `used < limit` to proceed.
- Two questions arriving at the same moment can both pass the check. Accepted.

## 5. Showing usage in debug mode

**Backend.** After `recordTurn()` (so this question is included), and only
when the request asked for debug, `ChatRuntime::ask()` adds (with `limit: 0`
when no limit is set):

```json
"token_usage": { "used": 420000, "limit": 1000000 }
```

`token_usage` is **not** added to `Redactor::PUBLIC_FIELDS`, so with debug off
the server strips it and it never reaches the browser. The extra query runs
only on debug turns.

**Frontend** (`SqlChatbotPage.jsx`). In debug mode, in the top bar left of the
Chat | Debug switch, as a pill with a thin progress bar (moved there from the
line under the input on 6 October 2026, at the user's request), read from the
latest answer:

- Text: **`42% used`** — `Math.round(used / limit × 100)`. Can read above
  100% when the last question went over.
- Hover (`title`): **`420,000 / 1,000,000`** — both numbers with
  `toLocaleString()`.
- **No limit (0):** text **`Unlimited`**, hover **`180,431 / ∞`**. Added on
  6 October 2026 at the user's request.
- Shown only when debug is on and the latest answer carries `token_usage`.
- Like the model badge, it appears once the first answer in the chat arrives.

## 6. What does not change

- The last-K window (`RECENT_QUESTIONS = 10`) is untouched.
- No `services.yml` or constructor change, so no container rebuild. (The new
  column needs the database update in §8, which is a different step.)
- No Python change, and the five metadata files are untouched.

## 7. Testing

Backend:

- A bootstrap script (scratchpad, not committed) against the real database.
  It overrides the limit **in memory only**
  (`$GLOBALS['config']['vf_sql_chatbot.settings']['monthly_token_limit']`,
  then `configFactory()->reset(...)`), never in saved config. It checks:
  1. limit 1 → `TokenLimitException`, and no new `sql_chat_turn` row;
  2. limit 0 → the question goes through;
  3. a high limit with debug on → `token_usage` present, `used` matches a
     direct SQL sum;
  4. debug off → `token_usage` absent.
  It uses a sentinel session id and cleans up only that session's rows.
- After the update hook: every row's `effective_tokens` equals the formula
  worked out from its metadata (one SQL comparison, want 0 mismatches), and
  `monthlyEffectiveTokens()` equals the old metadata-based sum.
- A new turn stores `effective_tokens` matching its own `tokens` metadata.
- The existing checks still pass: `tests/context/check.php`,
  `tests/context/adversarial.php`, `tests/outcome/check.php`,
  `tests/provider/check.php`, and the parity check.
- `php -l` on every changed file; control-character check on every written
  file (gotchas §7).

Frontend:

- No test files (the repo keeps none). ESLint with `--ext .js,.jsx`, then
  `npm run dev`. The user checks it in the browser.

## 8. Rollout

- Drupal and React work on feature branches; merge on the user's say-so.
- **Run the database update** (`update_9011`) before using the new code.
  Until it runs, `recordTurn()` fails to insert (the column is missing) and the
  history row is lost. Drush is mostly broken here, so the plan will name the
  exact way to run it (`/update.php`, or a bootstrap script) after checking.
- `npm run dev` deploys to the live web root as soon as it runs.
- After deploying, the admin sets the limit on the settings page. Until then
  there is no limit.
