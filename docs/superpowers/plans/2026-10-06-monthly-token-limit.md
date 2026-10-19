# Monthly Token Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the SQL chatbot once all users together have used a set number of effective tokens in the current calendar month, and show the usage in debug mode.

**Architecture:** Every saved turn gets an `effective_tokens` column. `ChatRuntime::ask()` sums this month's column before doing anything else and refuses with HTTP 429 when the sum has reached the limit set on the LLM settings page. Debug responses carry `token_usage`, which the chat page shows as "NN% used".

**Tech Stack:** Drupal 10/11 module (PHP 8, PostgreSQL), React (webpack via `npm run dev`).

**Spec:** `docs/superpowers/specs/2026-10-06-monthly-token-limit-design.md`

## Global Constraints

- Paths: `M` = `C:/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot`, `F` = `C:/xampp/htdocs/WCMS%20-%20Frontend%20-%20Arvind%20Retail`, `P` = `C:/Users/ansh.gala/Desktop/Python/wren-poc`.
- **Branches: stay on the current ones.** Drupal `feat/drupal-11-chatbot-compat`, frontend `feat/sql-chatbot`. No new branch. Both repos already hold uncommitted work by the user; leave it alone and **commit everything together at the end** (Task 7), not per task.
- Effective tokens formula, everywhere: `(prompt − cache_read) + cache_read × 0.1 + completion`, rounded, never below 0.
- User-facing refusal text, exactly: `You have exceeded your monthly token limit. Please try again next month.`
- Refusal response: HTTP **429**, body `{"error": "<text>", "code": "monthly_token_limit"}`.
- Config key `monthly_token_limit` in `vf_sql_chatbot.settings`; **0 or missing = no limit**.
- Shared budget: the monthly sum covers **all users** (no `uid` filter).
- Month starts 00:00 on the 1st in `date_default_timezone_get()`.
- PHP module files are live the moment they are saved (Apache serves this checkout). Keep tasks in order: the column must exist (Task 2) before anything writes it (Task 3).
- **Never call a paid API.** Live Drupal is on the OpenAI API. Backend checks use a scripted fake provider (Task 3). Never run `create_readonly_role`.
- New parameters go **last** (gotchas §8).
- After writing any file: `tr -cd '\000-\010\013\014\016-\037' < FILE | wc -c` must print `0` (gotchas §7). Write `"\n"`, never a literal line break inside a PHP string.
- Frontend: no test files. Run `npm run dev` yourself after frontend edits, once. Never `npm run build`.
- Python repo: no code change.

---

### Task 1: Effective tokens as a pure function

**Files:**
- Modify: `M/src/Service/TurnOutcome.php` (add one static method at the end of the class)
- Test: `M/tests/outcome/check.php` (add a second case table before the final `printf`)

**Interfaces:**
- Produces: `TurnOutcome::effectiveTokens(array $r): int` — reads `prompt_tokens`, `cache_read_tokens`, `completion_tokens` from a turn result (missing keys = 0).

- [ ] **Step 1: Write the failing cases**

In `M/tests/outcome/check.php`, replace the last two lines:

```php
printf("\n%d case(s), %d failure(s)\n", count($cases), $failures);
exit($failures === 0 ? 0 : 1);
```

with:

```php
// Effective tokens: what the monthly limit counts. Cache reads at a tenth,
// the way the debug panel counts them.
$tokenCases = [
  'no model call' => [[], 0],
  'no cache' => [['prompt_tokens' => 1000, 'completion_tokens' => 200], 1200],
  'cache read at a tenth' => [['prompt_tokens' => 10000, 'cache_read_tokens' => 9000, 'completion_tokens' => 300], 2200],
  // Half rounds up, as Postgres ROUND() does in the backfill.
  'half rounds up' => [['prompt_tokens' => 5, 'cache_read_tokens' => 5], 1],
  // The trap: the column is unsigned, so a negative would lose the whole row.
  'never negative' => [['cache_read_tokens' => 100], 0],
];

echo "\neffective tokens\n";
foreach ($tokenCases as $name => [$result, $want]) {
  $got = TurnOutcome::effectiveTokens($result);
  $ok = $got === $want;
  $failures += $ok ? 0 : 1;
  printf("  %-38s %-10s %s\n", $name, $got, $ok ? 'ok' : 'FAILURE, wanted ' . $want);
}

printf("\n%d case(s), %d failure(s)\n", count($cases) + count($tokenCases), $failures);
exit($failures === 0 ? 0 : 1);
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd M && php tests/outcome/check.php`
Expected: fatal `Call to undefined method ...TurnOutcome::effectiveTokens()`.

- [ ] **Step 3: Implement**

Add inside `TurnOutcome`, after `responseType()`:

