# Full CSV Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The chat table shows at most 200 rows. A "Show More Data" button opens a modal that gets every row as a CSV file from the backend.

**Architecture:** `ChatRuntime` cuts the rows it sends to 200 and tells the browser the chat id and question number. A new Drupal route runs that question's stored SQL again, through the same safety gates, and returns the CSV in the reply body. A new React modal calls the route, shows a spinner, then offers the Blob as a download.

**Tech Stack:** Drupal 10 module `vf_sql_chatbot` (PHP 8, Postgres via PDO), React 18 + react-bootstrap + axios, ag-grid.

**Spec:** `docs/superpowers/specs/2026-10-16-full-csv-download-design.md`

## Global Constraints

- Shown rows: exactly **200** (`ChatRuntime::SHOWN_ROWS` in PHP, `MAX_SHOWN_ROWS` in JS).
- Endpoint: `GET /api/sql-chat/chats/{chat_id}/turns/{turn}/csv`. `turn` is the 1-based `sequence_number`.
- Response field: `result.download = { chat_id: int, turn: int }`. Set only when `result.truncated` is true and the chat was saved.
- Errors: 404 `No such chat.` / 404 `No such answer.` / 422 `This answer cannot be downloaded.` / 500 with `Redactor::safeError()` text.
- Frontend messages: "Preparing the full file…", "The file is ready.", "This answer can no longer be found.", "The file could not be made. Please try again."
- The existing CSV / Excel download menu does not change.
- PHP-only. Python does not change. Parity does not cover `ChatRuntime`, `Redactor` or controllers.
- New code in a file is commented like the code around it (short "why" comments, Drupal docblocks in PHP).
- Shell: never write PHP or JS through a heredoc (gotchas §7). Use the Write/Edit tools.
- Commits end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Repos and branches

| Short name | Path | Start branch | New branch |
|---|---|---|---|
| Drupal | `c:\xampp\htdocs\dev-arvind-retail-chatbot` | `feat/drupal-11-chatbot-compat` | `feat/chatbot-full-csv` |
| Frontend | `c:\xampp\htdocs\WCMS%20-%20Frontend%20-%20Arvind%20Retail` | `feat/sql-chatbot` | `feat/chatbot-full-csv` |

Module folder: `MOD = c:\xampp\htdocs\dev-arvind-retail-chatbot\web\modules\custom\vf_sql_chatbot`.
Scratchpad: `SCRATCH = C:\Users\ANSH~1.GAL\AppData\Local\Temp\claude\c--Users-ansh-gala-Desktop-Python-wren-poc\b8ea9e6f-e0cf-4aad-a5fa-f5cc57111e4a\scratchpad`.

## File map

| File | Change | Why |
|---|---|---|
| `MOD/src/Service/ChatRuntime.php` | Modify | `SHOWN_ROWS`, `shownRows()`, cut in `toResponse()` and `rowsEvent()`, set `download` in `ask()` |
| `MOD/src/Service/Redactor.php` | Modify | `download` in `PUBLIC_RESULT_FIELDS` |
| `MOD/src/Controller/CsvController.php` | Create | The endpoint |
| `MOD/vf_sql_chatbot.routing.yml` | Modify | The route |
| `SCRATCH/verify_full_csv.php` | Create (not committed) | Backend checks |
| `FE/src/api/SqlChatbotApi.jsx` | Modify | `downloadFullCsv()` |
| `FE/src/components/Modals/SqlChatFullCsv.jsx` | Create | The modal |
| `FE/src/components/Modals/index.jsx` | Modify | Register the modal |
| `FE/src/components/SqlChatbot/ChatResultGrid.jsx` | Modify | 200-row guard and the button |
| `wren-poc/docs/gotchas.md` | Modify | One new section |

---

### Task 1: Backend — send 200 rows and name the question

**Files:**
- Modify: `MOD/src/Service/ChatRuntime.php` (constants near line 23; `ask()` near line 249; `toResponse()` line 461; `rowsEvent()` line 623; new method before `presentRows()` near line 670)
- Modify: `MOD/src/Service/Redactor.php:80-95`
- Test: `SCRATCH/verify_full_csv.php` (part 1)

**Interfaces:**
- Produces: `ChatRuntime::SHOWN_ROWS = 200`; `public static function shownRows($summary)` returns the summary with `rows` cut to 200 and `truncated = TRUE` when it had more, otherwise unchanged. Response field `result.download = ['chat_id' => int, 'turn' => int]`.

- [ ] **Step 1: Make the branch**

```powershell
git -C "c:\xampp\htdocs\dev-arvind-retail-chatbot" switch -c feat/chatbot-full-csv
```

