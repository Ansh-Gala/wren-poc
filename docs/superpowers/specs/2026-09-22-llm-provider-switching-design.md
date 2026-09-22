# Choosing the model from a page, not a script

Date: 2026-09-22
Status: approved, not yet built

## The problem

Switching the chatbot between the local Claude CLI and an HTTP API means
editing a row in the `vf_config` table by hand. There is no page for it, the
only other API provider is Anthropic, and once a question has been answered
nothing records which model answered it.

This adds three things:

1. An admin page for picking the mode, the provider and the model.
2. OpenAI, Gemini and Groq as usable providers.
3. The mode and model shown in the debug panel and stored against every turn.

## What is already true

Worth knowing, because it keeps the change small.

- `ResponseParser` tries five strategies to find SQL in a reply: JSON keys,
  fenced blocks, bare SELECT, and so on. It does not assume a Claude-shaped
  answer, so a non-Claude model has a fair chance without prompt changes.
- `ChatRuntime::debug()` merges each turn's `metadata` blob into the debug
  payload. A field a provider reports arrives in the browser with no
  plumbing.
- `Redactor` is a whitelist applied when debug is **off**. With debug on,
  nothing is stripped. So new debug fields need no whitelist entry.
- About a dozen other custom modules on this site have working
  `ConfigFormBase` settings pages. The "config save fatals" note in
  `scripts/set_claude_command.php` describes a CLI-only breakage (Drush
  command discovery), not a web request.

## Decisions

### One generic provider, not three

OpenAI, Groq and Gemini all accept the OpenAI chat-completions request shape;
Gemini exposes an OpenAI-compatible endpoint alongside its native one. One
class, `OpenAiCompatibleProvider`, serves all three, differing only in base
URL and model name.

Rejected: a class per provider. Three near-identical files that have to be
kept in step, for no gain, because nothing here needs a native-only feature.

### Site-wide, set by an admin

One setting for the whole site, not a per-user picker on the chat page. A
per-user picker would mean the browser sends the mode, which needs its own
permission checks, and it is not what is being asked for.

### Keys come from the environment, never from the form

API keys are read with `getenv()` from the project `.env`, which
`web/sites/sites.php` already loads through Symfony Dotenv with
`usePutenv()`, and which `.gitignore` already covers. No key is ever stored
in Drupal config, so no key can reach a `drush cex` export, a config YAML
file, or the database.

The form therefore has no key fields at all. It shows, per provider, whether
a key was found. That is the whole of it.

Safe with CLI mode: `ClaudeCliProvider::environment()` already unsets
`ANTHROPIC_API_KEY` before launching the subprocess, so an Anthropic key in
`.env` cannot quietly turn local Claude Code auth into billed API calls.

### Model lists come from the provider, not from us

Every one of the four exposes a list-models endpoint. None of the four
exposes pricing; OpenAI has been asked for a pricing endpoint and has none.
So the dropdown is filled live and cached, and no price is ever printed.

A hardcoded list would be wrong almost immediately. This repository already
ships `claude-sonnet-4-5` as a default, a generation behind, and nobody
noticed.

Context window is shown where the provider reports it:

    Anthropic   GET /v1/models          max_input_tokens, max_tokens
    Gemini      GET /v1beta/models      inputTokenLimit, outputTokenLimit
    Groq        GET /openai/v1/models   context_window
    OpenAI      GET /v1/models          nothing but the id

## The design

### 1. Admin page

Route `/admin/config/system/sql-chatbot-llm`, form
`Drupal\vf_sql_chatbot\Form\LlmSettingsForm`, permission
`administer vf sql chatbot`. Routing, menu link and permission follow
`vf_bold_bi_dashboard`, which is the nearest existing example.

Fields:

- **Mode** - radios, `cli` or `api`.
- **API provider** - select: Anthropic, OpenAI, Gemini, Groq. Ignored while
  mode is `cli`.
- **Model, per provider** - a select filled from that provider's cached model
  list, plus an "other" textfield for a model too new to be listed.
- **Refresh models** - one submit button per provider. It calls that
  provider's list endpoint with the key from the environment and caches the
  answer for 24 hours. It doubles as the key test: a bad key fails here with
  the provider's own words, rather than silently breaking the next question.
- **Key status, read only** - "found in the environment" or "not found",
  naming the variable to set.

Environment variables read:

    ANTHROPIC_API_KEY
    OPENAI_API_KEY
    GEMINI_API_KEY
    GROQ_API_KEY