```php
  /**
   * What a turn cost, in effective tokens.
   *
   * Cache reads count at a tenth, as the debug panel counts them
   * (DebugDetails.jsx). Every provider already counts cache reads inside
   * prompt_tokens.
   *
   * @param array $r
   *   A turn result, as TurnRunner returns it.
   *
   * @return int
   *   Never negative: the column is unsigned, and a failed insert loses the
   *   whole history row.
   */
  public static function effectiveTokens(array $r) {
    $prompt = (int) ($r['prompt_tokens'] ?? 0);
    $cacheRead = (int) ($r['cache_read_tokens'] ?? 0);
    $completion = (int) ($r['completion_tokens'] ?? 0);
    return max(0, (int) round($prompt - $cacheRead + $cacheRead * 0.1 + $completion));
  }
```

- [ ] **Step 4: Run it to see it pass**

Run: `cd M && php tests/outcome/check.php`
Expected: last line `16 case(s), 0 failure(s)`, exit 0.

- [ ] **Step 5: Lint and control-character check**

Run: `cd M && php -l src/Service/TurnOutcome.php && php -l tests/outcome/check.php && for f in src/Service/TurnOutcome.php tests/outcome/check.php; do tr -cd '\000-\010\013\014\016-\037' < $f | wc -c; done`
Expected: `No syntax errors` twice, then `0` twice.

---

### Task 2: The `effective_tokens` column, filled in for old rows

**Files:**
- Modify: `M/vf_sql_chatbot.install` — `vf_sql_chatbot_schema()` `sql_chat_turn` fields, and a new `vf_sql_chatbot_update_9011()` at the end of the file.

**Interfaces:**
- Consumes: nothing from Task 1 (the backfill is SQL).
- Produces: column `sql_chat_turn.effective_tokens` (int, unsigned, not null, default 0) on the live database; config key `monthly_token_limit` present (0) on the live site.

- [ ] **Step 1: Add the field to the schema**

In `vf_sql_chatbot_schema()`, in `$schema['sql_chat_turn']['fields']`, after the `'llm_model' => [...]` line, add:

```php
      'effective_tokens' => ['type' => 'int', 'description' => 'What this turn cost: prompt minus cache reads, plus a tenth of the cache reads, plus the reply. 0 when no model was called', 'unsigned' => TRUE, 'not null' => TRUE, 'default' => 0,],
```

- [ ] **Step 2: Add the update hook**

Append to the end of `M/vf_sql_chatbot.install`:

```php
/**
 * Store each turn's effective tokens, so the monthly limit is a plain SUM.
 *
 * Fills in every existing row from the token counts in its metadata, or the
 * tokens already used this month would not count. Old repair retries were
 * never recorded, so those rows stay slightly under. Also gives existing
 * sites the monthly_token_limit key, at 0 (no limit). Safe to run again.
 */
function vf_sql_chatbot_update_9011() {
  $schema = \Drupal::database()->schema();
  if (!$schema->fieldExists('sql_chat_turn', 'effective_tokens')) {
    $schema->addField('sql_chat_turn', 'effective_tokens', vf_sql_chatbot_schema()['sql_chat_turn']['fields']['effective_tokens']);
  }

  // CAST, not ::numeric, so nothing reads the cast as a placeholder.
  $prompt = "COALESCE(CAST(metadata->'tokens'->>'prompt' AS numeric), 0)";
  $cacheRead = "COALESCE(CAST(metadata->'tokens'->>'cache_read' AS numeric), 0)";
  $completion = "COALESCE(CAST(metadata->'tokens'->>'completion' AS numeric), 0)";
  $filled = \Drupal::database()->query(
    "UPDATE {sql_chat_turn} SET effective_tokens = GREATEST(0, ROUND(($prompt - $cacheRead) + $cacheRead * 0.1 + $completion))"
  )->rowCount();

  $config = \Drupal::configFactory()->getEditable('vf_sql_chatbot.settings');
  if ($config->get('monthly_token_limit') === NULL) {
    $config->set('monthly_token_limit', 0)->save();
  }

  return 'Added sql_chat_turn.effective_tokens and filled it in for ' . $filled . ' existing turn(s). The monthly token limit is ' . (int) $config->get('monthly_token_limit') . ' (0 means no limit).';
}
```

- [ ] **Step 3: Lint**

Run: `cd M && php -l vf_sql_chatbot.install && tr -cd '\000-\010\013\014\016-\037' < vf_sql_chatbot.install | wc -c`
Expected: `No syntax errors`, `0`.

- [ ] **Step 4: Dry run the update**