- [ ] **Step 2: Write the failing check (part 1)**

Create `SCRATCH/verify_full_csv.php` with the Write tool:

```php
<?php

// Checks for the full-CSV feature. Part 2 writes sentinel chat rows and
// removes them again; nothing else is written.

require 'C:/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/scripts/bootstrap.php';

use Drupal\vf_sql_chatbot\Service\ChatRuntime;

$failures = 0;
$check = function ($label, $ok) use (&$failures) {
  printf("  %-56s %s\n", $label, $ok ? 'ok' : 'FAILURE');
  if (!$ok) {
    $failures++;
  }
};

echo "shown rows\n";
$big = ['columns' => ['n'], 'rows' => array_map(fn ($i) => [$i], range(1, 250)), 'row_count' => 250, 'truncated' => FALSE];
$cut = ChatRuntime::shownRows($big);
$check('250 rows become 200', count($cut['rows']) === 200);
$check('the first row stays first', $cut['rows'][0] === [1]);
$check('row_count keeps 250', $cut['row_count'] === 250);
$check('truncated is set', $cut['truncated'] === TRUE);
$exact = ['columns' => ['n'], 'rows' => array_map(fn ($i) => [$i], range(1, 200)), 'row_count' => 200, 'truncated' => FALSE];
$check('exactly 200 rows are unchanged', ChatRuntime::shownRows($exact) === $exact);
$error = ['error' => 'x', 'sqlstate' => NULL];
$check('an error summary is unchanged', ChatRuntime::shownRows($error) === $error);
$check('NULL is unchanged', ChatRuntime::shownRows(NULL) === NULL);

echo "public response\n";
$public = \Drupal::service('vf_sql_chatbot.redactor')->publicResponse([
  'result' => ['rows' => [], 'download' => ['chat_id' => 7, 'turn' => 2]],
]);
$check('download survives the whitelist', ($public['result']['download'] ?? NULL) === ['chat_id' => 7, 'turn' => 2]);

// PART 2 GOES HERE

echo $failures === 0 ? "\nALL CHECKS PASS\n" : "\n$failures FAILURE(S)\n";
exit($failures === 0 ? 0 : 1);
```

- [ ] **Step 3: Run it and see it fail**

```powershell
php "$SCRATCH\verify_full_csv.php"
```
Expected: a fatal error `Call to undefined method ...ChatRuntime::shownRows()`.

- [ ] **Step 4: Add the constant**

In `ChatRuntime.php`, after `const LOCK_TTL = 1200;`:

```php

  /**
   * Rows the browser is sent. More are cut, with `truncated` set, and the
   * person gets the rest from CsvController.
   */
  const SHOWN_ROWS = 200;
```

- [ ] **Step 5: Add `shownRows()`**

In `ChatRuntime.php`, directly above the docblock of `protected function presentRows($summary)`:

```php
  /**
   * A summary with at most SHOWN_ROWS rows.
   *
   * row_count keeps the whole count, so the grid can say "showing the first
   * 200". An error summary or NULL passes through.
   */
  public static function shownRows($summary) {
    if (!is_array($summary) || !isset($summary['rows']) || count($summary['rows']) <= self::SHOWN_ROWS) {
      return $summary;
    }
    $summary['rows'] = array_slice($summary['rows'], 0, self::SHOWN_ROWS);
    $summary['truncated'] = TRUE;
    return $summary;
  }

```

- [ ] **Step 6: Cut in `toResponse()` and `rowsEvent()`**

In `toResponse()`, replace
```php
      $this->presentRows($r['actual_result']),
```
with
```php
      $this->presentRows(self::shownRows($r['actual_result'])),
```

In `rowsEvent()`, replace
```php
      'result' => $this->presentRows($early['actual_result'] ?? NULL),
```
with
```php
      'result' => $this->presentRows(self::shownRows($early['actual_result'] ?? NULL)),
```

- [ ] **Step 7: Set `download` in `ask()`**

In `ask()`, replace
```php
      $chatId = $this->store->save($sessionId, $state, $question);
```
with
```php
      $chatId = $this->store->save($sessionId, $state, $question);

      // Lets the browser ask CsvController for every row. Only now: the chat
      // id does not exist until save().
      if ($chatId !== NULL && !empty($full['result']['truncated'])) {
        $full['result']['download'] = ['chat_id' => (int) $chatId, 'turn' => $turnIndex + 1];
      }
```

- [ ] **Step 8: Whitelist `download`**

In `Redactor.php`, in `PUBLIC_RESULT_FIELDS`, replace
```php
    'chart_note', 'freshness',
  ];
```
with
```php
    'chart_note', 'freshness',
    // Two integers: the chat id and the question's number in it.
    'download',
  ];
```

