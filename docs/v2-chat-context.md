# V2: multi-turn conversation (design only, not implemented)

**Status: not built.** V1 is deliberately stateless — one question, one
subprocess, no memory. This document specifies how conversational follow-ups
would work and names the exact place they would attach, so that adding them
later is an extension rather than a rewrite.

Nothing here should be read as describing current behaviour.

## The problem

```
User:       Name a few workflows.
Assistant:  Onboarding, Invoice Processing, Hiring, QA

User:       Now list the tasks in them.
```

"them" refers to entities produced by the previous answer. A stateless system
cannot resolve it. Worse, in this project the previous answer's **rows never
reach Claude** — so even a naive "paste the history back" approach would send
Claude a reference to data it has never seen.

That constraint is the interesting part of the design, and it is what makes V2
non-trivial here.

## Two kinds of reference

**Referring to prior *entities*.**

```
User: Show workflows A, B, C and D.
User: Now list the tasks in them.        -> them = {A, B, C, D}
```

**Referring to a prior *query*.**

```
User: Which users are overloaded?
User: Now only the active ones.          -> add users.status = 'ACTIVE' to the previous query
```

The second is easier: it is a SQL transformation and needs no row data at all.
The first needs to know *which* entities, which is row data.

## Proposed state

```python
@dataclass
class Turn:
    index: int
    question: str
    generated_sql: str | None
    result_columns: list[str]
    result_row_count: int
    entities: dict[str, list[str]]   # {"workflows": ["Onboarding", ...]}
    entity_source: str               # the column entities came from

@dataclass
class Session:
    session_id: str
    turns: list[Turn]
    claude_session_id: str | None     # for `claude --resume`
```

## The privacy decision V2 forces

Resolving "them" requires telling Claude which workflows were in the previous
result. That **is** row data, however small. V1's guarantee — no rows to the
model — cannot survive unchanged.

Three options, in order of preference:

**1. Reference by predicate, not by value (recommended).**
Do not send entities at all. Send the *previous SQL* and let the new query
nest it:

```sql
SELECT t.name
FROM tasks t
WHERE t.workflow_id IN (
    <previous query, rewritten to select id>
)
```

Claude receives SQL it already wrote. **No row data moves.** V1's privacy
guarantee holds exactly. This handles most real follow-ups, including both
examples above.

Cost: cannot handle a user narrowing by hand ("just A and C") without
disclosing which of the entities those were.

**2. Send entity labels only, under an explicit allowlist.**
Send the values of one designated label column (`workflows.name`), never
identifiers, never other columns, capped at N values. A deliberate,
documented, narrow relaxation.

**3. Resolve references locally before prompting.**
Python resolves "them" from stored state and rewrites the question into a
self-contained one before sending it. **Rejected**: that is exactly the custom
planner this project exists to avoid, and it would put Python back in charge of
query construction.

Option 1 should be the default; option 2 an opt-in flag with a loud note in
`docs/privacy.md`.

## Where it attaches

A single seam, already isolated:

`benchmark/runner.py` → `run_question(question, config_name, privacy_mode, settings, mcp_config_path)`

V2 adds one optional parameter and changes nothing else:

```python
def run_question(..., session: Session | None = None) -> QuestionResult:
    ...
    run = ask_claude(question.question, mcp_config_path, privacy_mode,
                     settings, session=session)
```

`claude/cli.py` would then either:

- pass `--resume <claude_session_id>` so Claude Code keeps its own history
  (simplest, and it keeps the transcript on Claude's side); or
- prepend a rendered context block built from `Session` by a new
  `claude/context.py`.

`claude/prompts.py` gains a follow-up prompt variant instructing Claude to nest
the previous query rather than ask for its results.

Everything downstream — parser, safety gate, execution, evaluator, classifier,
report — is unchanged. They operate on SQL and rows and neither knows nor cares
about conversation.

## What V2 would need that V1 lacks

| Need | Why V1 does not have it |
|---|---|
| `Session` / `Turn` storage | V1 has no state between questions |
| Follow-up prompt variant | V1's prompt assumes a self-contained question |
| Previous-SQL nesting logic | new; must live in the prompt, not in Python |
| Multi-turn benchmark format | `questions.yaml` is one question per entry |
| Ground truth for turn *n* given turns 1..n-1 | much harder to author than single-shot |
| Reference-resolution failure categories | e.g. `WRONG_ANTECEDENT` |

That last row is the real cost. Single-shot ground truth is a query and its
rows. Multi-turn ground truth is a *conversation* and its rows at every step,
and it has to be re-verified whenever an earlier turn changes. Expect
authoring, not engineering, to dominate the effort.

## Suggested order of work

1. Extend `questions.yaml` to allow a `turns:` list, and teach
   `verify_ground_truth.py` to check each turn in sequence.
2. Add `Session`/`Turn` and thread the optional argument through
   `run_question` → `ask_claude`.
3. Implement option 1 (previous-SQL nesting) in the prompt only.
4. Measure on a small conversational set before touching option 2.

Do not start with `--resume`. It is the quickest thing to wire up and it hides
the design question — you would learn nothing about whether reference
resolution actually works, because Claude Code's own history would be doing the
work invisibly.
