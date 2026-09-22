# Choosing the model from a page, not a script

Date: 2026-09-22
Status: approved, not yet built

## The problem

Switching the chatbot between the local Claude CLI and an HTTP API means
editing a row in the `vf_config` table by hand. There is no page for it, the
only other API provider is Anthropic, and once a question has been answered
nothing records which model answered it.

This adds three things:

1. An admin page for picking the mode, the provider, the model and the key.
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

### All four providers visible at once, no AJAX

The form shows a model field and a key field for every provider, whichever
one is selected. Switching provider never loses a key or a model name, and
the form needs no JavaScript.

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
- **Per provider** - a model textfield and an API key password field, for
  each of the four.

A saved key renders as "saved", never as its value. An empty key field on
submit leaves the stored key alone, so saving the form does not wipe keys.

Config keys, all under `vf_sql_chatbot.settings`:

    llm_provider              cli | api          (existing key, reused)
    api_provider              anthropic | openai | gemini | groq
    providers.anthropic.model
    providers.anthropic.api_key
    providers.openai.model
    providers.openai.api_key
    providers.gemini.model
    providers.gemini.api_key
    providers.groq.model
    providers.groq.api_key

The existing `anthropic_api_key` and `anthropic_model` keys are migrated into
`providers.anthropic.*` by the update hook and then removed, so there is one
place to look rather than two.

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

**Keys live in Drupal config.** A `drush cex` writes them into YAML files.
`anthropic_api_key` already carries this risk. The form will carry a line
saying that production keys belong in a `settings.php` config override.

## Out of scope

- A "test this key" button on the form.
- Any per-provider prompt. All providers get the same prompt, from the same
  `PromptBuilder`, so the two repos cannot drift.
- Changing anything in the Python repo. This is Drupal and frontend only.
- Backfilling `llm_mode` and `llm_model` on old turns.