- [ ] **Step 9: Run the check and see it pass**

```powershell
php -l "$MOD\src\Service\ChatRuntime.php"; php -l "$MOD\src\Service\Redactor.php"; php "$SCRATCH\verify_full_csv.php"
```
Expected: `No syntax errors detected` twice, then 8 `ok` lines and `ALL CHECKS PASS`.

- [ ] **Step 10: Check for control characters (gotchas §7)**

```bash
for f in src/Service/ChatRuntime.php src/Service/Redactor.php; do tr -cd '\000-\010\013\014\016-\037' < "$f" | wc -c; done
```
Run from `MOD` in Git Bash. Expected: `0` twice.

- [ ] **Step 11: Commit**

```powershell
git -C "c:\xampp\htdocs\dev-arvind-retail-chatbot" add web/modules/custom/vf_sql_chatbot/src/Service/ChatRuntime.php web/modules/custom/vf_sql_chatbot/src/Service/Redactor.php
git -C "c:\xampp\htdocs\dev-arvind-retail-chatbot" commit -m @'
Send the table 200 rows, and say which question it answers

The browser gets the first 200 rows, the full row_count and truncated. When
rows were cut, result.download names the chat and the question, so the page
can ask for every row.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 2: Backend — the CSV endpoint

**Files:**
- Create: `MOD/src/Controller/CsvController.php`
- Modify: `MOD/vf_sql_chatbot.routing.yml` (append)
- Test: `SCRATCH/verify_full_csv.php` (part 2)

**Interfaces:**
- Consumes: `ConversationStore::openChat($chatId)` → `['chat' => [...], 'turns' => [rows]]` or NULL; `SafetyGate::assertReadOnly($sql)` throws `UnsafeSqlException`; `SchemaChecker::check($sql)['grounded']`; `QueryRunner::runReadonly($sql)` → `['columns', 'rows', 'ok', 'error', 'sqlstate', ...]`; `ColumnLabels::withColumnLabels(['columns' => [...]])['column_labels']`; `Redactor::safeError($error, $sqlstate)`.
- Produces: route `vf_sql_chatbot.full_csv`; `CsvController::download($chat_id, $turn)` returns a `Response` (CSV) or `JsonResponse` (error); `public static function cell($value)` returns a string.

- [ ] **Step 1: Write the failing check (part 2)**

In `SCRATCH/verify_full_csv.php`, add after the `use ...ChatRuntime;` line:

```php
use Drupal\user\Entity\User;
use Drupal\vf_sql_chatbot\Controller\CsvController;
```

Replace `// PART 2 GOES HERE` with:

