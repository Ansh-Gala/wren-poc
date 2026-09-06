# QA console

A human testing console for the SQL chatbot. Ask questions the way a user
would, and see what the system decided on every turn.

Plain HTML, CSS and JavaScript. No build step, no dependencies, no framework.

## Run it against the real system

```bash
python scripts/serve_api.py
```

Then open <http://localhost:8000/>. The console is served by the same process
that answers it, so it is same-origin — there is no CORS to configure — and it
starts in **live** mode, asking real questions of the real database.

Every request goes through `benchmark.lean_runner.run_turn`, the same function
the four benchmark suites run, with no expected SQL to compare against. There
is deliberately no second pipeline: a console running its own copy of the logic
would drift from the thing being measured, and would then be showing you
something other than what the benchmark reports.

The provider comes from `.env`, the same as the suites — `LLM_PROVIDER=cli`
and `CLI_LEAN=true`. Anything else is refused at startup with a message saying
so, rather than failing three seconds into your first question.

```bash
python scripts/serve_api.py --port 9000
python scripts/serve_api.py --context-mode none    # A/B the context layer by hand
```

## Run it without a backend

Open `ui/index.html` straight off disk. It starts in **mock mode**, so every
flow works before anything is running. (Served from the API server, untick
*use mock responses* to get the same thing.)

The mock is not invented: each fixture is a real turn lifted from
`results/followup_v2/raw/turns.jsonl`, so the SQL, row counts, suggestion ids
and token figures are what the system actually produced. A mock with
plausible-looking made-up fields would hide exactly the mismatches this page
exists to catch.

Flows worth trying:

| Type | What it exercises |
|---|---|
| `Show AR_YD_Suiting items` → `only active` → `only black` → `how many?` | filters stacking across a thread |
| `Show the AR_YD items` → click a chip | clarification, then the answer resolved back into the original question |
| `show the AR_YD_Suiting itmes` | typo repair, shown as original → normalized |
| `Show my open tasks` mid-thread | new-topic detection; the old filters must not leak |
| `What is the total revenue?` | a measure the schema does not hold |
| `Show tasks whose SLA status is Breached` | a value the column does not take, with the real values offered |
| `fail now` | the error state |

## Connect a different backend

One file, one function: `sendMessageToBackend()` in [api.js](api.js).

`ENDPOINT` resolves to whoever served the page when that is an HTTP server, and
falls back to `http://localhost:8000/ask` when the file was opened from disk.
Edit that line to point somewhere else.

The full request and response contract is documented in the comment block at
the top of that file, and [scripts/serve_api.py](../scripts/serve_api.py) is a
worked implementation of it — 300 lines of standard library, no framework.
Every response field is optional, and anything missing renders as `-` rather
than breaking the page, so a new backend can be wired up incrementally with the
panel filling in as it goes.

Two fields deserve a note:

- **`state`** is the conversation-level object shown in the right-hand rail.
  Send the whole thing on every turn. The console keeps no opinion of its own
  about what the state is; it shows what the backend last said it was, which is
  the only way a debugging view can be trusted.
- **`semantic_match` / `result_match` / `projection_verdict`** only mean
  anything against a known-correct answer. Omit them in production and the
  panel shows `n/a` — which is deliberately different from `no`.

## Layout

```
┌────────────────────────────────────────┬─────────────────────┐
│ mode badge · tags · latency            │ CONVERSATION STATE  │
│ clarification / error                  │  entity, tables,    │
│ ┌────────────────────────────────────┐ │  filters, grouping, │
│ │ generated SQL                      │ │  sorting, limit,    │
│ └────────────────────────────────────┘ │  intent, prev sql   │
│ result preview                         │                     │
│ [ suggestion chips ]                   │ PENDING QUESTION    │
│ ▸ debug — this request                 │ LAST MUTATIONS      │
│     understanding / query / scoring    │ SESSION TOTALS      │
│     follow-up / cost / mutations       │                     │
├────────────────────────────────────────┤                     │
│ input                          [Send]  │                     │
└────────────────────────────────────────┴─────────────────────┘
```

Request-level information lives inside each turn; conversation-level state
lives in the rail. That split is the point — a filter that leaks between turns
shows up in the rail, and a query that went wrong shows up in the turn.

## Files

| File | Role |
|---|---|
| `index.html` | Structure |
| `styles.css` | Presentation |
| `api.js` | **The only file that talks to a backend.** Contract documented inline |
| `mock.js` | Recorded fixtures, so the console works before the backend does |
| `app.js` | Chat, per-turn debug, state rail |

## Controls

- **Enter** sends, **Shift+Enter** newlines
- **Reset context** — next question starts a new thread; nothing carries over
- **Clear chat** — wipes the transcript and the session counters too
- Chips send their label as the next message and pass their structured
  `action` alongside, so the backend need not re-derive what was clicked
- Free text always still works, whether or not chips are on offer