Config keys, all under `vf_sql_chatbot.settings`:

    llm_provider          cli | api      (existing key, reused)
    api_provider          anthropic | openai | gemini | groq
    models.anthropic      a model id
    models.openai
    models.gemini
    models.groq

The existing `anthropic_model` is migrated into `models.anthropic` by the
update hook. The existing `anthropic_api_key` is deleted, because keys no
longer live in config; a site relying on it moves the value into `.env`.

### 2. Provider layer

New `Drupal\vf_sql_chatbot\Llm\OpenAiCompatibleProvider`, implementing the
existing `LlmProviderInterface`. Like `AnthropicApiProvider`, it reads the
selected provider from config inside `ask()` rather than taking it as a
constructor argument, so it needs one service definition and no new
constructor parameter. Base URLs are a constant map in the class.

`ProviderFactory::get()` becomes: `cli` returns `ClaudeCliProvider`; `api`
reads `api_provider` and returns `AnthropicApiProvider` for `anthropic` or
`OpenAiCompatibleProvider` otherwise. An unknown value still throws.

`ClaudeCliProvider` and `AnthropicApiProvider` change only as described next.

One more service, `Service\ModelCatalog`: given a provider name it returns that
provider's model list, from `cache.default` if it is fresh and from the
provider's endpoint otherwise. It owns the four endpoint shapes and
normalises them to `[id, label, context]`, so neither the form nor the
providers know that Gemini spells it `inputTokenLimit`. A failed fetch
returns the reason, which the form shows.

### 3. Reporting mode and model

Every provider adds two keys to the run array it already returns:

- `mode` - `cli` or `api`
- `model` - the model id actually sent, or for the CLI the configured
  `claude_model`

`ConversationStore::metadataFor()` copies both into the metadata blob, which
puts them in the debug payload with no further change.

### 4. Debug panel

`DebugDetails.jsx` gains a group, rendered first:

    Model
      Mode      api
      Provider  openai
      Model     gpt-4o

Read through the existing `show()` helper, so a turn without them renders an
em dash rather than breaking.

### 5. Database

Two columns on `sql_chat_turn`:

    llm_mode    varchar(32)   what answered: cli or api
    llm_model   varchar(64)   the model id

Their own columns rather than a corner of `metadata`, because the point is to
be able to group and count by them. `recordTurn()` writes both. Rows written
before this change keep NULL; nothing is backfilled, because nothing knows
what answered them.

Added by `vf_sql_chatbot_update_9005()` alongside the config migration, so one
update does the whole change.

### 6. Tests

Parity is untouched: no prompt text changes, so `tests/parity/check.php` must
still report PARITY HOLDS, unchanged.

New backend tests:

- `ProviderFactory` returns the expected class for each combination of
  `llm_provider` and `api_provider`, and throws on an unknown one.
- `recordTurn()` writes `llm_mode` and `llm_model`.
- `OpenAiCompatibleProvider` maps a chat-completions response onto the run
  array, and turns a non-2xx into a failed run without leaking the key.
- `ModelCatalog` normalises each of the four list shapes to the same
  `[id, label, context]`, and reports a failure rather than throwing.

No UI tests. The debug panel is checked by looking at it.

Remember to add every new `src/Service/*.php` and `src/Llm/*.php` class to the
hand-written require list in `tests/context/check.php`,
`tests/context/adversarial.php` and `tests/parity/check.php`, or those
harnesses fatal with "class not found".

## Known consequences

These are accepted, not open questions.

**Cost changes shape.** The Claude CLI and the Anthropic API both cache the
system prompt, which inlines about 24 KB of schema. OpenAI, Gemini and Groq
will be billed that 24 KB as fresh input on every question. The per-question
bill on those providers is not comparable to the Claude one.

**Answer quality is unmeasured.** The prompt is written for Claude and is
locked byte-for-byte against the Python. Other models will probably produce
usable SQL, given how tolerant the parser is, but nobody has measured it.
`scripts/run_suite.php` is the way to find out, once this exists.

**A key in `.env` is readable by anything running as the web user.** That is
the same exposure the database password already has, and it is the reason
the keys are not also copied into config, where a config export would spread
them further.

## Out of scope

- A separate "test this key" button. "Refresh models" already proves the
  key works, because it fails with the provider's own error if it does not.
- Any per-provider prompt. All providers get the same prompt, from the same
  `PromptBuilder`, so the two repos cannot drift.
- Changing anything in the Python repo. This is Drupal and frontend only.
- Backfilling `llm_mode` and `llm_model` on old turns.