```php
echo "csv cells\n";
$check('a formula gets a quote', CsvController::cell('=SUM(A1)') === "'=SUM(A1)");
$check('@ gets a quote', CsvController::cell('@x') === "'@x");
$check('a negative number is unchanged', CsvController::cell('-5') === '-5');
$check('plain text is unchanged', CsvController::cell('AR_YD_Suiting') === 'AR_YD_Suiting');
$check('NULL is empty', CsvController::cell(NULL) === '');
$check('TRUE is "true"', CsvController::cell(TRUE) === 'true');

echo "endpoint\n";
$database = \Drupal::database();
$switcher = \Drupal::service('account_switcher');
$sentinel = 'verify-csv-' . getmypid();
$now = time();
$sql = 'SELECT assigned_user_name FROM tms_task_flat';
$expected = (int) \Drupal::service('vf_sql_chatbot.query_runner')
  ->runReadonly('SELECT COUNT(*) FROM tms_task_flat')['rows'][0][0];
$otherUid = (int) $database->query('SELECT uid FROM {users} WHERE uid > 1 ORDER BY uid LIMIT 1')->fetchField();

$chatId = (int) $database->insert('sql_chat')->fields([
  'uid' => 1, 'session_id' => $sentinel, 'title' => 'csv check',
  'created_at' => $now, 'updated_at' => $now,
])->execute();
$addTurn = function ($sequence, $status, $turnSql) use ($database, $chatId, $now) {
  $database->insert('sql_chat_turn')->fields([
    'chat_id' => $chatId, 'sequence_number' => $sequence, 'question' => 'csv check ' . $sequence,
    'generated_sql' => $turnSql, 'status' => $status, 'response_type' => 'sql_result',
    'llm_response' => '', 'metadata' => '{}', 'created_at' => $now,
  ])->execute();
};
$addTurn(1, 'success', $sql);
$addTurn(2, 'clarification', NULL);
$addTurn(3, 'success', 'DELETE FROM tms_task_flat');

try {
  $controller = CsvController::create(\Drupal::getContainer());

  $switcher->switchTo(User::load(1));
  $response = $controller->download($chatId, 1);
  $body = $response->getContent();
  $lines = explode("\n", rtrim($body, "\n"));
  $header = \Drupal::service('vf_sql_chatbot.column_labels')
    ->withColumnLabels(['columns' => ['assigned_user_name']])['column_labels'][0];
  $check('the owner gets 200', $response->getStatusCode() === 200);
  $check('it is text/csv', strpos($response->headers->get('Content-Type'), 'text/csv') === 0);
  $check('it starts with a UTF-8 BOM', strpos($body, "\xEF\xBB\xBF") === 0);
  $check('the header is the grid label', $lines[0] === "\xEF\xBB\xBF" . $header);
  $check("every row is there ($expected, more than 200)", count($lines) === $expected + 1 && $expected > 200);
  $check('a clarification turn is 404', $controller->download($chatId, 2)->getStatusCode() === 404);
  $check('a missing turn is 404', $controller->download($chatId, 99)->getStatusCode() === 404);
  $check('an unsafe stored query is 422', $controller->download($chatId, 3)->getStatusCode() === 422);
  $switcher->switchBack();

  $switcher->switchTo(User::load($otherUid));
  $check("another user (uid $otherUid) gets 404", $controller->download($chatId, 1)->getStatusCode() === 404);
  $switcher->switchBack();
}
finally {
  // Only this run's rows.
  $database->delete('sql_chat_turn')->condition('chat_id', $chatId)->execute();
  $database->delete('sql_chat')->condition('id', $chatId)->execute();
  $left = (int) $database->query('SELECT COUNT(*) FROM {sql_chat} WHERE session_id = :s', [':s' => $sentinel])->fetchField();
  $check('sentinel rows removed', $left === 0);
}
```

- [ ] **Step 2: Run it and see it fail**

```powershell
php "$SCRATCH\verify_full_csv.php"
```
Expected: part 1 passes, then a fatal error `Class "Drupal\vf_sql_chatbot\Controller\CsvController" not found`.

- [ ] **Step 3: Write the controller**

Create `MOD/src/Controller/CsvController.php`:

