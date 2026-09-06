# The follow-up layer

What the system does *around* the SQL: repairing what the user typed, asking
which of several things they meant, and offering a next move.

This document exists to answer one question directly, because it is the
question that decides whether a layer like this is worth having:

> Which steps are deterministic, which use the LLM, and why?

## Short answer

**None of the follow-up layer calls an LLM.** It sometimes *avoids* one.

| Step | Decided by | Why |
|---|---|---|
| Repair a misspelling | Deterministic | Closed vocabulary. It's a string comparison. |
| Classify the turn | Deterministic | The signals are unambiguous; a model call here could itself be wrong. |
| Ask which entity was meant | Deterministic | The gazetteer knows the candidates. A model would invent plausible ones. |
| Explain *why* a question can't be answered | **LLM** | Already happens inside the existing call. No extra round trip. |
| Attach candidates to that explanation | Deterministic | The schema has the values; the model does not reliably. |
| Suggest next moves | Deterministic | Derived from the state and the business registry. |
| Turn a chosen suggestion into a query | **LLM** | The existing pipeline, unchanged. |

The only LLM calls are the ones the system already made. One case removes a
call that used to happen.

## Why not use the LLM for suggestions?

It was the obvious design and it is the wrong one, for a reason that is not
about cost.

A model asked "which order did the user mean?" will answer with order numbers.
They will look right. They will be plausible in exactly the way that makes
them hard to catch — correct format, believable range, consistent with the
domain. And they will be invented, because the model has never seen the table.

Deriving candidates from the gazetteer and the schema makes fabrication
structurally impossible rather than merely unlikely. There is nowhere for a
made-up value to come from. That is a stronger guarantee than any prompt.

The same argument applies to exploration. Which filters are worth offering is
a domain question, and `metadata/business_rules.yaml` has already answered it:
`active_business_object`, `open_task`, `delayed_task` are named rules with SQL
attached. Reading the suggestions out of that file means the registry and the
suggestions cannot disagree, and adding a rule adds a suggestion for free.

Cost is a real but secondary benefit. A suggestion-generating call per turn
would roughly double the per-turn spend for something the state already
determines.

## Where the LLM is still the only option

Recognising that a question has no answerable form. "What is the profit
margin?" needs someone to notice that no cost column exists and no arithmetic
over the schema produces one. That is semantic reasoning over an open-ended
question, and it is what the model is for.

It already happens inside the single existing call, via the `{"clarify": ...}`
reply the prompt permits. The layer adds no round trip — it takes the prose
the model produced, keeps it as the question, and attaches candidates from the
schema if the prose names a column that has them.

The division of labour is deliberate and it plays to both sides:

- The model is good at noticing that "Breached" is not a real SLA status, and
  poor at reliably reciting the two values that are.
- The schema is the reverse.

So the model supplies the *reason* and the schema supplies the *choices*.

## Flow

```
question as typed
      │
      ▼
  repair                    deterministic, 0 tokens
      │                     schema vocabulary + edit distance
      ▼
  classify turn             deterministic, 0 tokens
      │                     new_block / follow_up / switch / rebase
      ▼
  ambiguous entity? ──yes──▶ clarification            0 tokens, 0 LLM CALLS
      │ no                   (candidates from gazetteer)
      ▼
  render context            fixed-size structured state
      │
      ▼
  ask the model             ← the one LLM call, unchanged
      │
      ├── {"clarify": ...} ─▶ clarification           no extra call
      │                       (candidates from schema)
      ▼
  {"sql": ...} → gate → PostgreSQL → rows
      │
      ▼
  explore                   deterministic, 0 tokens
                            (rules from the business registry)
```

## Suggestions are actions, not SQL

A suggestion carries a structured `action`, never a query:

```json
{
  "id": "filter_active_business_object",
  "label": "Only the active ones",
  "action": {
    "type": "add_filter",
    "field": "business_object_status",
    "operator": "=",
    "value": "Active"
  }
}
```

Choosing it mutates `ConversationState` and produces an ordinary question,
which goes back through the normal path:

```
suggestion → action → state mutation → context → the model → SQL
```

This is the point. If a suggestion carried its own SQL there would be two
things writing queries, and the moment they disagreed there would be no way to
say which was right. There is one SQL generator, and the follow-up layer is
not it.

The state written by an action is provisional in exactly the way the rest of
the pipeline already expects: `update_state` overwrites it from whatever query
actually ran, so a suggestion that the model interprets differently
self-corrects on the next turn rather than compounding.

## What the layer refuses to do

- **Suggest something after every answer.** An empty result has nothing to
  narrow; a query that never ran has no shape to build on; one lone suggestion
  is not a choice. In all three cases it says nothing.
- **Offer four variations of one column.** The registry names three status
  rules, and taking all of them spent three of four slots on `business_object_status`
  and pushed out sorting and counting. One suggestion per column.
- **Repair a word it is not sure about.** Corrections come only from the
  database's own vocabulary, never from a general dictionary, and the words
  people ask *with* — `sort`, `back`, `count`, `only` — are never touched.
  Unguarded, the layer turned "Sort by due date" into "short by due date".

## Files

| File | Role |
|---|---|
| `benchmark/normalize.py` | Repair. Vocabulary, edit distance, case preservation. |
| `benchmark/followup.py` | The contract, candidates, suggestions, action→state. |
| `benchmark/context.py` | Structured state and turn classification (extended, not replaced). |
| `benchmark/lean_runner.py` | Wiring: repair before classify, follow-up after answer. |
| `benchmark/followup_questions.yaml` | 115 turns. |
| `scripts/build_followup_suite.py` | Builds and validates it. |
