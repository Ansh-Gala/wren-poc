# Drupal Module Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reimplement the whole text-to-SQL chatbot as a Drupal 10 module in PHP, with no Python at runtime.

**Architecture:** The Python pipeline's shape carries over one service per module: repair, classify, prompt, provider, parse, safety, execute, follow-up, orchestrate. The one part that cannot carry over is `sqlglot`: PHP has no Postgres-dialect SQL AST. Everywhere the Python reads a parsed tree, the PHP asks PostgreSQL instead — `EXPLAIN (VERBOSE, FORMAT JSON)` inside a `READ ONLY` transaction, which yields relations, filters, group keys and sort keys, and which fails with `42P01`/`42703` when the model invents a name. Conversation state moves from an in-process dict to Drupal's expirable key-value store, keyed by user.

**Tech Stack:** Drupal 10.2+, PHP 8.1+, PDO PostgreSQL, `symfony/yaml` (already in core), the `claude` CLI via `proc_open`, the Anthropic Messages API via core's Guzzle `http_client`, PHPUnit via `core/scripts/run-tests.sh`, vanilla JS/CSS reused verbatim from `ui/`.

## Global Constraints

- **Module machine name:** `ai_sql_chat`. Namespace `Drupal\ai_sql_chat`. Path `web/modules/custom/ai_sql_chat`.
- **Drupal 10.2 or later, PHP 8.1 or later.** Do not use Drupal 11-only APIs.
- **No new Composer dependencies.** `symfony/yaml` ships with core; everything else is core or PHP stdlib.
- **No Python at runtime.** The Python repo is the reference specification, never a dependency.
- **Two provider modes, both required:** `cli` (local Claude Code CLI subprocess) and `api` (Anthropic Messages API over HTTPS). Selected by `llm_provider` in config. Both must produce byte-identical prompts, so they share `PromptBuilder` and differ only in transport.
- **Permission:** `use ai sql chat`. Anonymous users get 403. Conversation state is keyed by `uid` and is private per user.
- **Synchronous requests.** `max_execution_time`, PHP-FPM `request_terminate_timeout` and the CLI timeout must all be at least `180`.
- **The database role used for generated SQL holds `SELECT` and nothing else.** This is not optional; see Task 6 for why it carries more weight here than in the Python version.
- **Every generated statement executes inside `BEGIN; SET TRANSACTION READ ONLY; SET LOCAL statement_timeout = <ms>;`** and is rolled back.
- **Metadata YAML is copied byte-for-byte** from the Python repo's `metadata/` into `ai_sql_chat/metadata/`. It is data, not code. Do not reformat it.
- **Prompt text is copied byte-for-byte** from `claude/prompts.py`'s `LEAN_SYSTEM_PROMPT` and `CONTEXT_GUIDANCE`. Reworded prompts invalidate every accuracy figure on record.
- **Reference repo:** paths like `pipeline/followup.py` below mean that file on the `develop` branch of the Python project. Read it before porting it.

## How to read the port tasks

Tasks 1–8 build new machinery and carry complete code. Tasks 9–13 port existing, already-correct logic; for those the reference Python file **is** the specification, so each task gives the exact target signatures, the exact test cases that must pass, and the named source to port from, rather than restating 500 lines of logic that already exists and is under test. Task 14 is the parity harness that proves the port matches the original — treat it as the real acceptance gate for 9–13.

---

## Phase 0 — De-risk the parser substitution

Everything else is ordinary work. This is the task that decides whether the port is viable at all, so it comes first and it is a hard gate: if `EXPLAIN`-derived state cannot reproduce what `sqlglot` gives, stop and re-plan rather than continuing.

### Task 0: Spike — prove PostgreSQL can replace sqlglot

**Files:**
- Create: `web/modules/custom/ai_sql_chat/spike/explain_probe.php`
- Create: `web/modules/custom/ai_sql_chat/spike/RESULTS.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a go/no-go decision, and the exact JSON paths Task 10 and Task 11 will read. Record them in `RESULTS.md`; later tasks depend on the field names you find, not on the ones guessed here.

- [ ] **Step 1: Write a standalone probe script**

Standalone on purpose — no Drupal bootstrap, so it can be run against production data on any box with PHP and network access to the database.

```php
<?php
// spike/explain_probe.php — run: php explain_probe.php "host=... dbname=..." 
// Answers one question: does EXPLAIN give us everything parse_sql_state and
// check_against_schema currently read out of a sqlglot tree?
declare(strict_types=1);

$dsn = $argv[1] ?? 'pgsql:host=localhost;dbname=postgres';
$user = getenv('PGUSER') ?: 'postgres';
$pass = getenv('PGPASSWORD') ?: '';

$pdo = new PDO($dsn, $user, $pass, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);

/** Plan a statement without running it, inside a read-only transaction. */
function plan(PDO $pdo, string $sql): array {
    $pdo->exec('BEGIN');
    try {
        $pdo->exec('SET TRANSACTION READ ONLY');
        $pdo->exec('SET LOCAL statement_timeout = 5000');
        $row = $pdo->query('EXPLAIN (VERBOSE, FORMAT JSON) ' . $sql)->fetchColumn();
        $pdo->exec('ROLLBACK');
        return ['ok' => true, 'plan' => json_decode($row, true)];
    } catch (PDOException $e) {
        $pdo->exec('ROLLBACK');
        return ['ok' => false, 'sqlstate' => $e->errorInfo[0] ?? '', 'message' => $e->getMessage()];
    }
}

$cases = [
    'plain filter' =>
        "SELECT business_object_id FROM tms_business_object_flat WHERE business_object_type = 'AR_YD_Suiting'",
    'group and order' =>
        "SELECT assigned_user_name, COUNT(*) AS n FROM tms_task_flat GROUP BY assigned_user_name ORDER BY n DESC LIMIT 5",
    'two filters and a join' =>
        "SELECT t.task_id FROM tms_task_flat t JOIN tms_user_flat u ON u.user_id = t.assigned_user_id
         WHERE t.task_sla_status = 'Delayed' AND u.user_status = 'ACTIVE'",
    'invented column' =>
        "SELECT profit_margin FROM tms_task_flat",
    'invented table'  =>
        "SELECT 1 FROM tms_nonexistent_flat",
    'a write'         =>
        "INSERT INTO tms_task_flat (task_id) VALUES (1)",
    'two statements'  =>
        "SELECT 1; DROP TABLE tms_task_flat",
    'cte'             =>
        "WITH d AS (SELECT * FROM tms_task_flat WHERE task_sla_status = 'Delayed') SELECT COUNT(*) FROM d",
];

foreach ($cases as $label => $sql) {
    echo str_repeat('=', 70), "\n", $label, "\n";
    $r = plan($pdo, $sql);
    echo json_encode($r, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), "\n";
}
```

- [ ] **Step 2: Run it against the real database**

Run: `PGPASSWORD=... php spike/explain_probe.php "pgsql:host=localhost;dbname=<your db>"`

Expected, and each of these is a requirement rather than a hope:
- `plain filter` — plan contains `Relation Name: tms_business_object_flat` and a `Filter` string containing `business_object_type` and `AR_YD_Suiting`.
- `group and order` — plan contains `Group Key` and `Sort Key` arrays, and a `Limit` node with `Plan Rows`.
- `two filters and a join` — **both** relations appear, and both filters are recoverable (they may sit on different plan nodes, which is the thing to check).
- `invented column` — `ok: false`, `sqlstate: 42703`, message naming `profit_margin`.
- `invented table` — `ok: false`, `sqlstate: 42P01`, message naming `tms_nonexistent_flat`.
- `a write` — either `ok: false` under the read-only transaction, or a plan whose `Node Type` is `ModifyTable`. Note which.
- `two statements` — must error. PostgreSQL's extended protocol rejects multiple statements; confirm it does here.
- `cte` — the CTE's underlying relation is discoverable.

- [ ] **Step 3: Write down the field paths and the gaps**

Create `spike/RESULTS.md` recording, verbatim from your output: the JSON path to relation names, to `Filter`, to `Group Key`, to `Sort Key`, to the `Limit` node, and the `sqlstate` plus the regex that extracts the offending identifier from each error message.

Then record the gaps honestly. Two are known in advance and must be measured, not assumed:

1. **Filter strings are rewritten by the planner.** The Python stores `business_object_type = 'AR_YD_Suiting'`; `EXPLAIN` will report something like `(business_object_type = 'AR_YD_Suiting'::text)`. Task 10 has to normalise. Write down the exact shape you see, including casts and parentheses.
2. **The planner may drop or fold predicates** — a constant-false filter, a filter satisfied by an index condition (`Index Cond` rather than `Filter`). Record every key under which a predicate appeared across your cases.

- [ ] **Step 4: Decide, in writing**

Add a `## Verdict` section to `RESULTS.md`: `GO` or `NO-GO`, with the reason.

`NO-GO` if any of these is true: filters are unrecoverable for joined queries, multiple statements are not rejected, or invented names do not produce a distinguishable sqlstate. If `NO-GO`, **stop and report** — the fallback options are a PHP FFI binding to `libpg_query`, or keeping the Python service for SQL analysis only, and both change the plan enough to need re-approval.

- [ ] **Step 5: Commit**

```bash
git add web/modules/custom/ai_sql_chat/spike/
git commit -m "spike: probe whether EXPLAIN can replace the sqlglot AST"
```

---

## Phase 1 — A working shell

Ends with a real Drupal page, permission-gated, rendering the real UI against canned answers. Deliberately before any pipeline work, so the plumbing is proven while it is still cheap to change.

### Task 1: Module skeleton, permission, settings

**Files:**
- Create: `ai_sql_chat.info.yml`
- Create: `ai_sql_chat.permissions.yml`
- Create: `ai_sql_chat.routing.yml`
- Create: `ai_sql_chat.links.menu.yml`
- Create: `config/schema/ai_sql_chat.schema.yml`
- Create: `config/install/ai_sql_chat.settings.yml`
- Create: `src/Form/SettingsForm.php`
- Test: `tests/src/Functional/SettingsFormTest.php`

**Interfaces:**
- Consumes: nothing.
- Produces: config object `ai_sql_chat.settings` with keys `claude_command` (string), `claude_model` (string), `claude_timeout` (int, seconds), `db_host`, `db_port`, `db_name`, `db_user`, `db_password`, `statement_timeout_ms` (int), `context_mode` (one of `none`, `history`, `state`), `log_turns` (bool). Every later task reads settings through `\Drupal::config('ai_sql_chat.settings')`.

- [ ] **Step 1: Write the failing functional test**