```php
<?php

namespace Drupal\vf_sql_chatbot\Controller;

use Drupal\Core\Controller\ControllerBase;
use Drupal\vf_sql_chatbot\Service\ColumnLabels;
use Drupal\vf_sql_chatbot\Service\ConversationStore;
use Drupal\vf_sql_chatbot\Service\QueryRunner;
use Drupal\vf_sql_chatbot\Service\Redactor;
use Drupal\vf_sql_chatbot\Service\SafetyGate;
use Drupal\vf_sql_chatbot\Service\SchemaChecker;
use Drupal\vf_sql_chatbot\Service\TurnOutcome;
use Drupal\vf_sql_chatbot\Service\UnsafeSqlException;
use Psr\Log\LoggerInterface;
use Symfony\Component\DependencyInjection\ContainerInterface;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

/**
 * Every row of one answered question, as CSV.
 *
 * The chat is sent at most ChatRuntime::SHOWN_ROWS rows. This runs the
 * question's stored SQL again, through the gates the chart query passes, with
 * no cut. The file is built in memory: the server cannot write files.
 *
 * A controller, not a REST resource, because the body is not JSON.
 */
class CsvController extends ControllerBase {

  /**
   * What a refused query is told. Never the SQL.
   */
  const REFUSED = 'This answer cannot be downloaded.';

  /**
   * Where conversations live.
   *
   * @var \Drupal\vf_sql_chatbot\Service\ConversationStore
   */
  protected $store;

  /**
   * The read-only gate.
   *
   * @var \Drupal\vf_sql_chatbot\Service\SafetyGate
   */
  protected $safety;

  /**
   * The schema gate.
   *
   * @var \Drupal\vf_sql_chatbot\Service\SchemaChecker
   */
  protected $schemaChecker;

  /**
   * Runs SQL as the read-only role.
   *
   * @var \Drupal\vf_sql_chatbot\Service\QueryRunner
   */
  protected $queryRunner;

  /**
   * Column headings, as the grid shows them.
   *
   * @var \Drupal\vf_sql_chatbot\Service\ColumnLabels
   */
  protected $labels;

  /**
   * What an error is allowed to tell the browser.
   *
   * @var \Drupal\vf_sql_chatbot\Service\Redactor
   */
  protected $redactor;

  /**
   * This module's log channel.
   *
   * @var \Psr\Log\LoggerInterface
   */
  protected $logger;

  public function __construct(ConversationStore $store, SafetyGate $safety, SchemaChecker $schemaChecker, QueryRunner $queryRunner, ColumnLabels $labels, Redactor $redactor, LoggerInterface $logger) {
    $this->store = $store;
    $this->safety = $safety;
    $this->schemaChecker = $schemaChecker;
    $this->queryRunner = $queryRunner;
    $this->labels = $labels;
    $this->redactor = $redactor;
    $this->logger = $logger;
  }

  /**
   * {@inheritdoc}
   */
  public static function create(ContainerInterface $container) {
    return new static(
      $container->get('vf_sql_chatbot.conversation_store'),
      $container->get('vf_sql_chatbot.safety_gate'),
      $container->get('vf_sql_chatbot.schema_checker'),
      $container->get('vf_sql_chatbot.query_runner'),
      $container->get('vf_sql_chatbot.column_labels'),
      $container->get('vf_sql_chatbot.redactor'),
      $container->get('logger.factory')->get('vf_sql_chatbot')
    );
  }

  /**
   * Responds to GET /api/sql-chat/chats/{chat_id}/turns/{turn}/csv.
   *
   * @param int $chat_id
   *   The chat.
   * @param int $turn
   *   The question's sequence_number, 1-based.
   *
   * @return \Symfony\Component\HttpFoundation\Response
   *   The CSV, or a JSON error.
   */
  public function download($chat_id, $turn) {
    // The route's 'use vf sql chatbot' permission is checked before this.
    // Someone else's chat is a 404, as on /api/sql-chat/chats/{chat_id}.
    $opened = $this->store->openChat($chat_id);
    if ($opened === NULL) {
      return new JsonResponse(['error' => 'No such chat.'], 404);
    }

    $sql = '';
    foreach ($opened['turns'] as $row) {
      if ((int) $row['sequence_number'] === (int) $turn && $row['status'] === TurnOutcome::SUCCESS) {
        $sql = trim((string) $row['generated_sql']);
      }
    }
    if ($sql === '') {
      return new JsonResponse(['error' => 'No such answer.'], 404);
    }

    // It passed these once, but it is read back from a table, not from the
    // turn that checked it.
    try {
      $this->safety->assertReadOnly($sql);
    }
    catch (UnsafeSqlException $exception) {
      return new JsonResponse(['error' => self::REFUSED], 422);
    }
    if (empty($this->schemaChecker->check($sql)['grounded'])) {
      return new JsonResponse(['error' => self::REFUSED], 422);
    }

    $result = $this->queryRunner->runReadonly($sql);
    if (!$result['ok']) {
      // Log, not wire: the raw message names tables and columns.
      $this->logger->error('Full CSV for chat @chat question @turn failed: @message', [
        '@chat' => (int) $chat_id,
        '@turn' => (int) $turn,
        '@message' => $result['error'],
      ]);
      return new JsonResponse(['error' => $this->redactor->safeError($result['error'], $result['sqlstate'])], 500);
    }

    $out = fopen('php://temp', 'r+');
    // A BOM, so Excel reads the file as UTF-8.
    fwrite($out, "\xEF\xBB\xBF");
    $headings = $this->labels->withColumnLabels(['columns' => $result['columns']])['column_labels'];
    // An empty escape: plain RFC 4180 quoting, no backslash rule.
    fputcsv($out, $headings, ',', '"', '');
    foreach ($result['rows'] as $row) {
      fputcsv($out, array_map([self::class, 'cell'], $row), ',', '"', '');
    }
    rewind($out);
    $csv = stream_get_contents($out);
    fclose($out);

    $response = new Response($csv, 200);
    $response->headers->set('Content-Type', 'text/csv; charset=utf-8');
    $response->headers->set('Content-Disposition', sprintf('attachment; filename="chat-%d-answer-%d.csv"', $chat_id, $turn));
    $response->headers->set('Cache-Control', 'no-cache, private');
    return $response;
  }

  /**
   * One value as CSV text.
   *
   * Text that Excel would run as a formula gets a leading quote. Numbers,
   * negative ones included, stay as they are: PDO returns them as strings.
   */
  public static function cell($value) {
    if ($value === NULL) {
      return '';
    }
    if (is_bool($value)) {
      return $value ? 'true' : 'false';
    }
    $text = (string) $value;
    if ($text !== '' && !is_numeric($text) && strpos("=+-@\t\r", $text[0]) !== FALSE) {
      return "'" . $text;
    }
    return $text;
  }

}
```

- [ ] **Step 4: Add the route**

