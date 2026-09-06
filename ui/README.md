# QA console

A human testing console for the SQL chatbot. Ask questions the way a user
would, and see what the system decided on every turn.

Plain HTML, CSS and JavaScript. No build step, no dependencies, no framework.

## Run it

Open `ui/index.html` in a browser. That is the whole setup.

It starts in **mock mode**, so every flow works before a backend exists. The
mock is not invented: each fixture is a real turn lifted from
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

## Connect your backend

One file, one function: `sendMessageToBackend()` in [api.js](api.js).

1. Set `ENDPOINT` at the top of `api.js`.
2. Untick **use mock responses** in the header.

The full request and response contract is documented in the comment block at
the top of that file. Every response field is optional — anything missing
renders as `-` rather than breaking the page — so you can wire it up
incrementally and watch fields fill in.

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