```php
<?php
namespace Drupal\Tests\ai_sql_chat\Functional;

use Drupal\Tests\BrowserTestBase;

/**
 * @group ai_sql_chat
 */
class SettingsFormTest extends BrowserTestBase {

  protected static $modules = ['ai_sql_chat'];
  protected $defaultTheme = 'stark';

  public function testOnlyAdminsReachTheSettingsForm(): void {
    $this->drupalGet('admin/config/ai-sql-chat');
    $this->assertSession()->statusCodeEquals(403);

    $this->drupalLogin($this->drupalCreateUser(['administer site configuration']));
    $this->drupalGet('admin/config/ai-sql-chat');
    $this->assertSession()->statusCodeEquals(200);
  }

  public function testSettingsRoundTrip(): void {
    $this->drupalLogin($this->drupalCreateUser(['administer site configuration']));
    $this->submitForm([
      'claude_command' => 'claude',
      'claude_model' => 'sonnet',
      'claude_timeout' => 180,
      'statement_timeout_ms' => 15000,
    ], 'Save configuration');

    $config = $this->config('ai_sql_chat.settings');
    $this->assertSame('sonnet', $config->get('claude_model'));
    $this->assertSame(180, $config->get('claude_timeout'));
  }

  public function testTimeoutBelowTheFloorIsRejected(): void {
    // 180s is a global constraint, not a preference: a shorter timeout kills
    // legitimate questions mid-answer.
    $this->drupalLogin($this->drupalCreateUser(['administer site configuration']));
    $this->drupalGet('admin/config/ai-sql-chat');
    $this->submitForm(['claude_timeout' => 5], 'Save configuration');
    $this->assertSession()->pageTextContains('at least 180');
  }
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `php core/scripts/run-tests.sh --module ai_sql_chat`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the module files**

`ai_sql_chat.info.yml`:

```yaml
name: 'AI SQL Chat'
type: module
description: 'Ask questions in English, get answers from PostgreSQL.'
package: Custom
core_version_requirement: ^10.2 || ^11
configure: ai_sql_chat.settings
```

`ai_sql_chat.permissions.yml`:

```yaml
'use ai sql chat':
  title: 'Use the AI SQL chatbot'
  description: 'Ask questions and see generated SQL and its results.'
  restrict access: TRUE
```

`restrict access: TRUE` because the answer embeds database rows and the SQL that produced them; this is not a public-content permission.

`ai_sql_chat.routing.yml`:

```yaml
ai_sql_chat.settings:
  path: '/admin/config/ai-sql-chat'
  defaults:
    _form: '\Drupal\ai_sql_chat\Form\SettingsForm'
    _title: 'AI SQL Chat'
  requirements:
    _permission: 'administer site configuration'

ai_sql_chat.console:
  path: '/ai-sql-chat'
  defaults:
    _controller: '\Drupal\ai_sql_chat\Controller\ConsoleController::page'
    _title: 'SQL chatbot'
  requirements:
    _permission: 'use ai sql chat'

ai_sql_chat.ask:
  path: '/ai-sql-chat/ask'
  defaults:
    _controller: '\Drupal\ai_sql_chat\Controller\AskController::ask'
  methods: [POST]
  requirements:
    _permission: 'use ai sql chat'
    _csrf_request_header_token: 'TRUE'
```

`_csrf_request_header_token` is what stops a third-party page from spending your LLM budget through a logged-in user's browser. The UI must send `X-CSRF-Token`; Task 3 wires that up.

`config/schema/ai_sql_chat.schema.yml`:

```yaml
ai_sql_chat.settings:
  type: config_object
  label: 'AI SQL Chat settings'
  mapping:
    claude_command: { type: string, label: 'Claude CLI command' }
    claude_model: { type: string, label: 'Model' }
    claude_timeout: { type: integer, label: 'CLI timeout (seconds)' }
    db_host: { type: string, label: 'Database host' }
    db_port: { type: integer, label: 'Database port' }
    db_name: { type: string, label: 'Database name' }
    db_user: { type: string, label: 'Read-only user' }
    db_password: { type: string, label: 'Read-only password' }
    statement_timeout_ms: { type: integer, label: 'Statement timeout (ms)' }
    context_mode: { type: string, label: 'Context mode' }
    log_turns: { type: boolean, label: 'Log every turn' }
```

`config/install/ai_sql_chat.settings.yml`:

```yaml
claude_command: claude
claude_model: sonnet
claude_timeout: 180
db_host: localhost
db_port: 5432
db_name: ''
db_user: ''
db_password: ''
statement_timeout_ms: 15000
context_mode: state
log_turns: true
```

`src/Form/SettingsForm.php`:

```php
<?php
declare(strict_types=1);

namespace Drupal\ai_sql_chat\Form;

use Drupal\Core\Form\ConfigFormBase;
use Drupal\Core\Form\FormStateInterface;

/**
 * Settings for the AI SQL chatbot.
 */
final class SettingsForm extends ConfigFormBase {

  private const TIMEOUT_FLOOR = 180;

  public function getFormId(): string {
    return 'ai_sql_chat_settings';
  }

  protected function getEditableConfigNames(): array {
    return ['ai_sql_chat.settings'];
  }

  public function buildForm(array $form, FormStateInterface $form_state): array {
    $c = $this->config('ai_sql_chat.settings');

    $form['claude_command'] = [
      '#type' => 'textfield',
      '#title' => $this->t('Claude CLI command'),
      '#default_value' => $c->get('claude_command'),
      '#description' => $this->t('Must be executable by the web server user, with a HOME containing its credentials.'),
      '#required' => TRUE,
    ];
    $form['claude_model'] = [
      '#type' => 'textfield',
      '#title' => $this->t('Model'),
      '#default_value' => $c->get('claude_model'),
    ];
    $form['claude_timeout'] = [
      '#type' => 'number',
      '#title' => $this->t('CLI timeout (seconds)'),
      '#default_value' => $c->get('claude_timeout'),
      '#min' => self::TIMEOUT_FLOOR,
    ];
    $form['statement_timeout_ms'] = [
      '#type' => 'number',
      '#title' => $this->t('Statement timeout (ms)'),
      '#default_value' => $c->get('statement_timeout_ms'),
      '#min' => 1000,
    ];
    $form['context_mode'] = [
      '#type' => 'select',
      '#title' => $this->t('Context mode'),
      '#options' => ['none' => 'none', 'history' => 'history', 'state' => 'state'],
      '#default_value' => $c->get('context_mode'),
    ];
    $form['log_turns'] = [
      '#type' => 'checkbox',
      '#title' => $this->t('Log every turn'),
      '#default_value' => $c->get('log_turns'),
    ];

    $form['db'] = [
      '#type' => 'details',
      '#title' => $this->t('Database (read-only role)'),
      '#open' => TRUE,
      '#description' => $this->t('This role must hold SELECT and nothing else.'),
    ];
    foreach (['db_host' => 'Host', 'db_name' => 'Database', 'db_user' => 'User'] as $key => $label) {
      $form['db'][$key] = [
        '#type' => 'textfield',
        '#title' => $this->t('@l', ['@l' => $label]),
        '#default_value' => $c->get($key),
      ];
    }
    $form['db']['db_port'] = [
      '#type' => 'number',
      '#title' => $this->t('Port'),
      '#default_value' => $c->get('db_port'),
    ];
    $form['db']['db_password'] = [
      '#type' => 'password',
      '#title' => $this->t('Password'),
      '#description' => $this->t('Leave blank to keep the stored value.'),
    ];

    return parent::buildForm($form, $form_state);
  }

  public function validateForm(array &$form, FormStateInterface $form_state): void {
    parent::validateForm($form, $form_state);
    if ((int) $form_state->getValue('claude_timeout') < self::TIMEOUT_FLOOR) {
      $form_state->setErrorByName('claude_timeout', $this->t(
        'The CLI timeout must be at least @n seconds; a question routinely takes 5-15 and a cold model call much longer.',
        ['@n' => self::TIMEOUT_FLOOR],
      ));
    }
  }

  public function submitForm(array &$form, FormStateInterface $form_state): void {
    $config = $this->config('ai_sql_chat.settings');
    foreach ([
      'claude_command', 'claude_model', 'claude_timeout', 'statement_timeout_ms',
      'context_mode', 'log_turns', 'db_host', 'db_port', 'db_name', 'db_user',
    ] as $key) {
      $config->set($key, $form_state->getValue($key));
    }
    // Blank means "unchanged", so an admin saving the form does not wipe the
    // password just by not retyping it.
    $password = (string) $form_state->getValue('db_password');
    if ($password !== '') {
      $config->set('db_password', $password);
    }
    $config->save();
    parent::submitForm($form, $form_state);
  }
}
```

- [ ] **Step 4: Run the tests and make them pass**

Run: `php core/scripts/run-tests.sh --module ai_sql_chat`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add web/modules/custom/ai_sql_chat
git commit -m "feat(ai_sql_chat): module skeleton, permission and settings form"
```

### Task 2: Conversation state store

**Files:**
- Create: `src/Conversation/ConversationState.php`
- Create: `src/Conversation/StateStore.php`
- Create: `ai_sql_chat.services.yml`
- Test: `tests/src/Kernel/StateStoreTest.php`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ConversationState` — a mutable value object with public typed properties: `?string $activeEntity`, `array $activeTables`, `array $activeFilters` (column => predicate string), `array $activeGrouping`, `?string $activeSorting`, `?int $activeLimit`, `string $lastIntent`, `?string $previousSql`, `int $turnsInBlock`, `?array $pendingClarification`, `string $pendingQuestion`, `?string $awaitingAnswerTo`. Methods `isEmpty(): bool`, `resetBlock(): void`, `toArray(): array`, `static fromArray(array $a): self`.
  - `StateStore` — service `ai_sql_chat.state_store`, methods `load(int $uid, string $conversationId): ConversationState`, `save(int $uid, string $conversationId, ConversationState $s): void`, `clear(int $uid, string $conversationId): void`.

Ports the dataclass at `pipeline/context.py:100-146`. The field list above must match it exactly; read that file and reconcile before writing code.

- [ ] **Step 1: Write the failing kernel test**

```php
<?php
namespace Drupal\Tests\ai_sql_chat\Kernel;

use Drupal\ai_sql_chat\Conversation\ConversationState;
use Drupal\KernelTests\KernelTestBase;

/**
 * @group ai_sql_chat
 */
class StateStoreTest extends KernelTestBase {

  protected static $modules = ['ai_sql_chat'];

  public function testAnUnknownConversationStartsEmpty(): void {
    $store = $this->container->get('ai_sql_chat.state_store');
    $state = $store->load(1, 'c1');
    $this->assertTrue($state->isEmpty());
    $this->assertNull($state->activeEntity);
  }

  public function testStateSurvivesARoundTrip(): void {
    $store = $this->container->get('ai_sql_chat.state_store');
    $state = new ConversationState();
    $state->activeEntity = 'AR_YD_Suiting';
    $state->activeFilters = ['business_object_type' => "business_object_type = 'AR_YD_Suiting'"];
    $state->lastIntent = 'list';
    $store->save(7, 'c1', $state);

    $back = $store->load(7, 'c1');
    $this->assertSame('AR_YD_Suiting', $back->activeEntity);
    $this->assertSame('list', $back->lastIntent);
    $this->assertArrayHasKey('business_object_type', $back->activeFilters);
  }

  public function testStateIsPrivatePerUser(): void {
    // Two users' conversations must never bleed: the state carries filters
    // derived from rows one of them may not be entitled to see.
    $store = $this->container->get('ai_sql_chat.state_store');
    $mine = new ConversationState();
    $mine->activeEntity = 'mine';
    $store->save(7, 'shared-id', $mine);

    $theirs = $store->load(8, 'shared-id');
    $this->assertTrue($theirs->isEmpty());
  }

