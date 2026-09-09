# Ask the Data — UI/UX improvements

**Date:** 9 September 2026
**Scope:** the Ask the Data page only — `SqlChatbotPage.jsx` and its own
components, plus two keys added to one backend method.
**Repos:** `WCMS - Frontend - Arvind Retail` (React 17, AG Grid 32.3.3) and
`dev-arvind-retail-chatbot` (Drupal 10 module `vf_sql_chatbot`).

---

## 1. What this is

Ten UI/UX improvements were requested. Nine are in scope. Item 6, a
ChatGPT-style conversation sidebar, is deferred to its own spec because the
backend has no conversation history to list — see §8.

Investigation changed the shape of the work: four items are already
implemented and need a fix rather than a build, and two of the things asked
for do not exist anywhere yet, in the React port or in the Python original.
Recording that here so the plan does not rebuild working code.

| # | Item | Found state | Work |
|---|---|---|---|
| 1 | Pagination | `pagination` and `paginationPageSize={25}` already set | Page-size selector, lower the on-threshold, height follows page size |
| 2 | Debug metadata | 3 of the Python's 5 groups present | Port 2 groups, add 2 backend fields |
| 3 | Borders and resize | `resizable: true` already set | Scoped borders; fix a `flex` conflict |
| 4 | Auto-scroll | Present, and forces the user to the bottom | Replace with pinned-tracking |
| 5 | Animations | A reduced-motion block exists | Add transitions inside it |
| 7 | Copy response | Absent in React; present in the Python console | Build |
| 8 | Question width | `max-width: 82%` | Shrink to fit |
| 9 | Send button | Text-only Send / Asking… | Icon, disabled and stop states |
| 10 | Input box | Textarea growing to 160px in a dock | Rounded container, integrated button |

---

## 2. Structure

`SqlChatbotPage.jsx` is 545 lines and already holds three components. The new
scroll, copy and composer behaviour would push it past what stays readable, so
it splits along seams that already exist. This is extraction of what is there,
not new abstraction: nothing gains a config object, a provider or a prop it
does not use.

| File | Status | Purpose |
|---|---|---|
| `components/SqlChatbot/DebugDetails.jsx` | moved out, expanded | Item 2 |
| `components/SqlChatbot/StateRail.jsx` | moved out unchanged | — |
| `components/SqlChatbot/Composer.jsx` | new | Items 9, 10 |
| `components/SqlChatbot/CopyButton.jsx` | new | Item 7 |
| `components/SqlChatbot/useStickyScroll.js` | new | Item 4 |
| `components/SqlChatbot/ChatResultGrid.jsx` | edited | Items 1, 3 |
| `pages/SqlChatbotPage.jsx` | slimmed to about 260 lines | Composition, send and reset |
| `css/SqlChatbotPage.css` | edited | Items 5, 8, 10 |

`SqlChatbotPage.jsx` keeps ownership of `turns`, `busy`, `debug`, the abort
controller and the session id. No new state container: the page is the only
thing that needs to see all of it, and passing three props is cheaper than a
context.

---

## 3. Items 1 and 3 — the result grid

### 3.1 Page-size selector

`paginationPageSizeSelector={[10, 25, 50, 100]}` replaces the current `false`.
AG Grid's own pager already supplies previous and next plus the page number, so
no custom footer is written.

The threshold that switches pagination on has to move with it. Today it is
`rows.length > PAGE_SIZE`, so a 20-row answer gets no pager at all — and
therefore no page-size control, exactly when someone might want to drop it to
10. The gate becomes the **smallest** selectable size:

```
paginated = rows.length > 10
```

Below 10 rows there is nothing to page and no pager appears, so a three-row
answer stays uncluttered. At or above it the selector is present whenever it
could change anything. `PAGE_SIZE` stays 25 as the default.

### 3.1a Grid height

`naturalHeight` currently multiplies **every** row by the row height, then
caps at `MAX_BODY_HEIGHT`. Once page size is selectable that is wrong twice
over: only one page is rendered, and choosing 10 rows should give a short grid
rather than the same 420px box with an inner scrollbar.

Height becomes header plus `min(rows.length, pageSize)` rows plus the pager,
still capped at `MAX_BODY_HEIGHT`. The page-size choice therefore has to live
in component state rather than staying the `PAGE_SIZE` constant, read back
through AG Grid's `paginationPageSize` change event.

### 3.2 Vertical borders

The shared theme sets `--ag-cell-horizontal-border: none`
(`AGGrid/Styles/ag-grid-theme.css:683`). That variable is AG Grid's name for
the line *between* columns, and it is why the chat grid has none.