Run: `cd M && php scripts/run_updates.php --dry-run`
Expected: `pending    [9010, 9011]`. As of 6 October 2026, `9010` (the user's uncommitted `tms_task_flat` view rebuild) has not run. The runner runs every pending hook in order, and 9011 cannot run alone: Drupal records only the highest number run, so a skipped 9010 would never run later. **Run Step 5 only if the user has agreed to 9010 running too.** If only `[9011]` is pending, carry on.

- [ ] **Step 5: Run the update**

Run: `cd M && php scripts/run_updates.php`
Expected: the hook's message, with a filled count around 480 or more.

- [ ] **Step 6: Verify the backfill against the metadata**

Write `<scratchpad>/check_backfill.php` with an editor (not a heredoc):

```php
<?php
require 'C:/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/scripts/bootstrap.php';

$db = \Drupal::database();
$prompt = "COALESCE(CAST(metadata->'tokens'->>'prompt' AS numeric), 0)";
$cacheRead = "COALESCE(CAST(metadata->'tokens'->>'cache_read' AS numeric), 0)";
$completion = "COALESCE(CAST(metadata->'tokens'->>'completion' AS numeric), 0)";
$formula = "GREATEST(0, ROUND(($prompt - $cacheRead) + $cacheRead * 0.1 + $completion))";

$mismatches = (int) $db->query("SELECT COUNT(*) FROM {sql_chat_turn} WHERE effective_tokens <> $formula")->fetchField();
$rows = (int) $db->query('SELECT COUNT(*) FROM {sql_chat_turn}')->fetchField();
$monthSql = (int) $db->query("SELECT COALESCE(SUM(effective_tokens), 0) FROM {sql_chat_turn} WHERE created_at >= EXTRACT(EPOCH FROM date_trunc('month', now()))")->fetchField();
printf("rows %d, mismatches %d, this month (db clock) %d\n", $rows, $mismatches, $monthSql);
exit($mismatches === 0 ? 0 : 1);
```

Run: `php <scratchpad>/check_backfill.php`
Expected: `mismatches 0`, this month about 170,000.

---

### Task 3: Write the column on every turn, count the repair retry, and sum the month

**Files:**
- Modify: `M/src/Service/ConversationStore.php` — `recordTurn()` insert fields; new public method `monthlyEffectiveTokens()` in the read path section.
- Modify: `M/src/Service/TurnRunner.php` — call site at line ~440 and `repairSql()` at line ~939.
- Test: `<scratchpad>/token_limit_check.php` (bootstrap script with a scripted model; extended in Task 5).

**Interfaces:**
- Consumes: `TurnOutcome::effectiveTokens(array $r): int` (Task 1); the column (Task 2).
- Produces: `ConversationStore::monthlyEffectiveTokens(): int` — all users, since 00:00 on the 1st, site time zone. `TurnRunner::repairSql($question, $sql, $error, array &$r)` — adds the retry's four token counts onto `$r`.

- [ ] **Step 1: Write the check script (fails until Steps 3–5 are done)**

Write `<scratchpad>/token_limit_check.php` with an editor:

```php
<?php

/**
 * Monthly token limit, end to end, with a scripted model.
 *
 * Real ChatRuntime, TurnRunner, store and read-only database; only the model
 * is scripted, so nothing is spent. Runs as uid 1 on a sentinel session and
 * deletes only that session afterwards.
 */

require 'C:/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/scripts/bootstrap.php';

use Drupal\vf_sql_chatbot\Llm\LlmProviderInterface;
use Drupal\vf_sql_chatbot\Llm\ProviderFactory;

// Hands out the queued replies in order.
$model = new class implements LlmProviderInterface {
  public $replies = [];
  public $calls = 0;

  public function ask($question, $context = NULL, ?callable $onDelta = NULL) {
    $this->calls++;
    $next = array_shift($this->replies) ?: ['result_text' => ''];
    return $next + ['ok' => TRUE, 'mode' => 'api', 'provider' => 'scripted', 'model' => 'scripted'] + LlmProviderInterface::RUN_DEFAULTS;
  }
};

// Set before anything asks for the runtime, so TurnRunner is built with it.
$factory = new class($model) extends ProviderFactory {
  private $model;

  public function __construct($model) {
    $this->model = $model;
  }

  public function get() {
    return $this->model;
  }
};
\Drupal::getContainer()->set('vf_sql_chatbot.provider_factory', $factory);

\Drupal::service('account_switcher')->switchTo(\Drupal\user\Entity\User::load(1));

$session = 'tokencheck-' . bin2hex(random_bytes(4));
$runtime = \Drupal::service('vf_sql_chatbot.runtime');
$store = \Drupal::service('vf_sql_chatbot.conversation_store');
$db = \Drupal::database();

$setLimit = function ($limit) {
  // In memory only: never saved to config.
  $GLOBALS['config']['vf_sql_chatbot.settings']['monthly_token_limit'] = $limit;
  \Drupal::configFactory()->reset('vf_sql_chatbot.settings');
};
$lastTurnTokens = function () use ($db, $session) {
  return $db->query(
    'SELECT t.effective_tokens FROM {sql_chat_turn} t JOIN {sql_chat} c ON c.id = t.chat_id
     WHERE c.uid = 1 AND c.session_id = :sid ORDER BY t.sequence_number DESC LIMIT 1',
    [':sid' => $session]
  )->fetchField();
};
$reply = function ($sql, array $tokens) {
  return ['result_text' => json_encode([
    'sql' => $sql,
    'explanation' => 'How many tasks there are.',
    'recap' => 'Counting tasks.',
  ])] + $tokens;
};

$failures = 0;
$check = function ($name, $ok, $detail = '') use (&$failures) {
  $failures += $ok ? 0 : 1;
  printf("  %-52s %s %s\n", $name, $ok ? 'ok' : 'FAILURE', $detail);
};

try {
  echo "token accounting\n";

  // 1. A plain turn stores its own effective tokens: 400 + 60 + 100.
  $setLimit(0);
  $model->replies = [$reply('SELECT COUNT(*) AS n FROM tms_task_flat', ['prompt_tokens' => 1000, 'cache_read_tokens' => 600, 'completion_tokens' => 100])];
  $model->calls = 0;
  $runtime->ask(['question' => 'How many tasks are there?', 'session_id' => $session]);
  $check('plain turn stores 560', (int) $lastTurnTokens() === 560, 'got ' . var_export($lastTurnTokens(), TRUE));

  // 2. A repaired turn counts both calls: 1050 + (1000 + 100 + 100).
  $model->replies = [
    $reply('SELECT nope FROM tms_task_flat', ['prompt_tokens' => 1000, 'completion_tokens' => 50]),
    $reply('SELECT COUNT(*) AS n FROM tms_task_flat', ['prompt_tokens' => 2000, 'cache_read_tokens' => 1000, 'completion_tokens' => 100]),
  ];
  $model->calls = 0;
  $runtime->ask(['question' => 'How many tasks are there in total?', 'session_id' => $session]);
  $check('repair was attempted (2 model calls)', $model->calls === 2, 'calls ' . $model->calls);
  $check('repaired turn stores 2250', (int) $lastTurnTokens() === 2250, 'got ' . var_export($lastTurnTokens(), TRUE));

  // 3. The month's sum, against the database's own clock.
  $direct = (int) $db->query("SELECT COALESCE(SUM(effective_tokens), 0) FROM {sql_chat_turn} WHERE created_at >= EXTRACT(EPOCH FROM date_trunc('month', now()))")->fetchField();
  $mine = $store->monthlyEffectiveTokens();
  $check('monthlyEffectiveTokens matches a direct sum', $mine === $direct, "$mine vs $direct");
}
finally {
  $db->delete('sql_chat')->condition('uid', 1)->condition('session_id', $session)->execute();
  $store->reset($session);
  \Drupal::service('account_switcher')->switchBack();
}

printf("\n%d failure(s)\n", $failures);
exit($failures === 0 ? 0 : 1);
```

Note on check 3: the database clock and the PHP time zone can disagree near midnight on the 1st. Any other day they agree; if it fails on the 1st, rerun the next day before chasing it.

- [ ] **Step 2: Run it to see it fail**

Run: `php <scratchpad>/token_limit_check.php`
Expected: `plain turn stores 560 FAILURE got 0` (column still defaults to 0), and a fatal on `monthlyEffectiveTokens()` being undefined. The `finally` block still cleans up.

- [ ] **Step 3: Write the column in `recordTurn()`**

In `M/src/Service/ConversationStore.php`, in `recordTurn()`, after the `'llm_model' => ...` line, add:

```php
          // Its own column so the monthly limit is a plain SUM.
          'effective_tokens' => TurnOutcome::effectiveTokens($r),
```

- [ ] **Step 4: Add `monthlyEffectiveTokens()`**

In `M/src/Service/ConversationStore.php`, after `countChats()`, add:

```php
  /**
   * Effective tokens every user together has used this calendar month.
   *
   * No uid filter, unlike everything else here: the budget is shared. The
   * month starts at 00:00 on the 1st in the site's time zone, the zone
   * stamp() uses.
   */
  public function monthlyEffectiveTokens() {
    $start = (new \DateTimeImmutable('@' . $this->time->getRequestTime()))
      ->setTimezone(new \DateTimeZone(date_default_timezone_get()))
      ->modify('first day of this month')
      ->setTime(0, 0);
    return (int) $this->database->query(
      'SELECT COALESCE(SUM(effective_tokens), 0) FROM {sql_chat_turn} WHERE created_at >= :start',
      [':start' => $start->getTimestamp()]
    )->fetchField();
  }
```

- [ ] **Step 5: Count the repair retry**

In `M/src/Service/TurnRunner.php`, change the call (line ~440):

```php
          $fixed = $this->repairSql($question, $parsed['sql'], $actual['error']);
```

to:

```php
          $fixed = $this->repairSql($question, $parsed['sql'], $actual['error'], $r);
```

In `repairSql()`, add the parameter to the docblock after `@param string $error`:

```php
   * @param array $r
   *   The turn result. The retry's tokens are added to it, so the turn records
   *   what it really cost.
```

change the signature to:

```php
  protected function repairSql($question, $sql, $error, array &$r) {
```

and directly after the `$run = $this->providerFactory->get()->ask(...);` statement add:

```php
    // Counted before any return: a repair that fails still cost tokens.
    foreach (['prompt_tokens', 'completion_tokens', 'cache_read_tokens', 'cache_write_tokens'] as $key) {
      $r[$key] = (int) ($r[$key] ?? 0) + (int) ($run[$key] ?? 0);
    }
```

- [ ] **Step 6: Lint**

Run: `cd M && for f in src/Service/ConversationStore.php src/Service/TurnRunner.php; do php -l $f; tr -cd '\000-\010\013\014\016-\037' < $f | wc -c; done`
Expected: `No syntax errors` and `0` for each.

- [ ] **Step 7: Run the check to see it pass**

Run: `php <scratchpad>/token_limit_check.php`
Expected: four `ok` lines, `0 failure(s)`.

- [ ] **Step 8: Run the harnesses that load TurnRunner**

Run: `cd M && php tests/context/check.php | tail -2 && php tests/context/adversarial.php | tail -2`
Expected: 88 and 113 cases, 0 failures.

---

### Task 4: The setting on the LLM settings page

**Files:**
- Modify: `M/config/schema/vf_sql_chatbot.schema.yml` (after `stream_answers`)
- Modify: `M/config/install/vf_sql_chatbot.settings.yml` (after `stream_answers: true`)
- Modify: `M/src/Form/LlmSettingsForm.php` — `buildForm()` after `$form['stream_answers']`, and `submitForm()`.

**Interfaces:**
- Produces: `vf_sql_chatbot.settings:monthly_token_limit` (int, ≥ 0), read by Task 5.

- [ ] **Step 1: Schema**

In `vf_sql_chatbot.schema.yml`, after the `stream_answers:` block (its `label:` line), add:

```yaml
    monthly_token_limit:
      type: integer
      label: 'Effective tokens all users together may use per calendar month. 0 means no limit'
```

- [ ] **Step 2: Install default**

In `vf_sql_chatbot.settings.yml`, after `stream_answers: true`, add:

```yaml
# Effective tokens all users together may use per calendar month, counted
# from the 1st: prompt minus cache reads, plus a tenth of the cache reads,
# plus the reply. 0 means no limit. Set on /admin/config/system/sql-chatbot-llm.
monthly_token_limit: 0
```

- [ ] **Step 3: The form field**

In `LlmSettingsForm::buildForm()`, after the `$form['stream_answers'] = [...];` statement, add:

```php
    $form['monthly_token_limit'] = [
      '#type' => 'number',
      '#title' => $this->t('Monthly token limit'),
      '#default_value' => (int) $config->get('monthly_token_limit'),
      '#min' => 0,
      '#step' => 1,
      '#description' => $this->t('How many effective tokens all users together may use in a calendar month, counted from the 1st. Effective means cache reads count at a tenth. When it is reached, the chatbot refuses new questions until next month. 0 means no limit.'),
    ];
```

In `submitForm()`, add to the chain after `->set('stream_answers', ...)` (move the `;`):

```php
      ->set('stream_answers', (bool) $form_state->getValue('stream_answers'))
      ->set('monthly_token_limit', (int) $form_state->getValue('monthly_token_limit'));
```

- [ ] **Step 4: Lint**

Run: `cd M && php -l src/Form/LlmSettingsForm.php && for f in src/Form/LlmSettingsForm.php config/schema/vf_sql_chatbot.schema.yml config/install/vf_sql_chatbot.settings.yml; do tr -cd '\000-\010\013\014\016-\037' < $f | wc -c; done && php -r 'require "C:/xampp/htdocs/dev-arvind-retail-chatbot/vendor/autoload.php"; foreach (["config/schema/vf_sql_chatbot.schema.yml","config/install/vf_sql_chatbot.settings.yml"] as $f) { Symfony\Component\Yaml\Yaml::parseFile($f); echo "$f parses\n"; }'`
Expected: `No syntax errors`, three `0`s, two `parses` lines.

- [ ] **Step 5: Check the field renders**

Run: `curl -k -s -o /dev/null -w "%{http_code}\n" "https://local-arvind-retail-chatbot.wcms.cloud/admin/config/system/sql-chatbot-llm"`
Expected: `403` (anonymous; the page builds without a 500). The user checks the field in the browser; do not save the form from a script.

---

### Task 5: Refuse over the limit, and report usage in debug

**Files:**
- Create: `M/src/Service/TokenLimitException.php`
- Modify: `M/src/Service/ChatRuntime.php` — `ask()` and two new protected methods.
- Modify: `M/src/Plugin/rest/resource/AskResource.php` — `post()` and a `use` line.
- Modify: `M/src/Controller/StreamController.php` — the `try` in `stream()` and a `use` line.
- Test: extend `<scratchpad>/token_limit_check.php`.

**Interfaces:**
- Consumes: `ConversationStore::monthlyEffectiveTokens(): int` (Task 3); config `monthly_token_limit` (Task 4).
- Produces: `TokenLimitException` with `const MESSAGE` and `const CODE = 'monthly_token_limit'`; debug responses carry `token_usage: {used: int, limit: int}` when a limit is set (read by Task 6).

- [ ] **Step 1: Extend the check script (fails until Steps 3–6)**

In `<scratchpad>/token_limit_check.php`, add `use Drupal\vf_sql_chatbot\Service\TokenLimitException;` under the other `use` lines, and insert before the `}` that closes the `try` block:

```php
  echo "\nlimit\n";

  // 4. Over the limit: refused before the model or the history.
  $setLimit(1);
  $model->replies = [$reply('SELECT 1', ['prompt_tokens' => 1])];
  $model->calls = 0;
  $turnsBefore = (int) $db->query('SELECT COUNT(*) FROM {sql_chat_turn}')->fetchField();
  $refused = NULL;
  try {
    $runtime->ask(['question' => 'How many tasks are there?', 'session_id' => $session]);
  }
  catch (TokenLimitException $exception) {
    $refused = $exception;
  }
  $check('limit 1 throws TokenLimitException', $refused !== NULL);
  $check('refusal text is the agreed one', $refused && $refused->getMessage() === 'You have exceeded your monthly token limit. Please try again next month.');
  $check('model was not called', $model->calls === 0, 'calls ' . $model->calls);
  $check('no turn was recorded', (int) $db->query('SELECT COUNT(*) FROM {sql_chat_turn}')->fetchField() === $turnsBefore);

  // 5. No limit, debug on: answered, and no token_usage to show.
  $setLimit(0);
  $model->replies = [$reply('SELECT COUNT(*) AS n FROM tms_task_flat', ['prompt_tokens' => 100])];
  $answer = $runtime->ask(['question' => 'How many tasks are there?', 'session_id' => $session, 'debug' => TRUE]);
  $check('limit 0 answers', empty($answer['error']), (string) ($answer['error'] ?? ''));
  $check('limit 0 sends no token_usage', !array_key_exists('token_usage', $answer));

  // 6. High limit, debug on: usage includes this very turn (100 tokens).
  $setLimit(1000000000);
  $before = $store->monthlyEffectiveTokens();
  $model->replies = [$reply('SELECT COUNT(*) AS n FROM tms_task_flat', ['prompt_tokens' => 100])];
  $answer = $runtime->ask(['question' => 'How many tasks are there?', 'session_id' => $session, 'debug' => TRUE]);
  $usage = $answer['token_usage'] ?? NULL;
  $check('debug carries token_usage', is_array($usage));
  $check('token_usage.limit is the limit', ($usage['limit'] ?? NULL) === 1000000000);
  $check('token_usage.used includes this turn', ($usage['used'] ?? NULL) === $before + 100, var_export($usage['used'] ?? NULL, TRUE) . ' vs ' . ($before + 100));

  // 7. High limit, debug off: stripped server-side.
  $model->replies = [$reply('SELECT COUNT(*) AS n FROM tms_task_flat', ['prompt_tokens' => 100])];
  $answer = $runtime->ask(['question' => 'How many tasks are there?', 'session_id' => $session]);
  $check('debug off strips token_usage', !array_key_exists('token_usage', $answer));
```

Check 6 can be off by another user's turn landing in the same second on the live site. If it fails by a few thousand, rerun once before chasing it.

- [ ] **Step 2: Run it to see it fail**

Run: `php <scratchpad>/token_limit_check.php`
Expected: fatal `Class "Drupal\vf_sql_chatbot\Service\TokenLimitException" not found` at the `catch`, or `limit 1 throws TokenLimitException FAILURE`.

- [ ] **Step 3: The exception**

Create `M/src/Service/TokenLimitException.php`:

```php
<?php

namespace Drupal\vf_sql_chatbot\Service;

/**
 * Thrown when this month's shared token budget is used up.
 *
 * Its message is the only thing the person sees, so it names nothing inside.
 */
class TokenLimitException extends \RuntimeException {

  /**
   * What the person is told.
   */
  const MESSAGE = 'You have exceeded your monthly token limit. Please try again next month.';

  /**
   * What the frontend can tell this refusal apart by.
   */
  const CODE = 'monthly_token_limit';

}
```

- [ ] **Step 4: Check before anything else in `ChatRuntime::ask()`**

In `M/src/Service/ChatRuntime.php`, in `ask()`, directly after the first `if ($question === '' && $dropRef === '') { throw ...; }` block and before `$sessionId = ...`, add:

```php
    // Before the state is loaded: a refused question costs nothing and never
    // enters the recent-questions window.
    $this->assertWithinMonthlyLimit();
```

Add `@throws` to the docblock of `ask()`, after the `\RuntimeException` entry:

```php
   * @throws \Drupal\vf_sql_chatbot\Service\TokenLimitException
   *   When this month's shared token budget is used up.
```

Replace the last statement of `ask()`:

```php
    // Enforced server-side: a field sent to the browser has already leaked.
    return !empty($payload['debug']) ? $full : $this->redactor->publicResponse($full);
```

with:

```php
    if (!empty($payload['debug'])) {
      // After recordTurn, so the figure includes this question.
      $usage = $this->tokenUsage();
      if ($usage !== NULL) {
        $full['token_usage'] = $usage;
      }
    }

    // Enforced server-side: a field sent to the browser has already leaked.
    return !empty($payload['debug']) ? $full : $this->redactor->publicResponse($full);
```

Add after `ask()`:

```php
  /**
   * The monthly token limit, or 0 for none.
   */
  protected function monthlyLimit() {
    return max(0, (int) $this->configFactory->get('vf_sql_chatbot.settings')->get('monthly_token_limit'));
  }

  /**
   * Refuse when all users together have reached this month's limit.
   *
   * A usage figure that cannot be read lets the question through: a broken
   * counter must not take the chatbot down. The last question allowed can go
   * over by its own cost, which is only known once it has run.
   *
   * @throws \Drupal\vf_sql_chatbot\Service\TokenLimitException
   */
  protected function assertWithinMonthlyLimit() {
    $limit = $this->monthlyLimit();
    if ($limit === 0) {
      return;
    }
    try {
      $used = $this->store->monthlyEffectiveTokens();
    }
    catch (\Throwable $exception) {
      $this->logger->error('Monthly token usage could not be read, so the question was allowed: @message', [
        '@message' => $exception->getMessage(),
      ]);
      return;
    }
    if ($used >= $limit) {
      throw new TokenLimitException(TokenLimitException::MESSAGE);
    }
  }

  /**
   * This month's usage for the debug badge, or NULL when there is no limit.
   */
  protected function tokenUsage() {
    $limit = $this->monthlyLimit();
    if ($limit === 0) {
      return NULL;
    }
    try {
      return ['used' => $this->store->monthlyEffectiveTokens(), 'limit' => $limit];
    }
    catch (\Throwable $exception) {
      return NULL;
    }
  }
```

(`TokenLimitException` is in the same namespace as `ChatRuntime`; no `use` line needed.)

- [ ] **Step 5: 429 from `AskResource`**

In `M/src/Plugin/rest/resource/AskResource.php`, add under the existing `use` lines:

```php
use Drupal\vf_sql_chatbot\Service\TokenLimitException;
```

In `post()`, insert before `catch (\InvalidArgumentException $exception) {`:

```php
    catch (TokenLimitException $exception) {
      return new JsonResponse(['error' => $exception->getMessage(), 'code' => TokenLimitException::CODE], 429);
    }
```

- [ ] **Step 6: The same from `StreamController`**

In `M/src/Controller/StreamController.php`, add under the existing `use` lines:

```php
use Drupal\vf_sql_chatbot\Service\TokenLimitException;
```

In `stream()`, insert before `catch (\InvalidArgumentException $exception) {`:

```php
      catch (TokenLimitException $exception) {
        // Same body as AskResource's 429.
        $emit('error', ['error' => $exception->getMessage(), 'code' => TokenLimitException::CODE]);
      }
```

- [ ] **Step 7: Lint**

Run: `cd M && for f in src/Service/TokenLimitException.php src/Service/ChatRuntime.php src/Plugin/rest/resource/AskResource.php src/Controller/StreamController.php; do php -l $f; tr -cd '\000-\010\013\014\016-\037' < $f | wc -c; done`
Expected: `No syntax errors` and `0` for each.

- [ ] **Step 8: Run the check to see it pass**

Run: `php <scratchpad>/token_limit_check.php`
Expected: every line `ok`, `0 failure(s)`.

- [ ] **Step 9: The live endpoint still answers**

Run: `curl -k -s -o /dev/null -w "%{http_code}\n" "https://local-arvind-retail-chatbot.wcms.cloud/api/sql-chat/health?_format=json"`
Expected: `403` (container fine). No container rebuild is needed: no services.yml or constructor changed.

---

### Task 6: "NN% used" in debug mode

**Files:**
- Modify: `F/src/pages/SqlChatbotPage.jsx` — a `useMemo` after `answeredBy` (line ~228) and the disclaimer markup (line ~678).

**Interfaces:**
- Consumes: `answer.token_usage = {used: number, limit: number}` (Task 5), present only on debug answers when a limit is set.

- [ ] **Step 1: Work out the badge**

After the `answeredBy` `useMemo` block (ends `}, [latest, debug]);`), add:

```jsx
  // This month's shared token budget. Debug mode only, and only when the
  // server has a limit to report.
  const tokenUsage = useMemo(() => {
    const usage = latest?.token_usage;
    if (!debug || !usage || !usage.limit) return null;
    return {
      label: `${Math.round((usage.used / usage.limit) * 100)}% used`,
      title: `${usage.used.toLocaleString()} / ${usage.limit.toLocaleString()}`,
    };
  }, [latest, debug]);
```

- [ ] **Step 2: Show it next to the model badge**

In the `sqlchat-disclaimer` paragraph, after the `{answeredBy ? (...) : null}` block and before `AI can make mistakes.`, add:

```jsx
              {tokenUsage ? (
                <>
                  <span className="sqlchat-model" title={tokenUsage.title}>
                    {tokenUsage.label}
                  </span>
                  {" · "}
                </>
              ) : null}
```

It reuses `sqlchat-model` (muted, monospace), so no CSS change.

- [ ] **Step 3: Lint**

Run: `cd F && npx eslint --no-eslintrc -c .eslintrc.json --parser-options=ecmaVersion:2022,sourceType:module,ecmaFeatures:{jsx:true} --ext .js,.jsx src/pages/SqlChatbotPage.jsx && tr -cd '\000-\010\013\014\016-\037' < src/pages/SqlChatbotPage.jsx | wc -c`
Expected: no errors (old warnings are not yours), `0`.

- [ ] **Step 4: Build**

Run: `cd F && npm run dev` (site is down ~45 s while it builds).
Expected: webpack finishes without errors.

- [ ] **Step 5: Confirm it shipped**

Run: `cd F && grep -l "% used" build/src_pages_SqlChatbotPage_jsx.*.js`
Expected: one file listed.

The user tests in the browser: set a limit on the settings page, turn on debug, ask a question, hover the badge. Do not write UI tests.

---

### Task 7: Docs, full check, commit together

**Files:**
- Modify: `P/docs/gotchas.md` — new section 16.
- Memory: update `php-only-drift-redactor-links.md` to add the repair-token difference.

- [ ] **Step 1: Gotchas**

Append to `P/docs/gotchas.md`:

```markdown
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
```

- [ ] **Step 2: Update the drift memory**

Add one line to the memory file `php-only-drift-redactor-links.md`: since 2026-10-06, `TurnRunner::repairSql()` also differs (it counts the retry's tokens); Python's `_repair` does not.

- [ ] **Step 3: Run every backend check**

Run:

```bash
cd M
php tests/outcome/check.php | tail -1      # 16 case(s), 0 failure(s)
php tests/context/check.php | tail -1      # 88 cases, 0 failures
php tests/context/adversarial.php | tail -1  # 113 cases, 0 failures
php tests/provider/check.php | tail -1     # 47 cases, 0 failures
cd P && python M/tests/parity/generate_expected.py <scratchpad>/parity && php M/tests/parity/check.php <scratchpad>/parity | tail -3   # PARITY HOLDS
php <scratchpad>/token_limit_check.php     # 0 failure(s)
php <scratchpad>/check_backfill.php        # mismatches 0
```

Expected: as commented. Any failure: stop and report it with its output.

- [ ] **Step 4: Commit together (ask first)**

Show the user `git status --short` for the Drupal and frontend repos, with a draft message for each. Each commit includes the user's pre-existing uncommitted work, as they asked, so ask them to confirm the message (and to describe their own changes if the draft does not cover them) before committing.

Draft, Drupal (`feat/drupal-11-chatbot-compat`):

```text
Cap the chatbot's monthly tokens, shared by all users

Each turn now stores its effective tokens; update_9011 adds the column and
fills in the old rows. ChatRuntime refuses with 429 once this month's sum
reaches the limit set on the LLM settings page (0 means none), and debug
answers carry token_usage. The SQL-repair retry's tokens now count.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

Draft, frontend (`feat/sql-chatbot`):

```text
Show the month's token usage in debug mode

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

Python repo (`P`): the spec, this plan and `docs/gotchas.md`. Its branch also holds unrelated uncommitted work. Ask the user whether to commit only these three files (gotchas.md already has their uncommitted edits in it) or leave them uncommitted.