  public function testClearForgetsTheConversation(): void {
    $store = $this->container->get('ai_sql_chat.state_store');
    $s = new ConversationState();
    $s->activeEntity = 'x';
    $store->save(7, 'c1', $s);
    $store->clear(7, 'c1');
    $this->assertTrue($store->load(7, 'c1')->isEmpty());
  }
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `php core/scripts/run-tests.sh --module ai_sql_chat --class 'Drupal\Tests\ai_sql_chat\Kernel\StateStoreTest'`
Expected: FAIL — service `ai_sql_chat.state_store` does not exist.

- [ ] **Step 3: Write the state store**

`src/Conversation/StateStore.php`:

```php
<?php
declare(strict_types=1);

namespace Drupal\ai_sql_chat\Conversation;

use Drupal\Core\KeyValueStore\KeyValueExpirableFactoryInterface;

/**
 * Conversation state, keyed by user.
 *
 * The Python version held this in a process dict with a lock per conversation,
 * because a turn takes seconds and mutates the state in place. PHP is
 * share-nothing across requests, so the store is the shared thing instead and
 * the lock has to be explicit -- two overlapping questions on one conversation
 * would otherwise interleave a repair, a classification and a state update,
 * and the resulting context would belong to neither turn.
 *
 * Keyed by uid as well as conversation id: the state carries filters derived
 * from rows, so one user's must never be reachable from another's session.
 */
final class StateStore {

  private const COLLECTION = 'ai_sql_chat.conversation';
  private const TTL = 86400;

  public function __construct(
    private readonly KeyValueExpirableFactoryInterface $keyValueExpirable,
  ) {}

  private function key(int $uid, string $conversationId): string {
    // Conversation ids come from the browser, so they are hashed rather than
    // interpolated: an id of "../7/c1" must not address another user's row.
    return $uid . ':' . hash('sha256', $conversationId);
  }

  public function load(int $uid, string $conversationId): ConversationState {
    $raw = $this->keyValueExpirable->get(self::COLLECTION)
      ->get($this->key($uid, $conversationId));
    return is_array($raw) ? ConversationState::fromArray($raw) : new ConversationState();
  }

  public function save(int $uid, string $conversationId, ConversationState $state): void {
    $this->keyValueExpirable->get(self::COLLECTION)
      ->setWithExpire($this->key($uid, $conversationId), $state->toArray(), self::TTL);
  }

  public function clear(int $uid, string $conversationId): void {
    $this->keyValueExpirable->get(self::COLLECTION)
      ->delete($this->key($uid, $conversationId));
  }
}
```

`ai_sql_chat.services.yml`:

```yaml
services:
  ai_sql_chat.state_store:
    class: Drupal\ai_sql_chat\Conversation\StateStore
    arguments: ['@keyvalue.expirable']
```

Write `ConversationState` with the properties listed under **Interfaces** above, `isEmpty()` returning `$this->previousSql === null && ($this->activeEntity ?? '') === ''`, and `toArray()`/`fromArray()` as plain serialisation with defaults for missing keys so an older stored shape cannot fatal a request.

- [ ] **Step 4: Run the tests and make them pass**

Run: `php core/scripts/run-tests.sh --module ai_sql_chat --class 'Drupal\Tests\ai_sql_chat\Kernel\StateStoreTest'`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add web/modules/custom/ai_sql_chat
git commit -m "feat(ai_sql_chat): per-user conversation state store"
```

### Task 3: The UI, as a Drupal library, against a stub

**Files:**
- Copy: `ui/styles.css` → `css/console.css` (verbatim)
- Copy: `ui/app.js` → `js/app.js` (one edit, below)
- Copy: `ui/api.js` → `js/api.js` (two edits, below)
- Create: `ai_sql_chat.libraries.yml`
- Create: `src/Controller/ConsoleController.php`
- Create: `templates/ai-sql-chat-console.html.twig`
- Create: `src/Controller/AskController.php` (stub)
- Create: `ai_sql_chat.module` (one `hook_theme()`)
- Test: `tests/src/Functional/ConsoleAccessTest.php`

**Interfaces:**
- Consumes: `use ai sql chat` permission and the routes from Task 1.
- Produces: a rendered console at `/ai-sql-chat`, and `POST /ai-sql-chat/ask` returning a fixed JSON answer in the contract documented at the top of `ui/api.js`. Task 13 replaces the stub body and nothing else.

- [ ] **Step 1: Write the failing functional test**

```php
<?php
namespace Drupal\Tests\ai_sql_chat\Functional;

use Drupal\Tests\BrowserTestBase;

/**
 * @group ai_sql_chat
 */
class ConsoleAccessTest extends BrowserTestBase {

  protected static $modules = ['ai_sql_chat'];
  protected $defaultTheme = 'stark';

  public function testAnonymousIsRefused(): void {
    $this->drupalGet('ai-sql-chat');
    $this->assertSession()->statusCodeEquals(403);
  }

  public function testPermittedUserSeesTheConsole(): void {
    $this->drupalLogin($this->drupalCreateUser(['use ai sql chat']));
    $this->drupalGet('ai-sql-chat');
    $this->assertSession()->statusCodeEquals(200);
    $this->assertSession()->elementExists('css', '#messages');
    $this->assertSession()->elementExists('css', '#composer');
  }

  public function testTheMockToggleIsNotShipped(): void {
    // The console must only ever talk to the real backend.
    $this->drupalLogin($this->drupalCreateUser(['use ai sql chat']));
    $this->drupalGet('ai-sql-chat');
    $this->assertSession()->elementNotExists('css', '#use-mock');
  }