The override is scoped to `.sqlchat-grid`, not applied to the variable at its
source. Every datatable in the application imports that theme, so changing it
there would put borders on Tasks, Reports, Issues and every other grid — a
visual change to screens nobody asked about. Header cells take their own rule,
since the header does not inherit the cell variable.

### 3.3 The resize conflict

`defaultColDef` sets `flex: 1` on every column while `autoSizeStrategy` is
also `fitGridWidth`. With `flex` present AG Grid recomputes widths to fill the
container, so a manually dragged column springs back or displaces its
neighbours. This is the "resizing breaks the table layout" symptom.

`flex` is removed. `autoSizeStrategy={{ type: "fitGridWidth", defaultMinWidth:
140 }}` already produces the full-width first paint on its own, and without
`flex` a dragged width is then stable. `minWidth: 140` and `resizable: true`
stay as they are.

---

## 4. Item 2 — debug metadata

### 4.1 Backend

`QueryRunner::summary()` (`src/Service/QueryRunner.php:109`) returns
`columns`, `row_count`, `rows` and `truncated`. It receives a `$result` array
that also carries `types` and `duration_ms`, built by `QueryRunner::result()`,
and drops both.

Those two keys are added to the returned array. No logic changes and nothing
new is computed. Both are diagnostics, so they travel the path the module
already uses for privileged fields and are absent from a turn asked with debug
off — the response does not contain them to withhold.

`duration_ms` is the SQL execution time. It is not the same number as
`latency_ms`, which is the whole turn including the model call, and the panel
must not present one as the other.

### 4.2 Frontend

`DebugDetails.jsx` regains the Python console's grouping. Present groups keep
their fields; the additions are:

**Query** — `Rows returned` (`result.row_count`), `Columns`
(`result.columns`), `Column types` (`result.types`, new), `Query time` in
seconds to one decimal (`result.duration_ms`, new).

**Follow-up** — absent from React entirely today: `required`, `type`,
`reason`, `question`, `free text allowed`, and suggestion ids with their
actions.

**Cost** — gains `cache_write`, `total`, `effective` and `tool_calls`.
`effective` is the weighted figure the Python used, charging cache reads at a
tenth of fresh input, because that is the number that tracks what a turn costs:

```
effective = (prompt - cache_read) + cache_read * 0.1 + completion
```

The Scoring group (`result_match`, `semantic_match`, `projection_verdict`,
`semantic_issues`) is **not** ported. The module's own README states these are
meaningless without a known-correct answer, so in production they would render
`n/a` on every turn — four rows of noise.

Absent fields continue to render an em dash through the existing `show()`
helper. A missing field must never crash the panel or invent a value, because
a debugging view that guesses is worse than one that says nothing.

---

## 5. Item 4 — sticky auto-scroll

`SqlChatbotPage.jsx:252` calls `scrollIntoView` on a sentinel whenever `turns`
or `busy` changes. It scrolls ancestor containers as well as the message list,
and it always wins against the user.

`useStickyScroll(containerRef, contentRef)` replaces it:

- A `scroll` listener sets `pinned` true when the container is within **80px**
  of the bottom, false otherwise. Scrolling up unpins; coming back re-pins.
- A `ResizeObserver` on the content element sets `container.scrollTop` to
  `container.scrollHeight` **only while pinned**.
- Writing `scrollTop` directly, rather than calling `scrollIntoView`, keeps
  the effect inside the message list and leaves the page around it alone.

One `ResizeObserver` covers every cause of growth — a new turn, the thinking
indicator, the answer landing, a debug section expanding, the grid finishing
its first render — so no case needs a hook of its own. Programmatic scrolls do
not need suppressing: they land at the bottom, which is where `pinned` is
already true.

Responses are not streamed. The endpoint answers one POST with a complete
answer, so "while a response is being generated" means the thinking indicator
and the answer arriving, not token-by-token growth. Nothing here assumes
streaming, and nothing needs changing if it is added later.

---

## 6. Item 5 — animations

All of it goes inside the existing `@media (prefers-reduced-motion: reduce)`
guard at `SqlChatbotPage.css:644`, which already sets the precedent.

| Element | Animation |
|---|---|
| A turn appearing | Fade with a 4px rise, 150ms ease-out |
| Debug expand and collapse | `grid-template-rows: 0fr` to `1fr`, 180ms |
| Grid first paint | Fade in, 200ms |
| Buttons and focus rings | 120ms transitions |
| Copy feedback | Icon crossfade, 120ms |
| Thinking indicator | Existing dots, unchanged |

