# Rows first, the rest a moment later

## The measurement this exists to act on

The reply is one JSON object and the contract puts `sql` first in it. Measured
on the Claude CLI with `--include-partial-messages`, across three questions:

| question | first token | sql complete | last token | gap after sql |
|---|---|---|---|---|
| open tasks for AR_YD_Suiting | 4.53s | 5.56s | 8.06s | 2.50s |
| initiatives by status | 8.14s | 8.64s | 10.24s | 1.60s |
| initiative type with most items | 3.94s | 4.73s | 6.69s | 1.96s |
| **mean** | 5.53s | 6.31s | 8.33s | **2.02s** |

Two seconds of every turn is spent generating `explanation`, `goal`, `recap`,
`next` and `group` — after the SQL is already known and the query could
already have run. The gap does not depend on process startup, so it is a real
saving on any transport.

Applied to the best recorded run — `results/after_meta`, 3.74s at 100%
accuracy — the table would land at roughly 1.7s.

The same holds on the API transport. `results/2026-09-23/ttft_luna_low.json`:
sql complete at 1.28s, last token at 2.01s.

## What changes

Nothing about what the model produces. Only when the caller stops waiting for
it. The rich answer that scored 100% in `after_meta` is kept whole.

## Design

### 1. The provider streams, by callback

`LLMProvider.ask` gains an optional `on_delta(text)`. It is called with each
text fragment as it arrives and is ignored by any caller that does not pass
one, so every existing call site is unchanged.

- **Claude CLI**: `--include-partial-messages` makes the CLI emit
  `stream_event` envelopes carrying `content_block_delta`. Verified present in
  this build. The flag is added unconditionally: the pooled read loop already
  skips event types it does not recognise, so a non-streaming caller pays only
  a little more stdout traffic and one pool serves both.
- **The pool**: `_converse` already reads events off a queue on the caller's
  thread. It gains one branch. Process management is untouched — still one
  question per process.
- **OpenAI**: `stream=True` on the lean branch, accumulating `choices[0].delta`.

A callback rather than a generator, because the pool's read loop is already a
loop over a queue and a generator would mean either threading it or inverting
that loop. Neither buys anything.

### 2. The runner acts at the SQL mark

`run_turn` gains an optional `on_sql(payload)`. When set, it passes an
`on_delta` down to the provider that accumulates the reply and watches for the
close of the `sql` value — the same scanner `scripts/probe_ttft.py` uses,
moved to `claude/parser.py` so there is one implementation and it stays tested.

At that mark, still on the provider's thread:

1. the SQL is parsed out of the partial reply
2. the existing schema-grounding check and safety gate run on it, unchanged
3. the query executes and the result is put in a per-turn memo
4. `on_sql` is called with the rows

The stream keeps arriving into the queue while the query runs, so the
execution overlaps the remaining generation rather than following it.

**The memo is what keeps this surgical.** `run_turn` has three `run_readonly`
call sites and only two execute the generated SQL (`lean_runner.py:604` and
`:677`; `:651` runs the ground-truth SQL, which a live turn does not have).
Those two consult the memo first. The scored pipeline is otherwise untouched,
which matters because it is what the accuracy figures were measured on.

Without the memo the choice would be between restructuring `run_turn` — 857
lines, and the thing every recorded accuracy number was produced by — or
running the user's query twice. Neither is worth it for 300ms.

**A reply with no SQL** — a clarification — never reaches the mark. The
scanner returns `None` for it (already tested), `on_sql` is never called, and
the turn finishes exactly as it does today. The endpoint must send its single
`answer` event rather than wait for rows that are not coming.

### 3. The endpoint sends two events

`POST /ask` is untouched, so the console, the mock and every existing caller
keep working.

`POST /ask/stream` is new and sends Server-Sent Events:

```
event: rows
data: {"generated_sql": ..., "result": {...}, "error": ..., "sql_valid": ...}

event: answer
data: <exactly what POST /ask returns today>
```

`rows` is omitted when the turn clarifies. `answer` always arrives, and is the
same payload as today — so a client may ignore `rows` entirely and behave as
it does now. Debug redaction applies to both events, by the same
`public_response` the existing path uses: a field the browser receives has
already left the server.

## Out of scope

- **The UI.** Backend only this session.
- **Drupal.** Under PHP-FPM every request spawns a fresh CLI, roughly 4s
  before the first token exists. Streaming would save 2s of tail with 4s of
  silence in front of it. Part 2 of `docs/latency-report-and-drupal-plan.md`
  has to land there first.

## Success criteria

1. `POST /ask` returns byte-identical responses to today for the same input.
2. `POST /ask/stream` sends `rows` before `answer` for a question that
   produces SQL, and `answer` alone for one that clarifies.
3. The query runs once per turn, not twice — asserted on the memo.
4. The full Python test suite shows no failures beyond the 27 that already
   fail on this branch.
5. Measured on the console: the `rows` event arrives roughly 2s before
   `answer`, matching the table above.