  public function testAskRefusesAGetAndRequiresPermission(): void {
    $this->drupalGet('ai-sql-chat/ask');
    $this->assertSession()->statusCodeEquals(403);
  }
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `php core/scripts/run-tests.sh --module ai_sql_chat --class 'Drupal\Tests\ai_sql_chat\Functional\ConsoleAccessTest'`
Expected: FAIL — route has no controller.

- [ ] **Step 3: Copy the assets and make the three edits**

Copy `styles.css` unchanged. Copy `app.js` and `api.js`, then make exactly these edits — the production branch already removed the mock, so there is no toggle to strip:

In `js/api.js`, replace the endpoint constant:

```js
  // Drupal route, same-origin. drupalSettings is emitted by ConsoleController.
  const ENDPOINT = drupalSettings.aiSqlChat.askUrl;
```

and add the CSRF header to the `fetch` call, since the route requires it:

```js
      const res = await fetch(ENDPOINT, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": drupalSettings.aiSqlChat.csrfToken,
        },
```

In `js/app.js`, the file is an IIFE that runs on load; wrap the entry point in a Drupal behavior so it survives BigPipe and AJAX:

```js
Drupal.behaviors.aiSqlChat = {
  attach: function (context) {
    if (context !== document || document.querySelector("#composer").dataset.attached) return;
    document.querySelector("#composer").dataset.attached = "1";
    init();
  }
};
```

Rename the existing top-level IIFE to a named `function init() { ... }` and call it only from the behavior. Do not otherwise touch it — `mockEnabled()` already tolerates the absent toggle.

`ai_sql_chat.libraries.yml`:

```yaml
console:
  version: 1.x
  css:
    theme:
      css/console.css: {}
  js:
    js/api.js: {}
    js/app.js: {}
  dependencies:
    - core/drupal
    - core/drupalSettings
```

`src/Controller/ConsoleController.php`:

```php
<?php
declare(strict_types=1);

namespace Drupal\ai_sql_chat\Controller;

use Drupal\Core\Access\CsrfTokenGenerator;
use Drupal\Core\Controller\ControllerBase;
use Drupal\Core\Url;
use Symfony\Component\DependencyInjection\ContainerInterface;

final class ConsoleController extends ControllerBase {

  public function __construct(private readonly CsrfTokenGenerator $csrfToken) {}

  public static function create(ContainerInterface $container): self {
    return new self($container->get('csrf_token'));
  }

  public function page(): array {
    return [
      '#theme' => 'ai_sql_chat_console',
      '#attached' => [
        'library' => ['ai_sql_chat/console'],
        'drupalSettings' => [
          'aiSqlChat' => [
            'askUrl' => Url::fromRoute('ai_sql_chat.ask')->toString(),
            // The route declares _csrf_request_header_token, so the header
            // must carry a token minted for that path.
            'csrfToken' => $this->csrfToken->get('ai-sql-chat/ask'),
          ],
        ],
      ],
      '#cache' => ['contexts' => ['user'], 'max-age' => 0],
    ];
  }
}
```

The Twig template is the `<header>` and `<main>` of the production `ui/index.html`, unchanged, minus `<!doctype>`, `<html>`, `<head>` and the `<script>` tags. Register the theme hook in `ai_sql_chat.module`:

```php
<?php
declare(strict_types=1);

/**
 * Implements hook_theme().
 */
function ai_sql_chat_theme(): array {
  return ['ai_sql_chat_console' => ['variables' => []]];
}
```

Then the stub `AskController::ask()` returns a `JsonResponse` with a fixed answer: `decision` `new_block`, a `generated_sql` string, `sql_valid` true, `execution_success` true, a `result` with two rows, `followup` `{"type":"none","suggestions":[]}`, and `state`/`state_mutations` from the loaded `ConversationState`. Keys must match the contract at the top of `ui/api.js`.

- [ ] **Step 4: Run the tests, then look at it**

Run: `php core/scripts/run-tests.sh --module ai_sql_chat --class 'Drupal\Tests\ai_sql_chat\Functional\ConsoleAccessTest'`
Expected: PASS, 4 tests.

Then open `/ai-sql-chat` as a permitted user, type a question, and confirm the stub answer renders in the transcript and the right-hand rail.

- [ ] **Step 5: Commit**

```bash
git add web/modules/custom/ai_sql_chat
git commit -m "feat(ai_sql_chat): console page and UI library against a stub endpoint"
```

---

## Phase 2 — Talking to PostgreSQL and to Claude

### Task 4: Read-only query runner

**Files:**
- Create: `src/Database/ReadOnlyRunner.php`
- Create: `src/Database/QueryResult.php`
- Modify: `ai_sql_chat.services.yml`
- Test: `tests/src/Kernel/ReadOnlyRunnerTest.php`

**Interfaces:**
- Consumes: `ai_sql_chat.settings`.
- Produces: service `ai_sql_chat.readonly_runner`, method `run(string $sql): QueryResult`. `QueryResult` has `array $columns`, `array $rows` (list of lists), `?string $error`, `?string $sqlstate`, `int $rowCount`, `float $elapsedMs`. Also `explain(string $sql): array` returning the decoded `EXPLAIN (VERBOSE, FORMAT JSON)` plan, throwing `\PDOException` on failure so callers can read `sqlstate`.

Ports `database/connection.py`. Uses its own PDO connection, **not** Drupal's, because Drupal's connection is the site database with write rights and this one must be the SELECT-only role.

- [ ] **Step 1: Write the failing kernel test**

```php
<?php
namespace Drupal\Tests\ai_sql_chat\Kernel;

use Drupal\KernelTests\KernelTestBase;

/**
 * Needs a reachable PostgreSQL with the tms_* views and a SELECT-only role.
 *
 * @group ai_sql_chat
 * @group ai_sql_chat_integration
 */
class ReadOnlyRunnerTest extends KernelTestBase {

  protected static $modules = ['ai_sql_chat'];

  protected function setUp(): void {
    parent::setUp();
    if (!getenv('AI_SQL_CHAT_TEST_DSN')) {
      $this->markTestSkipped('AI_SQL_CHAT_TEST_DSN is not set.');
    }
  }

  public function testASelectReturnsRows(): void {
    $r = $this->container->get('ai_sql_chat.readonly_runner')->run('SELECT 1 AS one');
    $this->assertNull($r->error);
    $this->assertSame([[1]], $r->rows);
    $this->assertSame(['one'], $r->columns);
  }

  public function testAWriteIsRefusedByTheTransaction(): void {
    $r = $this->container->get('ai_sql_chat.readonly_runner')
      ->run('CREATE TABLE should_not_exist (id int)');
    $this->assertNotNull($r->error, 'a read-only transaction accepted DDL');
  }

  public function testStatementTimeoutIsEnforced(): void {
    $this->config('ai_sql_chat.settings')->set('statement_timeout_ms', 250)->save();
    $r = $this->container->get('ai_sql_chat.readonly_runner')->run('SELECT pg_sleep(5)');
    $this->assertSame('57014', $r->sqlstate, 'expected query_canceled');
  }

  public function testExplainDoesNotExecute(): void {
    // EXPLAIN without ANALYZE plans but does not run, which is what makes it
    // safe to plan a statement before deciding whether to allow it.
    $plan = $this->container->get('ai_sql_chat.readonly_runner')
      ->explain('SELECT pg_sleep(30)');
    $this->assertIsArray($plan);
  }
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `AI_SQL_CHAT_TEST_DSN=... php core/scripts/run-tests.sh --module ai_sql_chat --class 'Drupal\Tests\ai_sql_chat\Kernel\ReadOnlyRunnerTest'`
Expected: FAIL — service missing.

- [ ] **Step 3: Write the runner**

Every statement runs as:

```php
$pdo->exec('BEGIN');
$pdo->exec('SET TRANSACTION READ ONLY');
$pdo->exec('SET LOCAL statement_timeout = ' . $ms);
// ... query ...
$pdo->exec('ROLLBACK');
```

`ROLLBACK` rather than `COMMIT` even on success: nothing should ever be committed by this path, and a rollback makes that structural instead of conventional. Catch `\PDOException` in `run()` and return it in `QueryResult::$error` with `$sqlstate` from `errorInfo[0]`; let `explain()` throw. Connect with `PDO::ATTR_ERRMODE => ERRMODE_EXCEPTION` and `PDO::ATTR_EMULATE_PREPARES => false`.

- [ ] **Step 4: Run the tests and make them pass**

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(ai_sql_chat): read-only query runner with EXPLAIN support"
```

### Task 5: Provider interface, factory, and CLI mode

**Files:**
- Create: `src/Llm/LlmProviderInterface.php`
- Create: `src/Llm/ProviderFactory.php`
- Create: `src/Llm/ClaudeCliProvider.php`
- Create: `src/Llm/ClaudeRun.php`
- Create: `src/Llm/StreamJsonParser.php`
- Modify: `ai_sql_chat.services.yml`
- Test: `tests/src/Unit/StreamJsonParserTest.php`
- Test: `tests/src/Kernel/ClaudeCliProviderTest.php`

**Interfaces:**
- Consumes: `ai_sql_chat.settings`.
- Produces: `LlmProviderInterface` with the single method `ask(string $systemPrompt, string $userPrompt): ClaudeRun` — the whole surface, deliberately, so a second transport cannot drift from the first. Service `ai_sql_chat.llm` is `ProviderFactory::get()`, returning the implementation named by `llm_provider` config (`cli` or `api`) and throwing on an unknown value. `ClaudeRun` has `string $text`, `int $promptTokens`, `int $cacheReadTokens`, `int $cacheWriteTokens`, `int $completionTokens`, `int $toolCallCount`, `float $latencyMs`, `?string $error`, `string $rawOutput`, plus `static failed(string $message): self` returning a run with empty text and `$error` set. `StreamJsonParser::parse(string $stdout): ClaudeRun` is separately testable with no subprocess.

Ports the lean branch of `llm_api/cli_provider.py:45-72` and `parse_stream_json` at `:111`. **Port only the lean branch.** There is no MCP path in this module.

The interface takes a finished system prompt and a finished user prompt and nothing else. The Python signature carried `mcp_config_path` and `privacy_mode` because it had to serve the MCP path too; neither exists here, and leaving them in would invite a second prompt-building route.

- [ ] **Step 1: Write the failing unit test for the parser**

Capture a real `--output-format stream-json` payload first: run the Python project's CLI provider once with `DEBUG=true` and copy the raw stdout into a fixture at `tests/fixtures/stream_json_ok.txt`. Then:

```php
<?php
namespace Drupal\Tests\ai_sql_chat\Unit;

use Drupal\ai_sql_chat\Llm\StreamJsonParser;
use Drupal\Tests\UnitTestCase;

/**
 * @group ai_sql_chat
 */
class StreamJsonParserTest extends UnitTestCase {

  private function fixture(string $name): string {
    return file_get_contents(__DIR__ . '/../../fixtures/' . $name);
  }

  public function testCollectsTextAndTokenCounts(): void {
    $run = StreamJsonParser::parse($this->fixture('stream_json_ok.txt'));
    $this->assertStringContainsString('SELECT', $run->text);
    $this->assertGreaterThan(0, $run->promptTokens);
    $this->assertNull($run->error);
  }

  public function testSurvivesNonJsonNoise(): void {
    // The CLI prints warnings on stderr, but a stray line on stdout must not
    // lose an answer that is otherwise complete.
    $noisy = "not json at all\n" . $this->fixture('stream_json_ok.txt');
    $run = StreamJsonParser::parse($noisy);
    $this->assertStringContainsString('SELECT', $run->text);
  }

  public function testEmptyOutputIsAnErrorNotACrash(): void {
    $run = StreamJsonParser::parse('');
    $this->assertNotNull($run->error);
    $this->assertSame('', $run->text);
  }

  public function testAnErrorResultIsReported(): void {
    $run = StreamJsonParser::parse(
      json_encode(['type' => 'result', 'is_error' => TRUE, 'result' => 'model unavailable']) . "\n"
    );
    $this->assertNotNull($run->error);
    $this->assertStringContainsString('model unavailable', $run->error);
  }
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `./vendor/bin/phpunit web/modules/custom/ai_sql_chat/tests/src/Unit/StreamJsonParserTest.php`
Expected: FAIL — class missing.

- [ ] **Step 3: Write the parser, then the provider**

Parser: split stdout on newlines, `json_decode` each, ignore lines that fail to decode, accumulate `assistant` message text, read `usage` for token counts, count `tool_use` blocks, and treat a `result` event with `is_error` as an error. Return an error when no `result` event was seen at all.

Provider — the part that will actually bite:

```php
<?php
declare(strict_types=1);

namespace Drupal\ai_sql_chat\Llm;

use Drupal\Core\Config\ConfigFactoryInterface;

/**
 * Runs the local Claude Code CLI as a subprocess.
 *
 * The awkward part is not the arguments, it is HOME. The CLI keeps its
 * credentials under $HOME/.claude, and PHP-FPM runs as a user that typically
 * has no home directory and no login session, so the CLI is unauthenticated
 * there even though it works perfectly for the admin who installed it. The
 * fix is a real directory owned by the web server user, populated once by
 * running `claude` as that user, and passed explicitly here -- inheriting the
 * environment is exactly what does not work.
 */
final class ClaudeCliProvider {

  public function __construct(private readonly ConfigFactoryInterface $configFactory) {}