The debug section uses the `0fr` to `1fr` grid technique because `height:
auto` is not animatable and a fixed max-height would clip a long SQL
statement.

No sidebar animation: item 6 is deferred. Pagination changes are left to AG
Grid's own rendering — animating rows in on every page change is the kind of
excess the request asked to avoid.

---

## 7. Items 7, 8, 9 and 10 — the chat surface

### 7.1 Copy response (item 7)

An icon button on each answer. It builds text from the answer object, not from
the DOM, so grid markup and code formatting are untouched:

1. The question
2. The clarification, when there is one
3. The full result as TSV — **every row the answer holds**, not the page on
   screen, matching the Python console's behaviour
4. The generated SQL, only when the turn was asked with debug on

Feedback is a check icon and the word Copied for 1.5s, then back.
`navigator.clipboard.writeText` with a hidden-textarea fallback, since the app
is served over plain HTTP in some environments and the async clipboard API is
unavailable there.

### 7.2 Question width (item 8)

`width: fit-content` with `max-width: min(82%, 60ch)`. The bubble shrinks to a
short question and still wraps a long one. The 82% is kept as the outer bound
so the change is a narrowing, not a re-layout.

### 7.3 Send button (item 9)

A circular icon button inside the input container.

- Disabled when the input is empty or whitespace only — the existing
  `!input.trim()` condition, now also driving the visual state.
- While busy it becomes a **stop** button and aborts the in-flight request.
  `send()` already creates an `AbortController` per turn and already handles
  `CanceledError`, so this is wiring an existing capability to a control, not
  new machinery.
- Enter sends, Shift and Enter inserts a newline. Already correct; preserved.

### 7.4 Input box (item 10)

A rounded container owning the border and focus ring, with the textarea
transparent inside it and the send button as a sibling. The textarea grows
from one row to about 200px and then scrolls internally, up from the current
160px cap. The existing sticky dock is kept — it already works.

---

## 8. Item 6 — deferred, and why

The sidebar needs a list of past conversations. There is none to list.
Conversation state lives in Drupal's expirable key-value store as one
serialised blob per `uid:session_id`, expiring an hour after the last turn:
no history table, no titles, no list endpoint.

`docs/conversation-storage-plan.md` in the module covers exactly this and is
unimplemented, awaiting a decision on what a turn record stores. Phases 1 and
2 of that plan — the tables and the conversation list endpoints — are
prerequisites. Building the sidebar against browser storage was considered and
rejected: it is per-browser, lost on a cache clear, and puts a transcript of
business data in `localStorage`, which is the same objection that ruled out
Option C in the storage plan.

Item 6 gets its own spec once that storage ships.

---

## 9. Verification

`react-scripts test` with @testing-library/react 12 is already configured.
Tests cover the places where being wrong is silent rather than obvious.

| Test | Asserts |
|---|---|
| Sticky scroll — follows | A pinned container scrolls to the bottom when content grows |
| Sticky scroll — yields | After scrolling up, growing content does **not** move the view |
| Sticky scroll — resumes | Returning to within 80px re-pins, and the next growth scrolls |
| Copy — completeness | Copies every row, not the paginated subset |
| Copy — debug gating | SQL is included with debug on and absent with it off |
| Send — disabled | Disabled for empty and for whitespace-only input |
| Send — stop | While busy the control aborts the in-flight request |
| Debug — new fields | Query time, column types, rows and the Follow-up group render |
| Debug — absent fields | A response missing the new keys renders an em dash and does not throw |
| Grid — page size | Choosing 50 shows more rows than the default 25 |
| Grid — pager threshold | A 20-row result has a pager and a size selector; a 3-row result has neither |
| Grid — height tracks page size | Dropping to 10 per page shortens the grid instead of leaving a 420px box |
| Grid — resize holds | A resized column keeps its width after a re-render |

PHPUnit, in the module: `summary()` returns `duration_ms` and `types`.

Manual check, because CSS scoping cannot be asserted in Jest: open a Tasks or
Reports datatable and confirm it has **not** gained vertical borders.

---

## 10. Out of scope

- **Item 6**, per §8.
- **App-wide grids.** `AGGridGenerator.jsx` (3,500 lines, with its own
  pagination footer) and the shared theme variable are untouched.
- **The Scoring debug group**, per §4.2.
- **Streaming responses.** The endpoint returns one whole answer; changing
  that is a separate piece of work.
- **The Ask TMS menu link.** Unrelated, and tracked separately.