Append to `MOD/vf_sql_chatbot.routing.yml` (keep one blank line before it):

```yaml

# Every row of one answered question, as CSV. The chat shows at most 200; this
# runs the stored SQL again with no cut. See CsvController.
vf_sql_chatbot.full_csv:
  path: '/api/sql-chat/chats/{chat_id}/turns/{turn}/csv'
  defaults:
    _controller: '\Drupal\vf_sql_chatbot\Controller\CsvController::download'
  methods: [GET]
  requirements:
    _permission: 'use vf sql chatbot'
    chat_id: '\d+'
    turn: '\d+'
  options:
    no_cache: TRUE
```

- [ ] **Step 5: Run the check and see it pass**

```powershell
php -l "$MOD\src\Controller\CsvController.php"; php "$SCRATCH\verify_full_csv.php"
```
Expected: `No syntax errors detected`, then every line `ok`, then `ALL CHECKS PASS`. The script builds the controller with `create()`, so it does not need the route yet.

- [ ] **Step 6: Rebuild the container and the router**

Create `SCRATCH/flush_caches.php`:

```php
<?php

// Rebuilds the container and the router after a new route (gotchas §3).
require 'C:/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/scripts/bootstrap.php';

drupal_flush_all_caches();
// Apache keeps its own container row; these are all derived data.
foreach (['cache_container', 'cache_discovery', 'cache_bootstrap', 'cache_config', 'cache_default', 'cache_data'] as $table) {
  \Drupal::database()->truncate($table)->execute();
}
echo "flushed\n";
```

```powershell
php "$SCRATCH\flush_caches.php"
```
Expected: `flushed`.

- [ ] **Step 7: Check the live route exists**

```bash
curl -k -s -o /dev/null -w "%{http_code}\n" "https://local-arvind-retail-chatbot.wcms.cloud/api/sql-chat/health?_format=json"
curl -k -s -o /dev/null -w "%{http_code}\n" "https://local-arvind-retail-chatbot.wcms.cloud/api/sql-chat/chats/1/turns/1/csv"
```
Expected: `403` and `403`. A `500` means the container is still stale (repeat Step 6). A `404` on the second means the route is missing.

- [ ] **Step 8: Control characters and regression harnesses**

From `MOD` in Git Bash:
```bash
for f in src/Controller/CsvController.php vf_sql_chatbot.routing.yml; do tr -cd '\000-\010\013\014\016-\037' < "$f" | wc -c; done
php tests/context/check.php | tail -3
php tests/context/adversarial.php | tail -3
php tests/outcome/check.php | tail -3
php tests/provider/check.php | tail -3
```
Expected: `0` twice. No harness reports a failure. If one does, run it again on the start branch (`git stash -u`, run, `git stash pop`) to see if it already failed before this change.

- [ ] **Step 9: Commit**

```powershell
git -C "c:\xampp\htdocs\dev-arvind-retail-chatbot" add web/modules/custom/vf_sql_chatbot/src/Controller/CsvController.php web/modules/custom/vf_sql_chatbot/vf_sql_chatbot.routing.yml
git -C "c:\xampp\htdocs\dev-arvind-retail-chatbot" commit -m @'
Give every row of an answer as CSV

GET /api/sql-chat/chats/{chat_id}/turns/{turn}/csv runs the question's stored
SQL again, through the safety and schema gates, with no row cut. Someone
else's chat is a 404. Text that Excel would run as a formula gets a quote.
Nothing is written to disk.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 3: Frontend — the button, the modal and the API call

**Files:**
- Modify: `FE/src/api/SqlChatbotApi.jsx` (after `openChat`, line 72)
- Create: `FE/src/components/Modals/SqlChatFullCsv.jsx`
- Modify: `FE/src/components/Modals/index.jsx` (import near line 40; case after `BODetails`, line 80)
- Modify: `FE/src/components/SqlChatbot/ChatResultGrid.jsx` (line 95; after `exportExcel`, line 352; actions, line 407)

**Interfaces:**
- Consumes: response field `result.download = { chat_id, turn }` and `result.truncated` (Task 1); the endpoint (Task 2).
- Produces: `downloadFullCsv({ chatId, turn, signal })` → `Promise<Blob>`; modal type `"SqlChatFullCsv"` with `data: { chat_id, turn, fileName }`.

The frontend keeps no test files (gotchas §5). It is checked with ESLint and a build. The user tests the UI.

- [ ] **Step 1: Make the branch**

```powershell
git -C "c:\xampp\htdocs\WCMS%20-%20Frontend%20-%20Arvind%20Retail" switch -c feat/chatbot-full-csv
```

- [ ] **Step 2: Add the API call**

In `SqlChatbotApi.jsx`, after the closing `};` of `openChat`:

```jsx