  public function ask(string $systemPrompt, string $userPrompt): ClaudeRun {
    $config = $this->configFactory->get('ai_sql_chat.settings');

    $cmd = [
      $config->get('claude_command'),
      '-p', $userPrompt,
      '--output-format', 'stream-json',
      '--verbose',
      '--system-prompt', $systemPrompt,
      '--tools', '',
      '--permission-mode', 'bypassPermissions',
    ];
    if ($model = $config->get('claude_model')) {
      $cmd[] = '--model';
      $cmd[] = $model;
    }

    $home = $config->get('claude_home') ?: '/var/lib/ai-sql-chat';
    $env = ['HOME' => $home, 'PATH' => getenv('PATH') ?: '/usr/bin:/bin'];

    $descriptors = [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']];
    $started = microtime(TRUE);
    $process = proc_open($cmd, $descriptors, $pipes, NULL, $env);

    if (!is_resource($process)) {
      return ClaudeRun::failed('could not start ' . $config->get('claude_command'));
    }

    fclose($pipes[0]);
    // Non-blocking reads on both pipes: a full stderr buffer with nobody
    // draining it deadlocks the child, and this child can run for minutes.
    stream_set_blocking($pipes[1], FALSE);
    stream_set_blocking($pipes[2], FALSE);

    $deadline = $started + (int) $config->get('claude_timeout');
    $stdout = $stderr = '';
    while (TRUE) {
      $stdout .= stream_get_contents($pipes[1]);
      $stderr .= stream_get_contents($pipes[2]);
      $status = proc_get_status($process);
      if (!$status['running']) {
        break;
      }
      if (microtime(TRUE) > $deadline) {
        proc_terminate($process, 9);
        fclose($pipes[1]);
        fclose($pipes[2]);
        proc_close($process);
        return ClaudeRun::failed('timed out after ' . $config->get('claude_timeout') . 's');
      }
      usleep(50000);
    }
    $stdout .= stream_get_contents($pipes[1]);
    $stderr .= stream_get_contents($pipes[2]);
    fclose($pipes[1]);
    fclose($pipes[2]);
    proc_close($process);

    $run = StreamJsonParser::parse($stdout);
    $run->latencyMs = (microtime(TRUE) - $started) * 1000;
    if ($run->error !== NULL && $stderr !== '') {
      $run->error .= ' | stderr: ' . substr($stderr, 0, 500);
    }
    return $run;
  }
}
```

Add `claude_home` to the config schema, the install config (`/var/lib/ai-sql-chat`) and the settings form.

Pass the command as an **array** to `proc_open`, never a string: the user's question goes in `-p` and a string command would make that a shell injection.

- [ ] **Step 4: Run both test classes**

Expected: unit tests PASS. The kernel test asserts that `ask()` returns a `ClaudeRun` with non-empty `text` for a trivial prompt; skip it unless `AI_SQL_CHAT_TEST_CLI=1`.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(ai_sql_chat): Claude CLI provider and stream-json parser"
```

### Task 5A: API mode

**Files:**
- Create: `src/Llm/ClaudeApiProvider.php`
- Modify: `src/Llm/ProviderFactory.php`
- Modify: `config/schema/ai_sql_chat.schema.yml`, `config/install/ai_sql_chat.settings.yml`, `src/Form/SettingsForm.php`
- Test: `tests/src/Unit/ClaudeApiProviderTest.php`
- Test: `tests/src/Kernel/ProviderFactoryTest.php`

**Interfaces:**
- Consumes: `LlmProviderInterface` and `ClaudeRun` from Task 5; core's `http_client`.
- Produces: `ClaudeApiProvider implements LlmProviderInterface`. New config keys: `api_key` (string), `api_model` (string, default `claude-sonnet-5`), `api_base_url` (string, default `https://api.anthropic.com`), `api_version` (string, default `2023-06-01`).

Simpler than Task 5, not harder: one HTTPS POST, no subprocess, no stream-json framing, and none of the `HOME` trouble that makes the CLI awkward under PHP-FPM. If CLI mode proves painful to operate, this is the mode to deploy.

**Prompt caching is not optional here.** The lean design inlines a ~600-line schema into every system prompt; the CLI gets caching for free, and without it API mode pays full input price on every question. Mark the system block `cache_control: {"type": "ephemeral"}`, which is why `PromptBuilder::systemPrompt()` had to be stable (Task 8) — a prompt that varies never hits the cache.

- [ ] **Step 1: Write the failing unit test**

Inject a mocked Guzzle client so no network is touched:

```php
public function testASuccessfulReplyBecomesAClaudeRun(): void {
  $body = json_encode([
    'content' => [['type' => 'text', 'text' => '{"sql": "SELECT 1"}']],
    'usage' => [
      'input_tokens' => 120, 'output_tokens' => 15,
      'cache_read_input_tokens' => 9000, 'cache_creation_input_tokens' => 0,
    ],
  ]);
  $provider = $this->providerWithResponse(new Response(200, [], $body));
  $run = $provider->ask('system', 'user');

  $this->assertStringContainsString('SELECT 1', $run->text);
  $this->assertSame(120, $run->promptTokens);
  $this->assertSame(15, $run->completionTokens);
  $this->assertSame(9000, $run->cacheReadTokens);
  $this->assertNull($run->error);
}

public function testTheSystemBlockIsMarkedCacheable(): void {
  // Without this the schema is re-billed on every question.
  $request = $this->captureRequest();
  $this->assertSame('ephemeral', $request['system'][0]['cache_control']['type']);
}

public function testAnHttpErrorBecomesAnErrorNotAnException(): void {
  // A bad turn must not take the page down.
  $provider = $this->providerWithResponse(new Response(429, [], '{"error":{"message":"rate limited"}}'));
  $run = $provider->ask('system', 'user');
  $this->assertNotNull($run->error);
  $this->assertStringContainsString('rate limited', $run->error);
  $this->assertSame('', $run->text);
}

public function testTheApiKeyNeverAppearsInTheError(): void {
  $provider = $this->providerWithResponse(new Response(401, [], '{"error":{"message":"bad key"}}'));
  $this->assertStringNotContainsString('sk-ant-', (string) $provider->ask('s', 'u')->error);
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./vendor/bin/phpunit web/modules/custom/ai_sql_chat/tests/src/Unit/ClaudeApiProviderTest.php`
Expected: FAIL — class not found.

- [ ] **Step 3: Implement the provider**

`POST {api_base_url}/v1/messages` with headers `x-api-key`, `anthropic-version`, `content-type: application/json`, and a body of `model`, `max_tokens`, `system` (an array with one text block carrying `cache_control`), and `messages` (one user turn). Read `content[0].text` into `ClaudeRun::$text` and map `usage` onto the four token fields. Set `'http_errors' => FALSE` and turn a non-2xx into `ClaudeRun::failed()` carrying the upstream `error.message` — never the request headers, or the key lands in a log.

Timeout comes from `claude_timeout`, the same floor as CLI mode.

- [ ] **Step 4: Write and run the factory test**

Assert `llm_provider: cli` yields `ClaudeCliProvider`, `api` yields `ClaudeApiProvider`, and anything else throws with a message naming the valid values.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(ai_sql_chat): API-mode provider with prompt caching"
```

---

## Phase 3 — The parts that needed sqlglot

### Task 6: Read-only safety gate

**Files:**
- Create: `src/Sql/SafetyGate.php`
- Create: `src/Sql/UnsafeSqlException.php`
- Modify: `ai_sql_chat.services.yml`
- Test: `tests/src/Unit/SafetyGateTest.php`
- Test: `tests/src/Kernel/SafetyGatePlanTest.php`

**Interfaces:**
- Consumes: `ai_sql_chat.readonly_runner` (Task 4) for `explain()`.
- Produces: service `ai_sql_chat.safety_gate`, method `assertReadOnly(string $sql): void`, throwing `UnsafeSqlException` with a message naming what was rejected.

Ports `pipeline/safety.py`. **Read that file first, including its docstring**, because this is the one place where the port is genuinely weaker than the original and the compensation has to be deliberate.

The Python has three layers: an AST gate, a SELECT-only role, and a read-only transaction. Layer 1 was primary — `sqlglot` parses the statement and rejects mutating node types, with a keyword regex as backup so a mis-parse cannot smuggle a write through. **PHP has no equivalent parser, so layer 1 is rebuilt out of four cheaper checks and layers 2 and 3 become load-bearing rather than belt-and-braces.** Task 15 verifies them independently for that reason.

- [ ] **Step 1: Write the failing unit test**

```php
<?php
namespace Drupal\Tests\ai_sql_chat\Unit;

use Drupal\ai_sql_chat\Sql\SafetyGate;
use Drupal\ai_sql_chat\Sql\UnsafeSqlException;
use Drupal\Tests\UnitTestCase;

/**
 * @group ai_sql_chat
 */
class SafetyGateTest extends UnitTestCase {

  private function gate(): SafetyGate {
    // The static checks run without a database; the plan check is a Kernel
    // test because it needs one.
    return new SafetyGate(NULL);
  }

  /** @dataProvider writes */
  public function testWritesAreRejected(string $sql): void {
    $this->expectException(UnsafeSqlException::class);
    $this->gate()->assertReadOnly($sql);
  }

  public static function writes(): array {
    return [
      ['INSERT INTO tms_task_flat (task_id) VALUES (1)'],
      ['UPDATE tms_task_flat SET task_id = 2'],
      ['DELETE FROM tms_task_flat'],
      ['DROP TABLE tms_task_flat'],
      ['TRUNCATE tms_task_flat'],
      ['ALTER TABLE tms_task_flat ADD COLUMN x int'],
      ['CREATE TABLE t (id int)'],
      ['GRANT ALL ON tms_task_flat TO PUBLIC'],
      ['COPY tms_task_flat FROM \'/etc/passwd\''],
      // Stacked statements: the classic way past a first-token check.
      ['SELECT 1; DROP TABLE tms_task_flat'],
      ['SELECT 1;DROP TABLE tms_task_flat'],
      // A comment must not be able to hide the real statement.
      ['/* SELECT */ DELETE FROM tms_task_flat'],
      ['SELECT 1 -- \nUNION SELECT 1; UPDATE tms_task_flat SET task_id=1'],
    ];
  }

  /** @dataProvider reads */
  public function testReadsAreAllowed(string $sql): void {
    $this->gate()->assertReadOnly($sql);
    $this->addToAssertionCount(1);
  }

  public static function reads(): array {
    return [
      ['SELECT 1'],
      ['SELECT * FROM tms_task_flat WHERE task_sla_status = \'Delayed\''],
      ['WITH d AS (SELECT 1) SELECT * FROM d'],
      ['SELECT 1; '],
      // A trailing semicolon and whitespace is one statement, not two.
      ["SELECT count(*) FROM tms_task_flat;\n"],
      // Words that merely look dangerous inside a string literal are fine --
      // this is the false positive a naive regex produces.
      ["SELECT * FROM tms_task_flat WHERE task_name = 'delete the old one'"],
      ["SELECT * FROM tms_task_flat WHERE task_name = 'DROP'"],
    ];
  }
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `./vendor/bin/phpunit web/modules/custom/ai_sql_chat/tests/src/Unit/SafetyGateTest.php`
Expected: FAIL — class missing.

- [ ] **Step 3: Implement the four static checks in order**

1. **Strip comments and string literals into a scratch copy.** Remove `--` to end of line, `/* ... */` (non-nested is enough for generated SQL), and the contents of `'...'` (honouring `''` escapes) and `$tag$...$tag$`. Every later check runs on the scratch copy, never the original — this is what makes `WHERE task_name = 'DROP'` pass while `/* SELECT */ DELETE ...` fails.
2. **Reject multiple statements.** On the scratch copy, if a `;` appears with any non-whitespace after it, reject.
3. **Require the first keyword to be `SELECT` or `WITH`.**
4. **Reject the forbidden keyword list as whole words**, copied verbatim from `FORBIDDEN_KEYWORDS` in `pipeline/safety.py`: `INSERT UPDATE DELETE DROP ALTER TRUNCATE CREATE GRANT REVOKE MERGE COPY CALL DO VACUUM REINDEX REFRESH COMMENT SECURITY`.

Then the fifth check, needing a database, in `SafetyGatePlanTest`: call `explain()` and reject if any `Node Type` in the plan tree is `ModifyTable`. Skip it when the runner is `NULL` so the static checks stay unit-testable.

- [ ] **Step 4: Run both classes and make them pass**

Expected: unit PASS (20 cases), kernel PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(ai_sql_chat): read-only safety gate without an AST"
```

### Task 7: Schema check via EXPLAIN

**Files:**
- Create: `src/Sql/SchemaCheck.php`
- Create: `src/Sql/SchemaChecker.php`
- Modify: `ai_sql_chat.services.yml`
- Test: `tests/src/Kernel/SchemaCheckerTest.php`

**Interfaces:**
- Consumes: `ai_sql_chat.readonly_runner`.
- Produces: service `ai_sql_chat.schema_checker`, method `check(?string $sql): SchemaCheck`. `SchemaCheck` has `bool $parsed`, `array $unknownTables`, `array $unknownColumns`, and `hasProblems(): bool`.

Replaces `check_against_schema` at `pipeline/sql_semantics.py:479`. Read its docstring: the point is catching an invented `profit_margin`, because that query fails at execution with an error indistinguishable from any other, so only a name check tells you the model hallucinated rather than the database hiccuped.

Where the Python builds a name index from `metadata/schema_description.yaml` and diffs it against the AST, this asks PostgreSQL, which is strictly more accurate — the database cannot disagree with itself about what columns it has.

- [ ] **Step 1: Write the failing kernel test**

```php
<?php
namespace Drupal\Tests\ai_sql_chat\Kernel;

use Drupal\KernelTests\KernelTestBase;

/**
 * @group ai_sql_chat
 * @group ai_sql_chat_integration
 */
class SchemaCheckerTest extends KernelTestBase {

  protected static $modules = ['ai_sql_chat'];

  protected function setUp(): void {
    parent::setUp();
    if (!getenv('AI_SQL_CHAT_TEST_DSN')) {
      $this->markTestSkipped('AI_SQL_CHAT_TEST_DSN is not set.');
    }
  }

  public function testAValidQueryHasNoProblems(): void {
    $c = $this->container->get('ai_sql_chat.schema_checker')
      ->check('SELECT task_id FROM tms_task_flat');
    $this->assertTrue($c->parsed);
    $this->assertFalse($c->hasProblems());
  }

  public function testAnInventedColumnIsReported(): void {
    $c = $this->container->get('ai_sql_chat.schema_checker')
      ->check('SELECT profit_margin FROM tms_task_flat');
    $this->assertContains('profit_margin', $c->unknownColumns);
    $this->assertSame([], $c->unknownTables);
  }

  public function testAnInventedTableIsReported(): void {
    $c = $this->container->get('ai_sql_chat.schema_checker')
      ->check('SELECT 1 FROM tms_nowhere_flat');
    $this->assertContains('tms_nowhere_flat', $c->unknownTables);
  }

  public function testAnUnknownColumnIsNotReportedWhenTheTableIsAlsoUnknown(): void {
    // The unknown table already explains the unknown column; reporting both
    // would double-count one mistake.
    $c = $this->container->get('ai_sql_chat.schema_checker')
      ->check('SELECT whatever FROM tms_nowhere_flat');
    $this->assertNotEmpty($c->unknownTables);
    $this->assertSame([], $c->unknownColumns);
  }

  public function testAliasesTheQueryDefinesAreNotSchemaNames(): void {
    $c = $this->container->get('ai_sql_chat.schema_checker')
      ->check('SELECT COUNT(*) AS n FROM tms_task_flat ORDER BY n');
    $this->assertFalse($c->hasProblems());
  }

  public function testUnparseableSqlSetsParsedFalseRatherThanThrowing(): void {
    $c = $this->container->get('ai_sql_chat.schema_checker')->check('SELECT FROM WHERE');
    $this->assertFalse($c->parsed);
  }