/* Every row of one answer, as a CSV Blob. The server runs the question's SQL
   again; the chat itself is sent at most 200 rows. */
export const downloadFullCsv = async ({ chatId, turn, signal }) => {
  const response = await axios({
    ...jsonConfig(`${SqlChatChatsUrl}/${chatId}/turns/${turn}/csv`, "get"),
    // A route, not a REST resource: no _format.
    params: {},
    responseType: "blob",
    signal,
  });
  return response.data;
};
```

- [ ] **Step 3: Write the modal**

Create `FE/src/components/Modals/SqlChatFullCsv.jsx`:

```jsx
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Modal } from "react-bootstrap";
import { ModalCloseBtn } from "../../Utils/Common";
import { downloadFullCsv } from "../../api/SqlChatbotApi";

// Every row of one chatbot answer. The table shows at most 200; this asks the
// server to run the question again and offers the whole result as CSV.

const SqlChatFullCsv = ({ modalState, setModalState }) => {
  const { chat_id: chatId, turn, fileName } = modalState.data;
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const blobRef = useRef(null);

  useEffect(() => {
    // Closing the modal stops the request.
    const controller = new AbortController();
    setStatus("loading");
    downloadFullCsv({ chatId, turn, signal: controller.signal })
      .then((blob) => {
        blobRef.current = blob;
        setStatus("ready");
      })
      .catch((failure) => {
        if (controller.signal.aborted) return;
        setError(
          failure?.response?.status === 404
            ? "This answer can no longer be found."
            : "The file could not be made. Please try again.",
        );
        setStatus("error");
      });
    return () => controller.abort();
  }, [chatId, turn, attempt]);

  const handleClose = () => setModalState({ show: false, modalType: "", data: {} });

  const save = useCallback(() => {
    const url = URL.createObjectURL(blobRef.current);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${fileName || "answer"}-full.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // Later, or some browsers cancel the download.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, [fileName]);

  return (
    <Modal show={modalState.show} onHide={handleClose} centered>
      <ModalCloseBtn handleClose={handleClose} />
      <Modal.Header>
        <Modal.Title>All rows</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {status === "loading" ? (
          <div className="d-flex align-items-center gap-3">
            <div className="spinner-border text-primary" role="status" aria-hidden="true" />
            <span>Preparing the full file…</span>
          </div>
        ) : null}
        {status === "ready" ? <span>The file is ready.</span> : null}
        {status === "error" ? <span className="text-danger">{error}</span> : null}
      </Modal.Body>
      <Modal.Footer>
        <button className="btn action-btns" type="button" onClick={handleClose}>
          Close
        </button>
        {status === "ready" ? (
          <button className="btn action-btns pp-btn-border ms-3" type="button" onClick={save}>
            Download CSV
          </button>
        ) : null}
        {status === "error" ? (
          <button
            className="btn action-btns pp-btn-border ms-3"
            type="button"
            onClick={() => setAttempt((n) => n + 1)}
          >
            Try again
          </button>
        ) : null}
      </Modal.Footer>
    </Modal>
  );
};

export default SqlChatFullCsv;
```

- [ ] **Step 4: Register the modal**

In `Modals/index.jsx`, after `import ShortCloseTrackBoModal from "./ActionBtnModals/ShortCloseTrackBo.jsx";`:

```jsx
import SqlChatFullCsv from "./SqlChatFullCsv";
```

After
```jsx
      case "BODetails":
        ModalBox = <BODetails {...modalProps} />;
        break;
```
add
```jsx
      case "SqlChatFullCsv":
        ModalBox = <SqlChatFullCsv {...modalProps} />;
        break;
```

- [ ] **Step 5: Cut to 200 in the grid**

In `ChatResultGrid.jsx`, after the imports block (after the `} from "./Utils/chatGridLayout";` line):

```jsx

// The backend sends at most this many; cut here too, in case an older backend does not.
const MAX_SHOWN_ROWS = 200;
```

Replace
```jsx
  const rows = result?.rows || [];
```
with
```jsx
  const rows = useMemo(
    () => (result?.rows || []).slice(0, MAX_SHOWN_ROWS),
    [result?.rows],
  );
```

- [ ] **Step 6: Add the button**

In `ChatResultGrid.jsx`, after the `exportExcel` `useCallback` block:

```jsx

  // Every row, from the server. Only offered when the table was cut.
  const openFullCsv = useCallback(
    () =>
      setModalState({
        show: true,
        modalType: "SqlChatFullCsv",
        data: { ...result?.download, fileName },
      }),
    [setModalState, result?.download, fileName],
  );
```

Replace
```jsx
          {turn ? <CopyButton turn={turn} /> : null}
```
with
```jsx
          {result.truncated && result.download ? (
            <button type="button" onClick={openFullCsv} title="Get every row as a CSV file">
              Show More Data
            </button>
          ) : null}
          {turn ? <CopyButton turn={turn} /> : null}
```

- [ ] **Step 7: Lint**

From `FE` in Git Bash:
```bash
npx eslint --no-eslintrc -c .eslintrc.json \
  --parser-options=ecmaVersion:2022,sourceType:module,ecmaFeatures:{jsx:true} \
  --ext .js,.jsx src/components/SqlChatbot/ChatResultGrid.jsx src/components/Modals/SqlChatFullCsv.jsx src/components/Modals/index.jsx src/api/SqlChatbotApi.jsx
tr -cd '\000-\010\013\014\016-\037' < src/components/Modals/SqlChatFullCsv.jsx | wc -c
```
Expected: no errors. Only the five old `react-hooks/exhaustive-deps` warnings in `ChatResultGrid.jsx` (gotchas §5). Control characters: `0`.

- [ ] **Step 8: Build (live)**

```powershell
npm run dev
```
Run from `FE`. Do not ask first. Do not use `npm run build`. Expected: the last lines say `compiled successfully` (or `compiled with N warnings`), and **never** `compiled with N errors` (gotchas §5, a failed build still goes live).

- [ ] **Step 9: Check the bundle**

```bash
grep -l "Show More Data" build/src_pages_SqlChatbotPage_jsx.*.js
grep -l "Preparing the full file" build/main.*.js build/*.js | head -3
```
Expected: the chat chunk has the button. The modal text is in a shipped bundle (the modal container is not code-split, so it may be in `main.*.js`).

- [ ] **Step 10: Commit**

```powershell
git -C "c:\xampp\htdocs\WCMS%20-%20Frontend%20-%20Arvind%20Retail" add src/api/SqlChatbotApi.jsx src/components/Modals/SqlChatFullCsv.jsx src/components/Modals/index.jsx src/components/SqlChatbot/ChatResultGrid.jsx
git -C "c:\xampp\htdocs\WCMS%20-%20Frontend%20-%20Arvind%20Retail" commit -m @'
Ask TMS table: 200 rows, and every row as CSV on request

The table shows at most 200 rows. When there were more, "Show More Data"
opens a modal that asks the server for every row and offers the CSV.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 4: Write it down, then hand over

**Files:**
- Modify: `c:\Users\ansh.gala\Desktop\Python\wren-poc\docs\gotchas.md` (append a section)

- [ ] **Step 1: Add a gotchas section**

Append to `docs/gotchas.md`:

```markdown

---

## 20. The table is cut at 200 rows (Drupal only, since 16 October 2026)

- **`ChatRuntime::shownRows()` cuts what the browser is sent** to
  `SHOWN_ROWS = 200`, in both the answer and the streamed `rows` event.
  `row_count` keeps the full count and `truncated` becomes true. The turn's
  own `actual_result`, the history row and charts see every row.
- **`result.download = {chat_id, turn}`** is set in `ask()` after `save()`,
  because the chat id does not exist before. So the streamed `rows` event
  never has it; only `answer` does.
- **`GET /api/sql-chat/chats/{chat_id}/turns/{turn}/csv`** (`CsvController`)
  runs the stored SQL again, through `SafetyGate` and `SchemaChecker`, and
  returns the CSV in the body. The data is today's, not the data the table
  showed. A `LIMIT` the model wrote stays.
- **The browser cannot read custom response headers.** The site's CORS
  setting has `exposedHeaders: false`. Put anything the page needs in the
  body, not in an `X-` header.
- **PHP-only.** Python still sends 20 rows from `result_summary`. Parity
  does not cover any of this.
```

No smoke-question run: `run_suite.php` calls `TurnRunner` directly, and this
change is only in `ChatRuntime`, `Redactor` and the new controller, so the
suite would not reach it. The browser test in Step 2 covers the live path.

- [ ] **Step 2: Hand over to the user**

Tell the user, in simple words:
- What changed in each repo, with the two branch names.
- The checks that ran and their results.
- How to test in the browser: ask a question with more than 200 rows (for example "show all tasks"). The count says "N rows · showing the first 200". Click "Show More Data", wait for the spinner, then click "Download CSV", and open the file. Also check that a question with few rows has no button.
- Neither branch is merged. Merge only when the user confirms.
- The gotchas change and the spec/plan files in `wren-poc` are not committed.