  public function testNullSqlIsHandled(): void {
    $this->assertFalse($this->container->get('ai_sql_chat.schema_checker')->check(NULL)->parsed);
  }
}
```

- [ ] **Step 2: Run it and watch it fail**

Expected: FAIL — service missing.

- [ ] **Step 3: Implement using sqlstate**

Call `explain($sql)`. On success, no problems. On `\PDOException`, branch on `errorInfo[0]` using the codes and message regexes recorded in `spike/RESULTS.md`:

- `42P01` undefined_table — extract the relation name into `unknownTables`.
- `42703` undefined_column — extract the column name into `unknownColumns`.
- `42601` syntax_error — `parsed = FALSE`.
- anything else — `parsed = FALSE`, and log at warning so an unexpected code is visible rather than silently becoming "unparseable".

PostgreSQL reports the first offending name, not all of them, so `unknownColumns` holds at most one entry where the Python could hold several. That is a real difference and it is acceptable: every consumer treats the field as a boolean "did it hallucinate".

- [ ] **Step 4: Run the tests and make them pass**

Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(ai_sql_chat): schema check via EXPLAIN sqlstates"
```

---

## Phase 4 — Porting the logic

Ports of code that already exists and is already under test. For each, read the named Python file, port it, and make the listed cases pass. Task 14 is the real gate.

### Task 8: Metadata loader and prompt builder

**Files:**
- Copy: `metadata/*.yaml` → `ai_sql_chat/metadata/` (4 files, verbatim)
- Create: `src/Metadata/MetadataRepository.php`
- Create: `src/Prompt/PromptBuilder.php`
- Modify: `ai_sql_chat.services.yml`
- Test: `tests/src/Kernel/PromptBuilderTest.php`

**Interfaces:**
- Produces: service `ai_sql_chat.metadata` with `schemaDescription(): array`, `businessRules(): array`, `questionSqlPairs(): array`, `entityGazetteer(): array`, each cached in `cache.default`. Service `ai_sql_chat.prompt_builder` with `systemPrompt(): string` and `userPrompt(string $question, ?string $context): string`.

Ports `claude/prompts.py`. `systemPrompt()` must reproduce `build_lean_system_prompt()`: `LEAN_SYSTEM_PROMPT` + `CONTEXT_GUIDANCE` + rendered schema + rules + examples, in that order.

- [ ] **Step 1: Write the failing kernel test**

```php
<?php
namespace Drupal\Tests\ai_sql_chat\Kernel;

use Drupal\KernelTests\KernelTestBase;

/**
 * @group ai_sql_chat
 */
class PromptBuilderTest extends KernelTestBase {

  protected static $modules = ['ai_sql_chat'];

  public function testSystemPromptCarriesTheSchema(): void {
    $p = $this->container->get('ai_sql_chat.prompt_builder')->systemPrompt();
    $this->assertStringContainsString('tms_task_flat', $p);
    $this->assertStringContainsString('tms_business_object_flat', $p);
  }

  public function testSystemPromptCarriesRulesAndExamples(): void {
    $p = $this->container->get('ai_sql_chat.prompt_builder')->systemPrompt();
    $this->assertStringContainsString('# SCHEMA', $p);
    $this->assertMatchesRegularExpression('/business rule|BUSINESS RULES/i', $p);
  }

  public function testSystemPromptIsStable(): void {
    // Cached and inlined into every request; if it varies between calls the
    // prompt cache never hits and every question pays full price.
    $b = $this->container->get('ai_sql_chat.prompt_builder');
    $this->assertSame($b->systemPrompt(), $b->systemPrompt());
  }

  public function testSystemPromptNeverContainsRows(): void {
    // Metadata may reach the model; database rows must not.
    $p = $this->container->get('ai_sql_chat.prompt_builder')->systemPrompt();
    $this->assertStringNotContainsString('AR_DummyEve011', $p);
  }

  public function testUserPromptEmbedsTheQuestionAndContext(): void {
    $p = $this->container->get('ai_sql_chat.prompt_builder')
      ->userPrompt('how many tasks?', 'ACTIVE CONVERSATION CONTEXT');
    $this->assertStringContainsString('how many tasks?', $p);
    $this->assertStringContainsString('ACTIVE CONVERSATION CONTEXT', $p);
  }
}
```

- [ ] **Step 2: Run it, watch it fail, then port**

Port the four `_render_*` helpers from `claude/prompts.py`. Keep the rendering compact in the same way — the schema is 583 lines of YAML and the prompt budget is the reason the lean path exists at all.

- [ ] **Step 3: Verify byte-for-byte against Python**

```bash
# In the Python repo:
python -c "from claude.prompts import build_lean_system_prompt as b; open('/tmp/py.txt','w',encoding='utf-8').write(b())"
# In Drupal:
drush php:eval "file_put_contents('/tmp/php.txt', \Drupal::service('ai_sql_chat.prompt_builder')->systemPrompt());"
diff /tmp/py.txt /tmp/php.txt
```

Expected: no differences. Any difference is a change to the prompt, which invalidates the accuracy figures — reconcile it now, not later.

- [ ] **Step 4: Run the tests**

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(ai_sql_chat): metadata repository and lean prompt builder"
```

### Task 9: Response parser

**Files:**
- Create: `src/Llm/ResponseParser.php`
- Create: `src/Llm/ParsedResponse.php`
- Test: `tests/src/Unit/ResponseParserTest.php`

**Interfaces:**
- Produces: `ResponseParser::parse(string $raw): ParsedResponse` with `?string $sql`, `?string $clarification`.

Port of `claude/parser.py` (182 lines). The model is asked for one JSON object, `{"sql": "..."}` or `{"clarify": "..."}`, and does not always comply.

Cases that must pass, each taken from that file's own tests at `tests/test_parser.py`:

```php
['{"sql": "SELECT 1"}', 'SELECT 1', NULL],
['{"clarify": "which user?"}', NULL, 'which user?'],
// Fenced, because models do this regardless of instructions.
["```json\n{\"sql\": \"SELECT 1\"}\n```", 'SELECT 1', NULL],
["```\n{\"sql\": \"SELECT 1\"}\n```", 'SELECT 1', NULL],
// Prose either side of the object.
['Here you go: {"sql": "SELECT 1"} Hope that helps.', 'SELECT 1', NULL],
// Bare SQL with no JSON at all.
['SELECT 1', 'SELECT 1', NULL],
// Neither: not an error, just nothing usable.
['I am not sure.', NULL, NULL],
['', NULL, NULL],
// A trailing semicolon is stripped; multiple statements are not this
// layer's problem -- SafetyGate rejects them.
['{"sql": "SELECT 1;"}', 'SELECT 1', NULL],
```

- [ ] **Step 1: Write the failing unit test**

One `@dataProvider` case per row above: `[$raw, $expectedSql, $expectedClarification]`, asserting both fields on the returned `ParsedResponse`.

- [ ] **Step 2: Run it to verify it fails**

Run: `./vendor/bin/phpunit web/modules/custom/ai_sql_chat/tests/src/Unit/ResponseParserTest.php`
Expected: FAIL — `ResponseParser` not found.

- [ ] **Step 3: Port `claude/parser.py`**

Order matters and is the whole trick: try a strict JSON decode first, then strip a fenced block and retry, then extract the first `{...}` span and retry, and only then fall back to treating the whole output as bare SQL. Return a `ParsedResponse` with both fields `NULL` when nothing is usable — the caller treats that as "the model said nothing actionable", not as an error.

- [ ] **Step 4: Run the tests to verify they pass**

Expected: PASS, 9 cases.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(ai_sql_chat): parse the model's JSON or bare-SQL reply"
```

### Task 10: Conversation state — classify, render, read back

**Files:**
- Create: `src/Conversation/TurnClassifier.php`
- Create: `src/Conversation/ContextRenderer.php`
- Create: `src/Conversation/StateReader.php`
- Modify: `src/Conversation/ConversationState.php`
- Test: `tests/src/Unit/TurnClassifierTest.php`
- Test: `tests/src/Unit/ContextRendererTest.php`
- Test: `tests/src/Kernel/StateReaderTest.php`

**Interfaces:**
- Produces:
  - `TurnClassifier::classify(string $question, ConversationState $s, array $gazetteer): array` returning `[string $decision, ?string $entity]`, decision one of `new_block`, `follow_up`, `switch`, `rebase`, `clarification_response`.
  - `TurnClassifier::isCompleteRequest(string $question): bool` — public, because the turn orchestrator needs it too.
  - `TurnClassifier::detectEntity(string $question, array $gazetteer): ?string`.
  - `ContextRenderer::render(ConversationState $s): string`.
  - `StateReader::read(string $sql): array` with keys `tables`, `filters`, `grouping`, `sorting`, `limit`, `intent`.
  - `ConversationState::update(string $question, ?string $sql, ?array $result, ?string $entity, string $decision): void` — ports `update_state` at `pipeline/context.py:150`. Rewrites the selected-state fields from `$sql` via `StateReader`, bumps or resets `turnsInBlock` according to `$decision`, and sets `previousSql`.

Ports `pipeline/context.py` (468 lines). The largest single port, and two parts of it need care.

**`ContextRenderer` must be ported literally.** It emits the block the model reads, so a reworded heading is a prompt change. In particular `awaitingAnswerTo` renders **first**, before `WHAT IS SELECTED` — the reason is in the comment at `pipeline/context.py:390`: a reply of "both" is only interpretable against the question that prompted it.

**`StateReader` is the second sqlglot replacement.** `parse_sql_state` walks the tree for tables, top-level AND-ed comparison predicates, group keys, sort keys and limit. Rebuild it from `EXPLAIN (VERBOSE, FORMAT JSON)` using the field paths in `spike/RESULTS.md`. Two things it must do that the Python got for free:

- **Normalise the planner's filter strings.** `EXPLAIN` reports `(business_object_type = 'AR_YD_Suiting'::text)`; strip the outer parentheses and `::type` casts so the stored predicate matches what the Python stored. The next turn addresses filters by column name, so the key matters more than the exact text — but the text is rendered into the context the model reads, so it must not be noisy.
- **Collect predicates from every key the spike found them under**, at minimum `Filter`, `Index Cond` and `Recheck Cond`, across all plan nodes, not just the root.

Keep the Python's failure behaviour exactly: `read()` returns the empty shape rather than throwing, because a query the reader cannot understand should degrade the context, not abort the conversation.

Required test cases, ported from `tests/test_context.py` (287 lines) — port all of them, and at minimum:

- A bare fragment continues the block: `"only active"`, `"how many?"`, `"Show their status too"` all classify `follow_up`.
- A question naming its own subject starts a new one: `"Show AR_YD_Suiting items"` classifies `new_block`.
- A question the system asked is carried into the next turn: with `awaitingAnswerTo` set, `render()` contains the question text and the word "answer", and the block appears before the selected-state block.
- `render()` on an empty state returns `''`, but an empty state with `awaitingAnswerTo` set does not.
- `isCompleteRequest()` distinguishes `"Show my active tasks"` from `"Show their status too"` — both four words, so length is not the signal.

- [ ] **Step 1: Write the failing classifier and renderer tests**

`TurnClassifierTest` and `ContextRendererTest` are pure unit tests — no database, no container. Port every case from `tests/test_context.py` before writing any implementation.

- [ ] **Step 2: Run them to verify they fail**

Run: `./vendor/bin/phpunit web/modules/custom/ai_sql_chat/tests/src/Unit/`
Expected: FAIL — classes not found.

- [ ] **Step 3: Port the classifier and the renderer**

Neither needs SQL parsing, so both port almost literally from `pipeline/context.py`. Do them first and get them green before touching `StateReader`; it keeps the one risky piece isolated.

- [ ] **Step 4: Run them green, then commit**

```bash
git commit -am "feat(ai_sql_chat): turn classification and context rendering"
```

- [ ] **Step 5: Write the failing StateReaderTest**

A Kernel test, because it needs `EXPLAIN`. Assert against the same statements used in the Task 0 spike: `tables` for a join contains both relations; `filters` is keyed by column with casts stripped; `grouping`, `sorting` and `limit` are recovered from the GROUP BY / ORDER BY / LIMIT case.

- [ ] **Step 6: Run it red, then implement from `spike/RESULTS.md`**

Walk the whole plan tree, not only the root node, collecting predicates from every key the spike recorded.

- [ ] **Step 7: Compare against the Python reader on identical SQL**

Run the same statement through both and diff the result. Expected: same `tables`, same `filters` keys, same `grouping`, `sorting` and `limit`. Filter *strings* may still differ in punctuation — record any residual difference in `spike/RESULTS.md` rather than leaving it undocumented.

- [ ] **Step 8: Commit**

```bash
git commit -am "feat(ai_sql_chat): read conversation state back out of EXPLAIN"
```

### Task 11: Repair layer

**Files:**
- Create: `src/Repair/Normalizer.php`
- Create: `src/Repair/NormalizeResult.php`
- Create: `src/Repair/Repair.php`
- Create: `src/Repair/Similarity.php`
- Test: `tests/src/Unit/NormalizerTest.php`
- Test: `tests/src/Unit/SimilarityTest.php`

**Interfaces:**
- Produces: service `ai_sql_chat.normalizer`, method `normalize(string $question): NormalizeResult` with `string $question` (repaired) and `Repair[] $repairs`, each `Repair` having `string $original`, `string $corrected`, `string $kind`.

Ports `pipeline/normalize.py` (253 lines). Vocabulary comes from `metadata/schema_description.yaml` — tables, columns and enum values, and nothing else. A general English dictionary would rewrite real column names into common words.

`difflib.SequenceMatcher.ratio()` has no exact PHP equivalent. `similar_text()` is close but not identical, and the module's threshold of `0.82` was tuned against `difflib`. **Port the ratio function explicitly** rather than substituting `similar_text`, then verify against the Python on the same inputs — the comment at `pipeline/normalize.py:33` records that `closed`/`closer` scores `0.83`, which is why both are in the vocabulary and neither is ever rewritten. Reproduce that number or the tuning is meaningless.

Test cases, ported from `tests/test_normalize.py`:

- `"give me my actie task"` → `active`.
- Single transposed or dropped letters are repaired: `itmes`→`items`, `tsaks`→`tasks`, `usres`→`users`, `colur`→`colour`. These score `0.80` against a `0.82` threshold, so distance is measured directly rather than by raising the ratio.
- Query words are never repaired: `"Sort by due date"` must not become `"short by due date"`, and `"Back to the first ones"` must not become `"black to ..."`. Port `_QUERY_WORDS` verbatim; it is a closed list on purpose.
- A typo one letter from a plural is still repaired.

Also port the corpus check from `tests/test_normalize_corpus.py` as a Kernel test if you copy the question suites in; if you do not, say so in the commit message, because that test is how the "never rewrite a correct question" property is actually held.

- [ ] **Step 1: Write the failing SimilarityTest first**

The ratio function is the foundation, and the only part that cannot be eyeballed:

```php
public function testRatioMatchesDifflib(): void {
  // Values taken from difflib.SequenceMatcher on the same pairs. The 0.82
  // threshold in normalize.py was tuned against these exact numbers.
  $this->assertEqualsWithDelta(0.91, Similarity::ratio('actie', 'active'), 0.01);
  $this->assertEqualsWithDelta(0.86, Similarity::ratio('delyaed', 'delayed'), 0.01);
  $this->assertEqualsWithDelta(0.83, Similarity::ratio('closed', 'closer'), 0.01);
  $this->assertEqualsWithDelta(0.80, Similarity::ratio('itmes', 'items'), 0.01);
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./vendor/bin/phpunit web/modules/custom/ai_sql_chat/tests/src/Unit/SimilarityTest.php`
Expected: FAIL — class not found.

- [ ] **Step 3: Port difflib's ratio; do not substitute `similar_text`**

`difflib` computes `2 * M / T`, where `M` is the total matched characters from its recursive longest-matching-block walk and `T` is the sum of both lengths. `similar_text` uses a different recursion and returns different numbers. Port the algorithm, then confirm the four values above before going any further — if they are wrong, every threshold in this task is meaningless.

- [ ] **Step 4: Run it green, then write the failing NormalizerTest**

Port every case from `tests/test_normalize.py`, including the query-word cases: `"Sort by due date"` and `"Back to the first ones"` must come back untouched.

- [ ] **Step 5: Port `pipeline/normalize.py`, run both classes green**

Copy `_QUERY_WORDS` verbatim. It is a closed list on purpose and grows only when a new phrasing collides with a schema term.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(ai_sql_chat): schema-grounded typo repair"
```

### Task 12: Follow-up layer

**Files:**
- Create: `src/Followup/FollowupDecider.php`
- Create: `src/Followup/Followup.php`
- Create: `src/Followup/Action.php`
- Test: `tests/src/Unit/FollowupDeciderTest.php`
- Test: `tests/src/Kernel/FollowupDeciderKernelTest.php`

**Interfaces:**
- Produces: service `ai_sql_chat.followup`, methods `decide(...): Followup`, `clarifyEntity(...): ?Followup`, `resolveClarification(...): ?string`, `applyAction(ConversationState $s, Action $a): void`. `Followup::toArray()` produces `{type, question, suggestions}` where `type` is `clarification`, `exploration` or `none`, and each suggestion carries `{label, action: {type, field, operator, value}}`. `Action::TYPES` is the allowed action-type list.

Ports `pipeline/followup.py` (561 lines). Reads `metadata/schema_description.yaml` and `business_rules.yaml` through `ai_sql_chat.metadata` rather than from disk directly.

The contract that matters: `applyAction` mutates state **before** the turn runs, so the context the model sees already reflects a clicked suggestion, while the label still goes through as the question so the turn takes the ordinary path. Do not add a second way for a query to be built.

Port all cases from `tests/test_followup.py` (307 lines). At minimum:

- A clarification with candidates sets `pendingClarification` and `pendingQuestion`; one without candidates sets `awaitingAnswerTo` instead.
- `resolveClarification` matches a reply against offered candidates and returns the original question with the choice filled in.
- Every suggestion's `action.type` is in `Action::TYPES`; a suggestion with an unusable action is dropped, not rendered.
- `applyAction` on `add_filter` puts the predicate in `activeFilters` keyed by column.

- [ ] **Step 1: Write the failing unit test**

Start with the contract rather than the suggestions: a clarification carrying candidates sets `pendingClarification` and `pendingQuestion`; one without candidates sets `awaitingAnswerTo`. That single distinction is what makes a prose question answerable at all.

- [ ] **Step 2: Run it to verify it fails**

Run: `./vendor/bin/phpunit web/modules/custom/ai_sql_chat/tests/src/Unit/FollowupDeciderTest.php`
Expected: FAIL — class not found.

- [ ] **Step 3: Port `pipeline/followup.py` in four commits**

In this order, committing between each so a regression stays bisectable: the `Followup` and `Action` value objects with `Action::TYPES`; then `applyAction`; then `clarifyEntity` and `resolveClarification`; then `decide` and the suggestion builders last, being the largest and least subtle part.

- [ ] **Step 4: Run both classes green**

The Kernel test covers what reads `schema_description.yaml` and `business_rules.yaml` through `ai_sql_chat.metadata`; the unit test covers the rest from fixtures.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(ai_sql_chat): follow-up layer, clarifications and suggested actions"
```

### Task 13: Turn orchestrator and real endpoint

**Files:**
- Create: `src/Turn/TurnRunner.php`
- Create: `src/Turn/TurnResult.php`
- Modify: `src/Controller/AskController.php` (replace the stub)
- Modify: `ai_sql_chat.services.yml`
- Test: `tests/src/Kernel/TurnRunnerTest.php`
- Test: `tests/src/Functional/AskEndpointTest.php`

**Interfaces:**
- Consumes: every service from Tasks 2, 4, 5, 6, 7, 8, 9, 10, 11, 12.
- Produces: service `ai_sql_chat.turn_runner`, method `run(string $question, ConversationState $s, ?Action $a): TurnResult`. `TurnResult::toResponse(): array` produces exactly the contract at the top of `ui/api.js`.

Ports `run_turn` from `pipeline/lean_runner.py` (618 lines), **minus everything that compares against expected SQL**. There is no ground truth here: `semantic_match`, `result_match`, `behavior_match`, `decision_match` and the rest are scoring fields that a real question has no answer for. Emit them as `null`, exactly as `scripts/serve_api.py:to_response` does — the UI already renders that as "n/a".

Order of operations, from `run_turn`, and it is not arbitrary:

1. Repair the question (`Normalizer`).
2. Resolve a pending clarification, if one is outstanding.
3. Classify the turn (`TurnClassifier`).
4. If a question was asked in prose and this reply is not itself a complete request, force `clarification_response`.
5. Build context per `context_mode`: empty for a fresh block **except** when `awaitingAnswerTo` is set.
6. Ask the model.
7. Parse the response.
8. Schema-check the SQL.
9. Safety-gate the SQL.
10. Execute read-only.
11. Update state from the SQL that actually ran.
12. Attach a follow-up.
13. Clear `awaitingAnswerTo` — it lives for exactly one turn.

Step 11 reads the state back off the executed SQL rather than recording it as it goes. Keep that. A claim about what changed is only trustworthy if it is read off the result.

- [ ] **Step 1: Write the failing kernel test with a stubbed provider**

Replace `ai_sql_chat.llm` in the test container with a fake returning canned JSON, so the orchestration is testable without an LLM. Port the cases from `tests/test_runtime_turn.py` (191 lines):

- A model asking a question is not a failed turn: `{"clarify": "..."}` yields `clarification` set, `failure_category` empty, `followup.type` `clarification`.
- A prose clarification is answerable next turn: ask, get a clarify, then send `"both"` — the prompt for that second turn must contain the original question, and `awaitingAnswerTo` must be `NULL` afterwards.
- Invented SQL is caught: `{"sql": "SELECT profit_margin FROM tms_task_flat"}` sets `hallucinated` true.
- A write is refused before execution: `{"sql": "DELETE FROM tms_task_flat"}` never reaches the database.

- [ ] **Step 2: Run it, watch it fail, then implement**

- [ ] **Step 3: Replace the AskController stub**

Read `question`, `session_id`, `reset_context` and `action` from the JSON body; load state for `$this->currentUser()->id()`; acquire a lock on the conversation key so two overlapping questions cannot interleave; run the turn; save state; return `TurnResult::toResponse()`. Return 400 on a missing question and 500 with `{"error": "..."}` on an unexpected exception — a bad turn must not take the site down.

- [ ] **Step 4: Run the functional test end to end**

Expected: a permitted user POSTs a question and gets the full contract back. Then open `/ai-sql-chat` and ask a real question in the browser.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(ai_sql_chat): turn orchestrator and real ask endpoint"
```

---

## Phase 5 — Prove it matches, then harden

### Task 14: Parity harness against the Python implementation

**Files:**
- Create: `scripts/parity_check.php`
- Create: `tests/fixtures/parity_questions.yaml`
- Create: `PARITY.md`

**Interfaces:**
- Consumes: the finished module, and the Python project reachable locally.
- Produces: a report showing, per question, whether both implementations produced equivalent SQL and identical rows.

This is the acceptance gate for Tasks 9–13, and the reason the port can be trusted at all. The Python implementation is measured; the PHP one is not, and unit tests ported by hand will miss what a corpus catches.

- [ ] **Step 1: Assemble the question set**

Copy the questions out of the Python repo's `benchmark/lean_questions.yaml` and `benchmark/targeted_questions.yaml` into `tests/fixtures/parity_questions.yaml`, preserving conversation grouping — a multi-turn thread has to run as a thread or the context layer is not being tested.

- [ ] **Step 2: Write the harness**

For each conversation, run every turn through both implementations against the same database, then compare: `decision`, `sql_valid`, `execution_success`, `hallucinated`, `followup.type`, and — the one that matters most — the **result rows**, sorted, as the real equivalence test. Two different-looking queries returning identical rows is a pass; identical-looking queries returning different rows is a failure.

- [ ] **Step 3: Run it and write down the number**

Run: `php scripts/parity_check.php --python-endpoint http://127.0.0.1:8000/ask`

Record in `PARITY.md`: total turns, row-level agreement, decision agreement, and every disagreement with both SQL statements side by side.

- [ ] **Step 4: Investigate every disagreement**

Each one is one of: a port bug (fix it), a deliberate difference (record why — `unknownColumns` holding one name instead of several is an example), or an LLM non-determinism (re-run to confirm before dismissing).

**Gate: do not ship below 95% row-level agreement.** The Python's own recorded figure is 114/115 on its suite; a port materially below that is a regression dressed as a migration.

- [ ] **Step 5: Commit**

```bash
git add scripts/parity_check.php tests/fixtures/parity_questions.yaml PARITY.md
git commit -m "test(ai_sql_chat): parity harness against the Python implementation"
```

### Task 15: Verify the layers the AST gate used to cover

**Files:**
- Create: `tests/src/Functional/SecurityPostureTest.php`
- Create: `SECURITY.md`

**Interfaces:**
- Consumes: the finished module.
- Produces: an executable check that the two non-AST layers actually hold.

Task 6 replaced a parser-based gate with static checks plus a plan inspection. That is a weaker layer 1 than the original, which means layers 2 and 3 are now doing work they were previously only backing up. Untested, "the role is read-only" is a belief.

- [ ] **Step 1: Write the test**

```php
<?php
namespace Drupal\Tests\ai_sql_chat\Functional;

use Drupal\Tests\BrowserTestBase;

/**
 * @group ai_sql_chat
 * @group ai_sql_chat_integration
 */
class SecurityPostureTest extends BrowserTestBase {

  protected static $modules = ['ai_sql_chat'];
  protected $defaultTheme = 'stark';

  public function testTheQueryRoleCannotWrite(): void {
    $runner = $this->container->get('ai_sql_chat.readonly_runner');
    foreach ([
      'INSERT INTO tms_task_flat (task_id) VALUES (999999)',
      'DELETE FROM tms_task_flat',
      'CREATE TABLE ai_sql_chat_probe (id int)',
      'DROP TABLE IF EXISTS tms_task_flat',
    ] as $sql) {
      $this->assertNotNull($runner->run($sql)->error, "role accepted: $sql");
    }
  }

  public function testTheRoleHoldsNoGrantsBeyondSelect(): void {
    $r = $this->container->get('ai_sql_chat.readonly_runner')->run("
      SELECT DISTINCT privilege_type FROM information_schema.table_privileges
      WHERE grantee = current_user
    ");
    $this->assertNull($r->error);
    foreach ($r->rows as $row) {
      $this->assertSame('SELECT', $row[0], 'role holds a privilege beyond SELECT');
    }
  }

  public function testAnonymousCannotReachTheEndpoint(): void {
    $this->drupalGet('ai-sql-chat/ask');
    $this->assertSession()->statusCodeEquals(403);
  }

  public function testTheEndpointRequiresACsrfToken(): void {
    // Without this, any page could spend a logged-in user's LLM budget.
    $user = $this->drupalCreateUser(['use ai sql chat']);
    $this->drupalLogin($user);
    $response = $this->getHttpClient()->post(
      $this->buildUrl('ai-sql-chat/ask'),
      ['http_errors' => FALSE, 'json' => ['question' => 'how many tasks?'],
       'cookies' => $this->getSessionCookies()],
    );
    $this->assertSame(403, $response->getStatusCode());
  }

  public function testNoSecretReachesTheRenderedPage(): void {
    $this->config('ai_sql_chat.settings')->set('db_password', 'super-secret-value')->save();
    $this->drupalLogin($this->drupalCreateUser(['use ai sql chat']));
    $this->drupalGet('ai-sql-chat');
    $this->assertSession()->responseNotContains('super-secret-value');
  }
}
```

- [ ] **Step 2: Run it**

Expected: PASS, 5 tests. **A failure here is a release blocker, not a bug to triage.**

- [ ] **Step 3: Write SECURITY.md**

State plainly: the AST gate is gone, what replaced it, and that the SELECT-only role plus the read-only transaction are now primary rather than secondary. Name this test file as the thing that verifies it. Anyone who later relaxes the role needs to find this document.

- [ ] **Step 4: Commit**

```bash
git add web/modules/custom/ai_sql_chat/tests/src/Functional/SecurityPostureTest.php SECURITY.md
git commit -m "test(ai_sql_chat): verify the read-only role and CSRF posture"
```

### Task 16: Operational readiness

**Files:**
- Create: `README.md`
- Create: `src/Commands/AiSqlChatCommands.php` (Drush)
- Modify: `ai_sql_chat.services.yml`
- Create: `drush.services.yml`

**Interfaces:**
- Produces: `drush ai-sql-chat:doctor`, checking every prerequisite and printing what is wrong.

The three operational problems that will actually generate support tickets: the CLI's `HOME`, the timeout stack, and the database role. `doctor` checks all of them.

- [ ] **Step 1: Write the Drush command**

Checks, each printing `OK` or a specific remedy:

1. In `cli` mode: `claude_command` is executable by the current user. Run `claude --version` and report it. In `api` mode: `api_key` is set, and one minimal live call succeeds.
2. In `cli` mode: `claude_home` exists, is owned by the web server user, and contains `.claude`. This is the one that fails in production while working for the admin.
3. `max_execution_time` and the configured `claude_timeout` are both at least 180.
4. The database connects, and the role holds only `SELECT`.
5. All four `metadata/*.yaml` files parse, and `systemPrompt()` builds.

- [ ] **Step 2: Run it on a real host**

Run: `drush ai-sql-chat:doctor`
Expected: every check `OK`, or an actionable remedy.

- [ ] **Step 3: Write the README**

Install, configure, the `HOME` setup with the exact commands, the FPM timeout settings, and the read-only role's `GRANT`. Point at `SECURITY.md` and `PARITY.md`.

- [ ] **Step 4: Commit**

```bash
git add web/modules/custom/ai_sql_chat
git commit -m "feat(ai_sql_chat): doctor command and operator documentation"
```

---

## Effort

18 tasks. Task 0 is a gate; Tasks 10, 12 and 13 are the bulk of the work.

| Phase | Tasks | Estimate |
|---|---|---|
| 0 — parser spike | 0 | 0.5–1 day |
| 1 — working shell | 1–3 | 2–3 days |
| 2 — Postgres and the two providers | 4, 5, 5A | 3–4 days |
| 3 — the sqlglot replacements | 6–7 | 3–4 days |
| 4 — logic ports | 8–13 | 8–12 days |
| 5 — parity and hardening | 14–16 | 3–5 days |
| | | **20–30 working days** |

Roughly **4 to 6 weeks** for one experienced Drupal developer, assuming the spike returns `GO`. Add a week if Task 0 forces the `libpg_query` FFI route.

Task 16's `doctor` command covers both modes: for `cli` it checks the executable and its `HOME`; for `api` it makes one cheap live call and reports the model and whether the cache was read.

For comparison, the proxy approach costs 300–600 lines and days rather than weeks, and keeps `sqlglot` and the existing test suite intact. You have chosen the full rewrite; this plan makes it as safe as it can be, and Tasks 0, 14 and 15 are the three that keep it honest. Do not let them be cut for schedule.

## What this plan does not do

- No benchmark or evaluation harness. Task 14 is a parity check, not a replacement for the Python project's scoring. Keep the Python repo for measuring accuracy.
- No queue. Synchronous by decision; revisit if concurrency rises above a handful of simultaneous users.
- No multi-tenancy beyond per-user state isolation. Every user sees the same database through the same read-only role.
- No `metadata/` generation. Those files are produced on the Python project's `develop` branch and copied here as output.
