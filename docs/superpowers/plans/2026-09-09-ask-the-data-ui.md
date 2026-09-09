# Ask the Data UI/UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver nine UI/UX improvements to the Ask the Data page — grid pagination controls and borders, extended debug metadata, non-hostile auto-scroll, subtle animations, copy-to-clipboard, a compact question bubble, and a ChatGPT-style composer.

**Architecture:** `SqlChatbotPage.jsx` splits along seams that already exist, into a composer, a debug panel, a state rail, a scroll hook and two pure-logic modules. Decisions that jsdom cannot observe — pagination thresholds, grid height, copied text — move into pure functions that are unit-tested directly, leaving the React components as thin wiring. One backend method gains two keys it already receives.

**Tech Stack:** React 17, AG Grid 32.3.3 (enterprise, licensed), CRA `react-scripts test` with @testing-library/react 12 and jest-dom, Drupal 10 PHP module.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-09-09-ask-the-data-ui-design.md` in the `wren-poc` repo. Read it before starting.
- **Two repos.** Frontend: `c:/xampp/htdocs/WCMS%20-%20Frontend%20-%20Arvind%20Retail` (branch `feat/sql-chatbot`). Backend: `c:/xampp/htdocs/dev-arvind-retail-chatbot` (branch `Tms-Sql-Chatbot-Testing`). Commit in each separately. Both are already on the right branch — do not create, switch or rebase branches.
- **Stage only the files your task names.** Never `git add -A`, `git add .`, or `git commit -a`. The backend repo has tracked local-environment changes already in its working tree — `web/sites/site-arvind-retail/settings.php` and a `dxpr_theme` CSS file — and committing either would push one machine's configuration to everyone. The `git add` lines in each task list the exact paths; use them as written.
- **Scope is the Ask the Data page only.** Never edit `components/DataTables/AGGrid/AGGridGenerator.jsx` or `components/DataTables/AGGrid/Styles/ag-grid-theme.css`. Every grid change is scoped under `.sqlchat`.
- **Item 6 (conversation sidebar) is out of scope.** Do not add a sidebar, conversation list, or `localStorage` persistence.
- **Do not port the Scoring debug group** (`result_match`, `semantic_match`, `projection_verdict`, `semantic_issues`).
- **No new dependencies.** Icons are inline SVG. No animation library.
- **CSS variables to use:** `--sc-ground`, `--sc-raised`, `--sc-ink`, `--sc-muted`, `--sc-faint`, `--sc-line`, `--sc-line-soft`, `--sc-accent`, `--sc-accent-soft`, `--sc-danger`, `--sc-radius`, `--sc-mono`. All defined on `.sqlchat`.
- **Animations need no reduced-motion guard of their own.** `SqlChatbotPage.css` ends with a block that sets `animation: none !important; transition: none !important` on every descendant of `.sqlchat` under `prefers-reduced-motion: reduce`. New animations are covered automatically. Do not remove that block.
- **Absent data renders an em dash**, never a guess, never a crash. The existing `show()` helper does this.
- **Run frontend tests with** `npx react-scripts test --watchAll=false <path>` from the frontend repo root. CRA's runner defaults to watch mode, which hangs a non-interactive session.
- **Test file convention:** co-located `*.test.js` / `*.test.jsx` beside the module. Only `src/App.test.js` exists today; follow CRA's default discovery.

---

## Task 1: Backend — carry `duration_ms` and `types` into the response

**Files:**
- Modify: `web/modules/custom/vf_sql_chatbot/src/Service/QueryRunner.php:109-123`
- Create: `web/modules/custom/vf_sql_chatbot/scripts/verify_summary_fields.php`

Repo: `c:/xampp/htdocs/dev-arvind-retail-chatbot`

**Interfaces:**
- Consumes: nothing.
- Produces: `QueryRunner::summary()` returns two additional keys — `types` (array of strings, `[]` when unknown) and `duration_ms` (float, or `NULL` when the caller's result carried no timing). Task 7 renders both.

**Context:** `QueryRunner::result()` already builds `types` and `duration_ms`. `summary()` receives that array and drops both. Nothing new is computed here.

**This paragraph was wrong and is corrected.** It originally claimed the `??`
coalescing guards the synthetic result at `TurnRunner.php:428`, which has no
`duration_ms` key. Two reviewers independently disproved it: that array's only
consumer is `classifyFailure()` at `:433`, it never reaches `summary()`, and it
does carry `'types' => []`. All three real `summary()` call sites receive a
live `runReadonly()` return, which always has both keys.

The guard on `duration_ms` is still right, for a different reason: `summary()`
is public API and a caller may hand it a result with no timing — the
verification script's second block does exactly that, and would warn without
it. It is also what makes this task's own `Produces` contract true.

The guard on `types` is inert under every reachable shape, since `summary()`
already reads `error`, `rows` and `columns` unguarded. It stays anyway, by
decision, but the script must assert `types` properly rather than lean on it —
see Step 1.

- [ ] **Step 1: Write the verification script**

Create `web/modules/custom/vf_sql_chatbot/scripts/verify_summary_fields.php`. This follows the module's established pattern — boot through `bootstrap.php`, print what was checked, count failures, exit non-zero — the same shape as `verify_readonly.php`.

```php
<?php

/**
 * @file
 * Check that summary() carries the two diagnostic fields the debug panel needs.
 *
 *   php verify_summary_fields.php
 *
 * QueryRunner::result() has always built 'types' and 'duration_ms'.
 * summary() used to drop both, so the panel could show the total turn
 * latency but never the time the query itself took, and never a column's
 * type. This checks they survive the trip.
 *
 * duration_ms is the SQL execution time. It is NOT latency_ms, which is the
 * whole turn including the model call. Anything presenting one as the other
 * is wrong.
 *
 * Exits non-zero if a field is missing or the wrong type.
 */

require __DIR__ . '/bootstrap.php';

$runner = \Drupal::service('vf_sql_chatbot.query_runner');
$failures = 0;

echo "a real read, summarised\n";
$result = $runner->runReadonly('SELECT task_id, task_status FROM tms_task_flat LIMIT 5');
if (!$result['ok']) {
  printf("  the read FAILED: %s\n", $result['error']);
  echo "\nCannot check summary() without a working read.\n";
  exit(1);
}
$summary = $runner->summary($result);

foreach (['columns', 'row_count', 'rows', 'truncated', 'types', 'duration_ms'] as $key) {
  $present = array_key_exists($key, $summary);
  printf("  %-12s %s\n", $key, $present ? 'present' : 'MISSING  <-- FAILURE');
  if (!$present) {
    $failures++;
  }
}

if (array_key_exists('types', $summary) && !is_array($summary['types'])) {
  echo "  types is not an array  <-- FAILURE\n";
  $failures++;
}
if (array_key_exists('duration_ms', $summary) && !is_numeric($summary['duration_ms'])) {
  echo "  duration_ms is not numeric  <-- FAILURE\n";
  $failures++;
}
if (!empty($summary['types'])) {
  printf("  types read  [%s]\n", implode(', ', $summary['types']));
}
if (is_numeric($summary['duration_ms'] ?? NULL)) {
  printf("  query took  %.1f ms\n", $summary['duration_ms']);
}

// A result with neither key must not warn. TurnRunner builds exactly this
// for a turn that asked a clarifying question instead of running SQL.
echo "\na result carrying no timing\n";
$synthetic = ['columns' => [], 'types' => [], 'rows' => [], 'error' => NULL, 'sqlstate' => NULL, 'ok' => TRUE];
$syntheticSummary = $runner->summary($synthetic);
if (!array_key_exists('duration_ms', $syntheticSummary)) {
  echo "  duration_ms absent from the array  <-- FAILURE\n";
  $failures++;
}
elseif ($syntheticSummary['duration_ms'] !== NULL) {
  echo "  duration_ms should be NULL when nothing ran  <-- FAILURE\n";
  $failures++;
}
else {
  echo "  duration_ms  NULL, as it should be\n";
}

echo "\n", str_repeat('=', 58), "\n";
echo $failures === 0
  ? "summary() carries every field the debug panel reads.\n"
  : sprintf("%d FAILURE(S).\n", $failures);
exit($failures === 0 ? 0 : 1);
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd "c:/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot/scripts"
php verify_summary_fields.php
```

Expected: exit 1, with `types MISSING` and `duration_ms MISSING`.

If instead it fails to boot, stop and report — `bootstrap.php` needs `BACKEND_SITE_NAME` in `.env` and a reachable database. Do not work around it by editing `bootstrap.php`.

- [ ] **Step 3: Add the two keys**

In `src/Service/QueryRunner.php`, the return of `summary()` becomes:

```php
    return [
      'columns' => $result['columns'],
      'row_count' => count($result['rows']),
      'rows' => $rows,
      'truncated' => count($result['rows']) > $maxRows,
      // Both are built by result() and were being dropped here. types names
      // each column's Postgres type; duration_ms is how long the query took,
      // which is not the turn's latency_ms -- that includes the model call.
      // Coalesced because summary() is public and a caller may pass a result
      // carrying no timing, as verify_summary_fields.php does.
      'types' => $result['types'] ?? [],
      'duration_ms' => $result['duration_ms'] ?? NULL,
    ];
```

Change nothing else in the method. The early `error` return above it stays as it is: a failed query has no timing worth reporting.

- [ ] **Step 4: Run it to verify it passes**

```bash
php verify_summary_fields.php
```

Expected: exit 0, `summary() carries every field the debug panel reads.`

- [ ] **Step 5: Commit**

```bash
cd "c:/xampp/htdocs/dev-arvind-retail-chatbot"
git add web/modules/custom/vf_sql_chatbot/src/Service/QueryRunner.php web/modules/custom/vf_sql_chatbot/scripts/verify_summary_fields.php
git commit -m "Stop summary() dropping the query's own timing and types

result() has always built both. summary() returned four keys and discarded
these two, so the debug panel could show a turn's total latency but never
how long the query itself took, and never a column's type.

Coalesced rather than read directly: TurnRunner builds a synthetic result
for turns that clarify instead of querying, and it carries no timing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Grid pagination and height, as pure functions

**Files:**
- Create: `src/components/SqlChatbot/chatGridLayout.js`
- Create: `src/components/SqlChatbot/chatGridLayout.test.js`

Repo: `c:/xampp/htdocs/WCMS%20-%20Frontend%20-%20Arvind%20Retail`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `PAGE_SIZES` — `[10, 25, 50, 100]`
  - `DEFAULT_PAGE_SIZE` — `25`
  - `MAX_BODY_HEIGHT` — `420`
  - `gridLayout(rowCount: number, pageSize: number) => { paginated: boolean, height: number }`

  Task 3 imports `gridLayout`, `PAGE_SIZES` and `DEFAULT_PAGE_SIZE`. It does
  not import `MAX_BODY_HEIGHT` — `gridLayout` already applies the cap — but
  the constant is exported because the tests assert against it.

**Context:** `ChatResultGrid.jsx` currently decides both inline: `paginated = rows.length > PAGE_SIZE` and `naturalHeight = 34 + rows.length * 34 + (paginated ? 44 : 0)`. Both are wrong once page size is selectable — a 20-row answer gets no pager and therefore no size control, and a 10-per-page choice still renders a 420px box. Extracting them makes both assertable; jsdom cannot observe a rendered AG Grid's height.

- [ ] **Step 1: Write the failing tests**

Create `src/components/SqlChatbot/chatGridLayout.test.js`:

```js
import {
  gridLayout,
  PAGE_SIZES,
  DEFAULT_PAGE_SIZE,
  MAX_BODY_HEIGHT,
} from "./chatGridLayout";

describe("gridLayout", () => {
  it("does not paginate a result smaller than the smallest page size", () => {
    expect(gridLayout(3, DEFAULT_PAGE_SIZE).paginated).toBe(false);
  });

  it("paginates a 20-row result, so the size selector is reachable", () => {
    // The old gate was rows > 25, which hid the pager exactly when someone
    // might want to drop the page size to 10.
    expect(gridLayout(20, DEFAULT_PAGE_SIZE).paginated).toBe(true);
  });

  it("paginates at one row above the smallest page size and not at it", () => {
    expect(gridLayout(PAGE_SIZES[0], DEFAULT_PAGE_SIZE).paginated).toBe(false);
    expect(gridLayout(PAGE_SIZES[0] + 1, DEFAULT_PAGE_SIZE).paginated).toBe(true);
  });

  it("gives a shorter grid for a smaller page size", () => {
    const small = gridLayout(200, 10).height;
    const large = gridLayout(200, 100).height;
    expect(small).toBeLessThan(large);
  });

  it("never exceeds the height cap", () => {
    expect(gridLayout(500, 100).height).toBe(MAX_BODY_HEIGHT);
  });

  it("sizes an unpaginated result to its own rows", () => {
    // Header 34 + three rows at 34, and no pager to allow for.
    expect(gridLayout(3, DEFAULT_PAGE_SIZE).height).toBe(34 + 3 * 34);
  });

  it("offers 25 as the default page size", () => {
    expect(PAGE_SIZES).toContain(DEFAULT_PAGE_SIZE);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
npx react-scripts test --watchAll=false src/components/SqlChatbot/chatGridLayout.test.js
```

Expected: FAIL — `Cannot find module './chatGridLayout'`.

- [ ] **Step 3: Write the implementation**

Create `src/components/SqlChatbot/chatGridLayout.js`:

```js
/**
 * How big the result grid is, and whether it pages.
 *
 * Extracted from ChatResultGrid so both decisions can be asserted. jsdom has
 * no layout and ag-grid virtualises rows against measured heights, so a
 * rendered-grid test would be asserting the mock rather than the behaviour.
 */

/** Offered in the grid's own page-size selector. */
export const PAGE_SIZES = [10, 25, 50, 100];

export const DEFAULT_PAGE_SIZE = 25;

/** Above this the grid scrolls instead of pushing the composer off screen. */
export const MAX_BODY_HEIGHT = 420;

const HEADER_HEIGHT = 34;
const ROW_HEIGHT = 34;
const PAGER_HEIGHT = 44;

/**
 * @param {number} rowCount rows the answer holds.
 * @param {number} pageSize rows shown per page.
 * @returns {{paginated: boolean, height: number}}
 */
export function gridLayout(rowCount, pageSize) {
  // The gate is the SMALLEST selectable size, not the default. Gating on the
  // default would hide the pager for a 20-row answer, and with it the control
  // that would have set the page size to 10.
  const paginated = rowCount > PAGE_SIZES[0];

  // Only one page is rendered, so height follows the page and not the result.
  const visibleRows = paginated ? Math.min(rowCount, pageSize) : rowCount;
  const natural =
    HEADER_HEIGHT + visibleRows * ROW_HEIGHT + (paginated ? PAGER_HEIGHT : 0);

  return { paginated, height: Math.min(natural, MAX_BODY_HEIGHT) };
}
```

- [ ] **Step 4: Run to verify they pass**

```bash
npx react-scripts test --watchAll=false src/components/SqlChatbot/chatGridLayout.test.js
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add src/components/SqlChatbot/chatGridLayout.js src/components/SqlChatbot/chatGridLayout.test.js
git commit -m "Make the grid's paging and height decisions assertable

Both were inline in ChatResultGrid and both were about to be wrong: the
pager was gated on the default page size, so a 20-row answer got no pager
and therefore no size selector, and height multiplied every row rather than
the one page actually rendered.

Pure functions because jsdom has no layout and ag-grid virtualises against
measured heights, so a rendered-grid assertion would test the mock.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Wire the grid up — selector, height, borders, resize fix

**Files:**
- Modify: `src/components/SqlChatbot/ChatResultGrid.jsx`
- Modify: `src/css/SqlChatbotPage.css` (add a rule after the existing `.sqlchat .sqlchat-grid-body.ag-theme-alpine` block at line 300)

**Interfaces:**
- Consumes: `gridLayout`, `PAGE_SIZES`, `DEFAULT_PAGE_SIZE`, `MAX_BODY_HEIGHT` from Task 2.
- Produces: nothing other tasks consume.

**Context — the resize bug.** `defaultColDef` sets `flex: 1` on every column while `autoSizeStrategy` is also `fitGridWidth`. With `flex` present AG Grid recomputes widths to fill the container, so a dragged column springs back or displaces its neighbours. That is the reported "resizing breaks the layout". Removing `flex` keeps the full-width first paint — `autoSizeStrategy` alone produces it — and makes a dragged width stick.

**Context — the borders.** Not the shared theme's fault. That theme's `--ag-cell-horizontal-border: none` is scoped to `.test_datatable_table .ag-root-wrapper`, which the chat grid has no ancestor matching. The real cause is AG Grid's own base default in `ag-grid.css`: `--ag-cell-horizontal-border: solid transparent`, with `--ag-header-column-separator-display: none`. The border is already drawn and merely invisible. Consequence: **this change cannot affect any other grid**, because the other grids set their own values on their own selector, which this task does not touch.

Verified in AG Grid 32.3.3: `paginationPageSizeSelector?: number[] | boolean` exists (`gridOptions.d.ts:692`), `api.paginationGetPageSize()` exists (`gridApi.d.ts:602`), and `PaginationChangedEvent` carries `newPageSize?: boolean` (`events.d.ts:196-207`).

- [ ] **Step 1: Replace the layout constants and add page-size state**

In `ChatResultGrid.jsx`, delete these two lines near the top:

```js
const PAGE_SIZE = 25;

/** Above this, the grid gets its own scroll instead of growing the page. */
const MAX_BODY_HEIGHT = 420;
```

Add to the imports:

```js
import {
  gridLayout,
  PAGE_SIZES,
  DEFAULT_PAGE_SIZE,
} from "./chatGridLayout";
```

and change the React import line to include `useState`:

```js
import React, { useCallback, useMemo, useRef, useState } from "react";
```

Then, immediately after `const gridRef = useRef(null);`, add:

```js
  // The grid owns the selector, so the chosen size has to be read back out of
  // it -- the height depends on it and nothing else here would know.
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
```

- [ ] **Step 2: Remove `flex` from `defaultColDef`**

Replace the `defaultColDef` memo with:

```js
  const defaultColDef = useMemo(
    () => ({
      // No `flex` here. With flex set, ag-grid recomputes widths to fill the
      // container and a manually dragged column springs back. autoSizeStrategy
      // below already gives the full-width first paint, and without flex a
      // dragged width holds.
      minWidth: 140,
      resizable: true,
      sortable: true,
      floatingFilter: false,
      wrapHeaderText: true,
      autoHeaderHeight: true,
    }),
    [],
  );
```

- [ ] **Step 3: Add the pagination handler**

Add this beside the other callbacks, above the `if (!headings.length || !rows.length)` guard. It must exist before Step 4 references it.

```js
  // newPageSize distinguishes a size change from a page turn; only the former
  // changes how tall the grid should be.
  const onPaginationChanged = useCallback((event) => {
    if (event.newPageSize) {
      setPageSize(event.api.paginationGetPageSize());
    }
  }, []);
```

- [ ] **Step 4: Replace the layout calculation and the grid element**

Replace the block from `const paginated = rows.length > PAGE_SIZE;` through the closing `</div>` of `sqlchat-grid-body` with:

```js
  const { paginated, height } = gridLayout(rows.length, pageSize);

  return (
    <div className="sqlchat-grid">
      <div className="sqlchat-grid-tools">
        <span className="sqlchat-grid-count">
          {result.row_count ?? rows.length}{" "}
          {(result.row_count ?? rows.length) === 1 ? "row" : "rows"}
          {result.truncated ? " · showing the first 20" : ""}
        </span>
        <span className="sqlchat-grid-actions">
          <button type="button" onClick={exportCsv}>
            CSV
          </button>
          <button type="button" onClick={exportExcel}>
            Excel
          </button>
        </span>
      </div>

      <div
        className="ag-theme-alpine sqlchat-grid-body"
        style={{ height }}
      >
        <AgGridReact
          ref={gridRef}
          rowData={rowData}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          headerHeight={32}
          rowHeight={34}
          pagination={paginated}
          paginationPageSize={pageSize}
          paginationPageSizeSelector={PAGE_SIZES}
          onPaginationChanged={onPaginationChanged}
          // Enterprise, and already licensed here: drag a range and Ctrl+C, or
          // right-click for copy-with-headers and export.
          enableRangeSelection={true}
          suppressMovableColumns={false}
          enableBrowserTooltips={false}
          suppressCellFocus={false}
          autoSizeStrategy={{ type: "fitGridWidth", defaultMinWidth: 140 }}
        />
      </div>
    </div>
  );
```

Note the `sqlchat-grid-tools` block is unchanged — it is repeated here only because the surrounding `return` is being replaced wholesale.

- [ ] **Step 5: Add the border CSS**

In `src/css/SqlChatbotPage.css`, immediately after the existing `.sqlchat .sqlchat-grid-body.ag-theme-alpine { ... }` block (starts line 300), add:

```css
/* Vertical rules between columns.

   ag-grid draws this border already -- its base stylesheet sets
   --ag-cell-horizontal-border to `solid transparent` and switches the header
   separator off -- so this makes an existing border visible rather than
   adding one. Scoped here, which is also why it cannot reach the app's other
   grids: those set their own values under .test_datatable_table. */
.sqlchat .sqlchat-grid-body.ag-theme-alpine {
  --ag-cell-horizontal-border: 1px solid var(--sc-line-soft);
  --ag-header-column-separator-display: block;
  --ag-header-column-separator-color: var(--sc-line);
  --ag-header-column-separator-width: 1px;
  --ag-header-column-separator-height: 100%;
}
```

- [ ] **Step 6: Verify by eye**

```bash
npx react-scripts start
```

Open the Ask the Data page and ask `Show AR_YD_Suiting items`. Confirm all five:

1. Vertical lines between columns, in the header and the body.
2. Dragging a column border resizes it and it **stays** where dropped.
3. A result over 10 rows shows a pager with previous/next, a page number and a page-size selector.
4. Choosing 10 makes the grid visibly shorter; choosing 100 makes it taller, capped.
5. Open a **Tasks** or **Reports** datatable: unchanged, no new borders.

Item 5 cannot fail given the scoping, but the original diagnosis of this was wrong, so look rather than assume.

- [ ] **Step 7: Commit**

```bash
git add src/components/SqlChatbot/ChatResultGrid.jsx src/css/SqlChatbotPage.css
git commit -m "Give the result grid borders, a page-size control and stable resizing

Three things, one component.

Resizing was already enabled and already broken: flex:1 on every column made
ag-grid recompute widths to fill the container, so a dragged column sprang
back. autoSizeStrategy alone gives the same full-width first paint and lets a
dragged width hold.

The missing vertical borders were not the shared theme's doing -- its
--ag-cell-horizontal-border:none is scoped to .test_datatable_table, which
this grid is not inside. ag-grid's own base default draws the border as
`solid transparent`. Five variables make it visible, scoped so the app's
other grids cannot be reached.

Pagination existed but gated on the default page size, hiding the new
selector for results between 11 and 25 rows.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Sticky auto-scroll

**Files:**
- Create: `src/components/SqlChatbot/useStickyScroll.js`
- Create: `src/components/SqlChatbot/useStickyScroll.test.js`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `isNearBottom({ scrollHeight, scrollTop, clientHeight }, threshold?) => boolean`
  - `THRESHOLD` — `80`
  - default export `useStickyScroll(contentRef)` — attaches the listeners; returns nothing.

  Task 8 calls the default export.

**Context — what actually scrolls.** Not the message list. `.sqlchat-messages` sets padding only, `<main>` in `Layout.jsx` is unstyled, and the page's CSS header states the design: the document scrolls and the toolbar, composer and rail are sticky against it. So the hook targets `document.scrollingElement` and listens on `window`. There is no container `scrollTop` to write.

The current behaviour being replaced is `SqlChatbotPage.jsx:252-254`, a `scrollIntoView` on a sentinel fired by every change to `turns` or `busy`.

Assigning `el.scrollTop = el.scrollHeight` rather than calling `window.scrollTo` is deliberate: jsdom implements the property but not the method, so the tests exercise the real code path instead of a stub.

- [ ] **Step 1: Write the failing tests**

Create `src/components/SqlChatbot/useStickyScroll.test.js`:

```js
import React, { useRef } from "react";
import { render, act } from "@testing-library/react";
import useStickyScroll, { isNearBottom, THRESHOLD } from "./useStickyScroll";

describe("isNearBottom", () => {
  it("is true when the document is at the bottom", () => {
    expect(
      isNearBottom({ scrollHeight: 1000, scrollTop: 200, clientHeight: 800 }),
    ).toBe(true);
  });

  it("is false when the reader has scrolled well up", () => {
    expect(
      isNearBottom({ scrollHeight: 5000, scrollTop: 0, clientHeight: 800 }),
    ).toBe(false);
  });

  it("is true just inside the threshold and false just outside it", () => {
    const inside = {
      scrollHeight: 2000,
      clientHeight: 800,
      scrollTop: 2000 - 800 - THRESHOLD,
    };
    const outside = {
      scrollHeight: 2000,
      clientHeight: 800,
      scrollTop: 2000 - 800 - THRESHOLD - 1,
    };
    expect(isNearBottom(inside)).toBe(true);
    expect(isNearBottom(outside)).toBe(false);
  });
});

describe("useStickyScroll", () => {
  let observerCallback;
  let originalResizeObserver;

  const Harness = () => {
    const content = useRef(null);
    useStickyScroll(content);
    return <div ref={content}>content</div>;
  };

  // jsdom has no ResizeObserver. The stub captures the callback so a test can
  // drive a growth event directly.
  beforeEach(() => {
    originalResizeObserver = global.ResizeObserver;
    observerCallback = null;
    global.ResizeObserver = class {
      constructor(callback) {
        observerCallback = callback;
      }
      observe() {}
      disconnect() {}
    };
  });

  afterEach(() => {
    global.ResizeObserver = originalResizeObserver;
  });

  const setGeometry = ({ scrollHeight, clientHeight, scrollTop }) => {
    const el = document.scrollingElement || document.documentElement;
    Object.defineProperty(el, "scrollHeight", {
      value: scrollHeight,
      configurable: true,
    });
    Object.defineProperty(el, "clientHeight", {
      value: clientHeight,
      configurable: true,
    });
    el.scrollTop = scrollTop;
    return el;
  };

  it("follows new content while pinned to the bottom", () => {
    render(<Harness />);
    const el = setGeometry({ scrollHeight: 2000, clientHeight: 800, scrollTop: 1200 });

    act(() => observerCallback());

    expect(el.scrollTop).toBe(2000);
  });

  it("does not move the view after the reader scrolls up", () => {
    render(<Harness />);
    const el = setGeometry({ scrollHeight: 5000, clientHeight: 800, scrollTop: 0 });

    act(() => window.dispatchEvent(new Event("scroll")));
    act(() => observerCallback());

    expect(el.scrollTop).toBe(0);
  });

  it("resumes once the reader returns to the bottom", () => {
    render(<Harness />);
    const el = setGeometry({ scrollHeight: 5000, clientHeight: 800, scrollTop: 0 });
    act(() => window.dispatchEvent(new Event("scroll")));

    // Back to the bottom, then more content arrives.
    el.scrollTop = 4200;
    act(() => window.dispatchEvent(new Event("scroll")));
    act(() => observerCallback());

    expect(el.scrollTop).toBe(5000);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
npx react-scripts test --watchAll=false src/components/SqlChatbot/useStickyScroll.test.js
```

Expected: FAIL — `Cannot find module './useStickyScroll'`.

- [ ] **Step 3: Write the implementation**

Create `src/components/SqlChatbot/useStickyScroll.js`:

```js
import { useEffect, useRef } from "react";

/**
 * Follow new content, unless the reader has scrolled away from the bottom.
 *
 * What scrolls here is the DOCUMENT, not the message list: .sqlchat-messages
 * sets padding and nothing else, <main> is unstyled, and the page is designed
 * to flow with the composer sticky against the document. So this reads and
 * writes document.scrollingElement and listens on window.
 *
 * It replaces a scrollIntoView() fired on every state change, which pulled
 * the reader back to the bottom whatever they were doing.
 */

/** How close to the bottom still counts as being at the bottom. */
export const THRESHOLD = 80;

/**
 * Pure so the three behaviours that matter -- follows, yields, resumes -- can
 * be asserted without a layout engine. jsdom has neither real layout nor
 * window.scrollTo.
 */
export function isNearBottom(
  { scrollHeight, scrollTop, clientHeight },
  threshold = THRESHOLD,
) {
  return scrollHeight - scrollTop - clientHeight <= threshold;
}

const scroller = () => document.scrollingElement || document.documentElement;

export default function useStickyScroll(contentRef) {
  // A ref, not state: this is read inside an observer callback and must never
  // re-render anything when it changes.
  const pinned = useRef(true);

  useEffect(() => {
    const onScroll = () => {
      const el = scroller();
      pinned.current = isNearBottom({
        scrollHeight: el.scrollHeight,
        scrollTop: el.scrollTop,
        clientHeight: el.clientHeight,
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const content = contentRef.current;
    if (!content || typeof ResizeObserver === "undefined") return undefined;

    // One observer covers every reason the transcript grows: a new turn, the
    // thinking dots, the answer landing, a debug panel opening, the grid
    // finishing its first render. None of them needs its own hook.
    const observer = new ResizeObserver(() => {
      if (!pinned.current) return;
      const el = scroller();
      el.scrollTop = el.scrollHeight;
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [contentRef]);
}
```

- [ ] **Step 4: Run to verify they pass**

```bash
npx react-scripts test --watchAll=false src/components/SqlChatbot/useStickyScroll.test.js
```

Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add src/components/SqlChatbot/useStickyScroll.js src/components/SqlChatbot/useStickyScroll.test.js
git commit -m "Follow the conversation without fighting the reader

The old effect called scrollIntoView on every change to turns or busy, so
scrolling up to re-read an earlier answer was undone by the next render.

This tracks whether the reader is within 80px of the bottom and only follows
while they are. Scrolling up yields; coming back resumes.

It scrolls the document, not the message list -- .sqlchat-messages is not a
scroll container, <main> is unstyled, and the page is built to flow with the
composer sticky against the document.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Copy a response

**Files:**
- Create: `src/components/SqlChatbot/answerToText.js`
- Create: `src/components/SqlChatbot/answerToText.test.js`
- Create: `src/components/SqlChatbot/CopyButton.jsx`
- Create: `src/components/SqlChatbot/CopyButton.test.jsx`
- Modify: `src/css/SqlChatbotPage.css` (append)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `answerToText(turn) => string`, where `turn` is `{ question: string, answer: object }`
  - default export `CopyButton({ turn })` — renders a `<button>` with accessible name `Copy response`, becoming `Copied` for 1.5s.

  Task 8 renders `CopyButton`.

**Context on the debug gate.** The spec asks for SQL "only when the turn was asked with debug on". That needs no flag: with debug off the server does not put `generated_sql` in the response at all. Testing for the field's presence *is* the gate, and it is the honest one — a flag could disagree with the payload.

Truncation matters. `result.rows` is capped server-side by `QueryRunner::MAX_ROWS`, with `result.row_count` holding the true total and `result.truncated` saying so. Copying 20 rows as though they were the whole answer would mislead, so the text says what it is.

- [ ] **Step 1: Write the failing tests for the text builder**

Create `src/components/SqlChatbot/answerToText.test.js`:

```js
import answerToText from "./answerToText";

const turnWith = (answer) => ({ question: "Show AR_YD_Suiting items", answer });

describe("answerToText", () => {
  it("starts with the question", () => {
    expect(answerToText(turnWith({}))).toMatch(/^Show AR_YD_Suiting items/);
  });

  it("includes every row the answer holds, tab separated", () => {
    const text = answerToText(
      turnWith({
        result: {
          column_labels: ["Item", "Colour"],
          rows: [
            ["AR_1", "black"],
            ["AR_2", "white"],
            ["AR_3", "navy"],
          ],
          row_count: 3,
        },
      }),
    );
    expect(text).toContain("Item\tColour");
    expect(text).toContain("AR_1\tblack");
    expect(text).toContain("AR_3\tnavy");
  });

  it("includes the SQL when the turn carries it", () => {
    const text = answerToText(
      turnWith({ generated_sql: "SELECT 1 FROM tms_task_flat" }),
    );
    expect(text).toContain("SELECT 1 FROM tms_task_flat");
  });

  it("omits the SQL when the turn does not carry it", () => {
    // Debug off: the server never sends generated_sql, so its absence is the
    // gate. There is nothing for this to hide.
    const text = answerToText(turnWith({ result: { columns: [], rows: [] } }));
    expect(text).not.toMatch(/SELECT/i);
  });

  it("says so when the rows are a truncated view", () => {
    const text = answerToText(
      turnWith({
        result: {
          columns: ["Item"],
          rows: [["AR_1"], ["AR_2"]],
          row_count: 400,
          truncated: true,
        },
      }),
    );
    expect(text).toContain("first 2 of 400");
  });

  it("includes a clarification and an error when present", () => {
    const text = answerToText(
      turnWith({ clarification: "Which business unit?", error: "no such column" }),
    );
    expect(text).toContain("Which business unit?");
    expect(text).toContain("no such column");
  });

  it("renders an empty cell for null rather than the word null", () => {
    const text = answerToText(
      turnWith({ result: { columns: ["A", "B"], rows: [[null, "x"]] } }),
    );
    expect(text).toContain("\tx");
    expect(text).not.toContain("null");
  });

  it("survives a turn with no answer at all", () => {
    expect(() => answerToText({ question: "hi", answer: null })).not.toThrow();
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
npx react-scripts test --watchAll=false src/components/SqlChatbot/answerToText.test.js
```

Expected: FAIL — `Cannot find module './answerToText'`.

- [ ] **Step 3: Write the text builder**

Create `src/components/SqlChatbot/answerToText.js`:

```js
/**
 * A whole answer as plain text, for the clipboard.
 *
 * Built from the answer object, never from the DOM. Reading the rendered grid
 * would copy the page ag-grid happens to be showing and would carry its markup
 * along; this copies what the answer holds.
 *
 * The SQL is included when the answer carries it, which is exactly when the
 * turn was asked with debug on -- the server omits the field otherwise. That
 * makes the payload the gate, so no flag here can disagree with it.
 */

const cell = (value) =>
  value === null || value === undefined ? "" : String(value);

const tsv = (headings, rows) =>
  [
    headings.join("\t"),
    ...rows.map((row) => row.map(cell).join("\t")),
  ].join("\n");

export default function answerToText(turn) {
  const answer = turn?.answer || {};
  const parts = [];

  if (turn?.question) parts.push(turn.question);
  if (answer.clarification) parts.push(answer.clarification);
  if (answer.error) parts.push(answer.error);

  const result = answer.result;
  const headings = result?.column_labels?.length
    ? result.column_labels
    : result?.columns || [];
  const rows = result?.rows || [];

  if (headings.length && rows.length) {
    parts.push(tsv(headings, rows));
    // The server caps rows and reports the true total. Pasting the cap as
    // though it were the answer would misrepresent it.
    if (result.truncated) {
      parts.push(`(first ${rows.length} of ${result.row_count} rows)`);
    }
  }

  if (answer.generated_sql) parts.push(answer.generated_sql);

  return parts.join("\n\n");
}
```

- [ ] **Step 4: Run to verify they pass**

```bash
npx react-scripts test --watchAll=false src/components/SqlChatbot/answerToText.test.js
```

Expected: PASS, 8 tests.

- [ ] **Step 5: Write the failing tests for the button**

Create `src/components/SqlChatbot/CopyButton.test.jsx`:

```jsx
import React from "react";
import { render, screen, act } from "@testing-library/react";
import CopyButton from "./CopyButton";

const turn = {
  question: "Show AR_YD_Suiting items",
  answer: { result: { columns: ["Item"], rows: [["AR_1"]] } },
};

describe("CopyButton", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    Object.assign(navigator, {
      clipboard: { writeText: jest.fn().mockResolvedValue(undefined) },
    });
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("copies the whole answer", async () => {
    render(<CopyButton turn={turn} />);
    const button = screen.getByRole("button", { name: /copy response/i });

    await act(async () => {
      button.click();
    });

    expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(1);
    expect(navigator.clipboard.writeText.mock.calls[0][0]).toContain("AR_1");
  });

  it("confirms, then returns to its resting label", async () => {
    render(<CopyButton turn={turn} />);

    await act(async () => {
      screen.getByRole("button", { name: /copy response/i }).click();
    });
    expect(screen.getByRole("button", { name: /copied/i })).toBeInTheDocument();

    act(() => {
      jest.advanceTimersByTime(1600);
    });
    expect(
      screen.getByRole("button", { name: /copy response/i }),
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run to verify they fail**

```bash
npx react-scripts test --watchAll=false src/components/SqlChatbot/CopyButton.test.jsx
```

Expected: FAIL — `Cannot find module './CopyButton'`.

- [ ] **Step 7: Write the button**

Create `src/components/SqlChatbot/CopyButton.jsx`:

```jsx
import React, { useCallback, useEffect, useRef, useState } from "react";
import answerToText from "./answerToText";

/**
 * Copy a whole answer.
 *
 * The async clipboard API needs a secure context, and this app is served over
 * plain HTTP in some environments, so there is a textarea fallback rather than
 * a button that silently does nothing.
 */

const CopyIcon = () => (
  <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
    <rect
      x="9" y="9" width="11" height="11" rx="2"
      fill="none" stroke="currentColor" strokeWidth="1.8"
    />
    <path
      d="M5 15V5a2 2 0 0 1 2-2h8"
      fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
    />
  </svg>
);

const CheckIcon = () => (
  <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
    <path
      d="M4 12.5l5 5L20 6.5"
      fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round"
    />
  </svg>
);

const writeToClipboard = async (text) => {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const scratch = document.createElement("textarea");
  scratch.value = text;
  scratch.setAttribute("readonly", "");
  scratch.style.position = "fixed";
  scratch.style.left = "-9999px";
  document.body.appendChild(scratch);
  scratch.select();
  document.execCommand("copy");
  document.body.removeChild(scratch);
};

const CopyButton = ({ turn }) => {
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = useCallback(async () => {
    try {
      await writeToClipboard(answerToText(turn));
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1500);
    } catch (exception) {
      // A blocked clipboard is the browser's decision, not an error to shout
      // about. The button simply does not confirm.
      setCopied(false);
    }
  }, [turn]);

  return (
    <button
      type="button"
      className={`sqlchat-copy${copied ? " is-copied" : ""}`}
      onClick={copy}
    >
      {copied ? <CheckIcon /> : <CopyIcon />}
      <span>{copied ? "Copied" : "Copy response"}</span>
    </button>
  );
};

export default React.memo(CopyButton);
```

- [ ] **Step 8: Run to verify they pass**

```bash
npx react-scripts test --watchAll=false src/components/SqlChatbot/CopyButton.test.jsx
```

Expected: PASS, 2 tests.

- [ ] **Step 9: Add the CSS**

Append to `src/css/SqlChatbotPage.css`, before the final `@media (prefers-reduced-motion: reduce)` block:

```css
/* ----------------------------------------------------------------- copy -- */

.sqlchat .sqlchat-copy {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  padding: 5px 10px;
  border: 1px solid var(--sc-line);
  border-radius: 8px;
  background: var(--sc-ground);
  color: var(--sc-muted);
  font: inherit;
  font-size: 12.5px;
  cursor: pointer;
  transition: color 0.12s ease, border-color 0.12s ease, background 0.12s ease;
}

.sqlchat .sqlchat-copy:hover {
  border-color: var(--sc-muted);
  color: var(--sc-ink);
}

.sqlchat .sqlchat-copy.is-copied {
  border-color: var(--sc-accent);
  color: var(--sc-accent);
  background: var(--sc-accent-soft);
}

.sqlchat .sqlchat-copy svg {
  flex: 0 0 auto;
}
```

- [ ] **Step 10: Commit**

```bash
git add src/components/SqlChatbot/answerToText.js src/components/SqlChatbot/answerToText.test.js src/components/SqlChatbot/CopyButton.jsx src/components/SqlChatbot/CopyButton.test.jsx src/css/SqlChatbotPage.css
git commit -m "Let an answer be copied whole

Built from the answer object rather than the rendered grid, so it copies
every row the answer holds instead of the page ag-grid happens to show, and
carries no markup.

The SQL rides along when the answer has it, which is exactly when the turn
was asked with debug on -- the server omits the field otherwise, so the
payload is the gate and no flag can disagree with it.

Truncated results say so: the server caps rows and reports the true total,
and pasting the cap unlabelled would misrepresent the answer.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: The composer — input box and send button

**Files:**
- Create: `src/components/SqlChatbot/Composer.jsx`
- Create: `src/components/SqlChatbot/Composer.test.jsx`
- Modify: `src/css/SqlChatbotPage.css:561-620` (replace the composer, textarea and send rules)

**Interfaces:**
- Consumes: nothing.
- Produces: default export `Composer({ value, onChange, onSubmit, onStop, busy })`.
  - `onChange(nextValue: string)` — the string, not the event.
  - `onSubmit()` — no arguments; the parent already holds the value.
  - `onStop()` — called when the stop control is pressed.
  - Accessible names: `Send` at rest, `Stop` while busy.

  Task 8 renders it.

**Context.** Today's markup is a `<form>` with a bare `textarea` and a text button reading `Send` / `Asking…`, styled at CSS 561-620. The textarea's JS cap is 160px while its CSS `max-height` is 180px — they disagree; both become 200.

The stop state is wiring, not new machinery: `send()` in `SqlChatbotPage.jsx` already creates an `AbortController` per turn and already swallows `CanceledError`.

Note the textarea is **not** disabled while busy. Today it is, which throws focus away mid-request and stops you drafting a follow-up. The send control changing to stop is what communicates the state.

- [ ] **Step 1: Write the failing tests**

Create `src/components/SqlChatbot/Composer.test.jsx`:

```jsx
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import Composer from "./Composer";

const setup = (props = {}) => {
  const handlers = {
    onChange: jest.fn(),
    onSubmit: jest.fn(),
    onStop: jest.fn(),
  };
  render(<Composer value="" busy={false} {...handlers} {...props} />);
  return handlers;
};

describe("Composer", () => {
  it("disables send when there is nothing to send", () => {
    setup({ value: "" });
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
  });

  it("disables send for whitespace only", () => {
    setup({ value: "   \n  " });
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
  });

  it("enables send once there is real input", () => {
    setup({ value: "how many tasks are delayed?" });
    expect(screen.getByRole("button", { name: /send/i })).toBeEnabled();
  });

  it("sends on Enter", () => {
    const { onSubmit } = setup({ value: "a question" });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("does not send on Shift+Enter, so multiline works", () => {
    const { onSubmit } = setup({ value: "a question" });
    fireEvent.keyDown(screen.getByRole("textbox"), {
      key: "Enter",
      shiftKey: true,
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does not send an empty question on Enter", () => {
    const { onSubmit } = setup({ value: "  " });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("offers stop instead of send while busy, and stops", () => {
    const { onStop, onSubmit } = setup({ value: "a question", busy: true });
    expect(screen.queryByRole("button", { name: /^send$/i })).toBeNull();

    screen.getByRole("button", { name: /stop/i }).click();

    expect(onStop).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("keeps the textbox usable while busy, so a follow-up can be drafted", () => {
    setup({ value: "", busy: true });
    expect(screen.getByRole("textbox")).toBeEnabled();
  });

  it("reports the value, not the event", () => {
    const { onChange } = setup({ value: "" });
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "typed" },
    });
    expect(onChange).toHaveBeenCalledWith("typed");
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
npx react-scripts test --watchAll=false src/components/SqlChatbot/Composer.test.jsx
```

Expected: FAIL — `Cannot find module './Composer'`.

- [ ] **Step 3: Write the component**

Create `src/components/SqlChatbot/Composer.jsx`:

```jsx
import React, { useCallback, useEffect, useRef } from "react";

/**
 * The question input.
 *
 * The container owns the border and the focus ring; the textarea inside it is
 * transparent and borderless, so the whole box lights up as one thing on
 * focus. The textarea grows with the text to a cap and then scrolls.
 *
 * While a turn is in flight the send control becomes a stop control -- the
 * page already creates an AbortController per turn and already handles the
 * cancellation, so this only needed a button. The textarea stays enabled: a
 * disabled one throws focus away mid-request and stops you drafting the next
 * question.
 */

/** Past this the textarea scrolls rather than pushing the page around. */
const MAX_HEIGHT = 200;

const SendIcon = () => (
  <svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true">
    <path
      d="M12 19V6M6 12l6-6 6 6"
      fill="none" stroke="currentColor" strokeWidth="2.1"
      strokeLinecap="round" strokeLinejoin="round"
    />
  </svg>
);

const StopIcon = () => (
  <svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true">
    <rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" />
  </svg>
);

const Composer = ({ value, onChange, onSubmit, onStop, busy }) => {
  const textarea = useRef(null);
  const sendable = value.trim().length > 0;

  // Resize on every value change, not only on keystrokes: the value also
  // drops to "" when a question is sent, and the box has to shrink back.
  useEffect(() => {
    const node = textarea.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  const onKeyDown = useCallback(
    (event) => {
      if (event.key !== "Enter" || event.shiftKey) return;
      event.preventDefault();
      if (sendable && !busy) onSubmit();
    },
    [sendable, busy, onSubmit],
  );

  return (
    <form
      className="sqlchat-composer"
      onSubmit={(event) => {
        event.preventDefault();
        if (sendable && !busy) onSubmit();
      }}
    >
      <div className="sqlchat-composer-box">
        <textarea
          ref={textarea}
          rows={1}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask a question…"
          autoComplete="off"
        />
        {busy ? (
          <button
            type="button"
            className="sqlchat-send is-stop"
            onClick={onStop}
            aria-label="Stop"
            title="Stop"
          >
            <StopIcon />
          </button>
        ) : (
          <button
            type="submit"
            className="sqlchat-send"
            disabled={!sendable}
            aria-label="Send"
            title="Send"
          >
            <SendIcon />
          </button>
        )}
      </div>
    </form>
  );
};

export default React.memo(Composer);
```

- [ ] **Step 4: Run to verify they pass**

```bash
npx react-scripts test --watchAll=false src/components/SqlChatbot/Composer.test.jsx
```

Expected: PASS, 9 tests.

- [ ] **Step 5: Replace the composer CSS**

In `src/css/SqlChatbotPage.css`, replace everything from `.sqlchat .sqlchat-composer {` (line 561) through the end of `.sqlchat .sqlchat-send:not(:disabled):hover { ... }` (line 620) with:

```css
.sqlchat .sqlchat-composer {
  width: 100%;
  max-width: 820px;
  margin: 0 auto;
  box-sizing: border-box;
}

/* The container carries the border and the focus ring, so the box lights up
   as one object; the textarea inside is transparent and borderless. */
.sqlchat .sqlchat-composer-box {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 7px 7px 7px 16px;
  border: 1px solid var(--sc-line);
  border-radius: 24px;
  background: var(--sc-ground);
  box-shadow: 0 1px 2px rgb(16 24 40 / 5%);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.sqlchat .sqlchat-composer-box:hover {
  border-color: var(--sc-muted);
}

.sqlchat .sqlchat-composer-box:focus-within {
  border-color: var(--sc-accent);
  box-shadow: 0 0 0 3px var(--sc-accent-soft);
}

.sqlchat .sqlchat-composer-box textarea {
  flex: 1;
  max-height: 200px;
  padding: 8px 0;
  border: 0;
  background: none;
  color: var(--sc-ink);
  font: inherit;
  line-height: 1.5;
  resize: none;
  overflow-y: auto;
}

.sqlchat .sqlchat-composer-box textarea:focus {
  outline: none;
}

.sqlchat .sqlchat-composer-box textarea::placeholder {
  color: var(--sc-faint);
}

.sqlchat .sqlchat-send {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 0;
  border-radius: 50%;
  background: var(--sc-accent);
  color: #fff;
  cursor: pointer;
  transition: opacity 0.12s ease, background 0.12s ease, transform 0.12s ease;
}

.sqlchat .sqlchat-send:disabled {
  background: var(--sc-line);
  color: var(--sc-faint);
  cursor: default;
}

.sqlchat .sqlchat-send:not(:disabled):hover {
  opacity: 0.88;
}

.sqlchat .sqlchat-send:not(:disabled):active {
  transform: scale(0.94);
}

.sqlchat .sqlchat-send.is-stop {
  background: var(--sc-ink);
}
```

- [ ] **Step 6: Commit**

```bash
git add src/components/SqlChatbot/Composer.jsx src/components/SqlChatbot/Composer.test.jsx src/css/SqlChatbotPage.css
git commit -m "Give the composer a rounded box and an icon send button

The container now owns the border and the focus ring, so the whole box lights
up as one object rather than the textarea alone. The textarea grows to 200px
and then scrolls -- the JS cap said 160 and the CSS said 180, which is the
sort of disagreement nobody notices until a long question looks wrong.

The send button becomes a stop button while a turn is in flight. That needed
a control, not machinery: the page already aborts per turn and already
handles the cancellation.

The textarea is no longer disabled while busy. Disabling it threw focus away
mid-request and stopped you drafting a follow-up.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Extract and expand the debug panel

**Files:**
- Create: `src/components/SqlChatbot/DebugDetails.jsx` (moved from `SqlChatbotPage.jsx:51-127`, expanded)
- Create: `src/components/SqlChatbot/DebugDetails.test.jsx`
- Create: `src/components/SqlChatbot/StateRail.jsx` (moved from `SqlChatbotPage.jsx:131-220`, unchanged)
- Create: `src/components/SqlChatbot/show.js` (the helper at `SqlChatbotPage.jsx:38-47`, shared by both)

**Interfaces:**
- Consumes: `duration_ms` and `types` inside `answer.result`, from Task 1.
- Produces:
  - `show(value) => string` — default export of `show.js`
  - default export `DebugDetails({ answer })`
  - default export `StateRail({ answer, totals })`

  Task 8 renders both.

**Context.** `show()` moves to its own module because `DebugDetails` and `StateRail` both use it and they are becoming separate files. Copy it verbatim — it already handles null, undefined, empty string, booleans, arrays and objects.

The groups below restore the Python QA console's five-group layout, minus Scoring. Field names come from that console (`ui/app.js:278-335` in `wren-poc`).

Two fields are new to both implementations, and exist only because of Task 1: `Query time` from `result.duration_ms`, and `Column types` from `result.types`. **`duration_ms` is the query's own execution time and must not be labelled as the turn's latency** — `latency_ms`, already shown under Cost as `Took`, includes the model call.

- [ ] **Step 1: Move `show()` into its own module**

Create `src/components/SqlChatbot/show.js` with the function currently at `SqlChatbotPage.jsx:38-47`:

```js
/** A value as something printable, without inventing anything for absent ones. */
const show = (value) => {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") {
    const entries = Object.values(value);
    return entries.length ? entries.join(" · ") : "—";
  }
  return String(value);
};

export default show;
```

- [ ] **Step 2: Move `StateRail` into its own file**

Create `src/components/SqlChatbot/StateRail.jsx` containing the component from `SqlChatbotPage.jsx:131-220` **verbatim**, with these lines added at the top and bottom:

```jsx
import React from "react";
import show from "./show";
```

```jsx
export default StateRail;
```

Change nothing inside it. It is moving, not changing.

- [ ] **Step 3: Write the failing tests for the debug panel**

Create `src/components/SqlChatbot/DebugDetails.test.jsx`:

```jsx
import React from "react";
import { render, screen } from "@testing-library/react";
import DebugDetails from "./DebugDetails";

const fullAnswer = {
  decision: "follow_up",
  normalized_question: "show the AR_YD_Suiting items",
  generated_sql: "SELECT item FROM tms_business_object_flat",
  sql_valid: true,
  execution_success: true,
  result: {
    row_count: 22,
    columns: ["item", "colour"],
    types: ["text", "text"],
    duration_ms: 143.7,
    rows: [],
  },
  followup: {
    follow_up_required: true,
    type: "narrow",
    reason: "many rows",
    question: "Narrow it down?",
    allow_free_text: true,
    suggestions: [{ id: "only_active", action: { filter: "active" } }],
  },
  tokens: { prompt: 4000, cache_read: 3800, cache_write: 120, completion: 90 },
  latency_ms: 6498,
  tool_calls: 2,
};

describe("DebugDetails", () => {
  it("shows the query's own execution time in seconds", () => {
    render(<DebugDetails answer={fullAnswer} />);
    expect(screen.getByText("Query time")).toBeInTheDocument();
    expect(screen.getByText("0.1s")).toBeInTheDocument();
  });

  it("does not label the query time as the turn's latency", () => {
    // latency_ms 6498 is the whole turn including the model call; duration_ms
    // 143.7 is the query. Showing 6.5s as the query time would be a lie.
    render(<DebugDetails answer={fullAnswer} />);
    expect(screen.queryByText("6.5s")).not.toBeNull(); // present, as "Took"
    expect(screen.getByText("Query time").parentElement).not.toHaveTextContent(
      "6.5s",
    );
  });

  it("shows the rows returned and the column types", () => {
    render(<DebugDetails answer={fullAnswer} />);
    expect(screen.getByText("Rows returned")).toBeInTheDocument();
    expect(screen.getByText("22")).toBeInTheDocument();
    expect(screen.getByText("Column types")).toBeInTheDocument();
    expect(screen.getByText("text, text")).toBeInTheDocument();
  });

  it("shows the follow-up group", () => {
    render(<DebugDetails answer={fullAnswer} />);
    expect(screen.getByText("Follow-up")).toBeInTheDocument();
    expect(screen.getByText("Narrow it down?")).toBeInTheDocument();
    expect(screen.getByText("narrow")).toBeInTheDocument();
  });

  it("shows the full cost, including the weighted effective figure", () => {
    render(<DebugDetails answer={fullAnswer} />);
    // 4000 - 3800 + 3800*0.1 + 90 = 670
    expect(screen.getByText("Effective")).toBeInTheDocument();
    expect(screen.getByText("670")).toBeInTheDocument();
    expect(screen.getByText("Cache write")).toBeInTheDocument();
    expect(screen.getByText("Tool calls")).toBeInTheDocument();
  });

  it("does not show the scoring fields", () => {
    render(<DebugDetails answer={fullAnswer} />);
    expect(screen.queryByText(/semantic match/i)).toBeNull();
    expect(screen.queryByText(/projection/i)).toBeNull();
  });

  it("renders an em dash for a response missing the new fields", () => {
    const older = { decision: "new_block", result: { row_count: 3, rows: [] } };
    expect(() => render(<DebugDetails answer={older} />)).not.toThrow();
    expect(screen.getByText("Query time")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("renders nothing for a turn asked with debug off", () => {
    const { container } = render(<DebugDetails answer={{ result: {} }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 4: Run to verify they fail**

```bash
npx react-scripts test --watchAll=false src/components/SqlChatbot/DebugDetails.test.jsx
```

Expected: FAIL — `Cannot find module './DebugDetails'`.

- [ ] **Step 5: Write the expanded debug panel**

Create `src/components/SqlChatbot/DebugDetails.jsx`:

```jsx
import React from "react";
import show from "./show";

/**
 * What the backend decided about one turn.
 *
 * The grouping is the Python QA console's, restored: Understanding, Query,
 * Follow-up, Cost. Its fifth group, Scoring, is deliberately absent -- those
 * fields only mean anything against a known-correct answer, so in production
 * they would render "n/a" on every turn.
 *
 * Present only when the turn was asked with debug on. With it off the server
 * omits these fields entirely, so there is nothing here to hide.
 */

const Group = ({ label, pairs }) => (
  <div className="sqlchat-debug-block">
    <div className="sqlchat-debug-label">{label}</div>
    <dl className="sqlchat-kv">
      {pairs.map(([name, value]) => (
        <div key={name}>
          <dt>{name}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  </div>
);

const seconds = (ms) =>
  typeof ms === "number" ? `${(ms / 1000).toFixed(1)}s` : "—";

const DebugDetails = React.memo(function DebugDetails({ answer }) {
  // Present only when the turn was asked with debug on.
  if (!answer || answer.decision === undefined) return null;

  const result = answer.result || {};
  const followup = answer.followup || {};
  const tokens = answer.tokens || {};

  const total = (tokens.prompt || 0) + (tokens.completion || 0);
  // Cache reads bill at a fraction of fresh input, so this is the figure that
  // tracks what a turn actually costs.
  const effective =
    (tokens.prompt || 0) -
    (tokens.cache_read || 0) +
    (tokens.cache_read || 0) * 0.1 +
    (tokens.completion || 0);

  return (
    <div className="sqlchat-debug">
      {answer.generated_sql ? (
        <div className="sqlchat-debug-block">
          <div className="sqlchat-debug-label">Query</div>
          <pre className="sqlchat-sql">{answer.generated_sql}</pre>
        </div>
      ) : null}

      <Group
        label="Understanding"
        pairs={[
          ["Decision", show(answer.decision)],
          ["Understood as", show(answer.normalized_question)],
          [
            "Repairs",
            show(
              (answer.repairs || []).map(
                (repair) => `${repair.original} → ${repair.corrected}`,
              ),
            ),
          ],
          ["Resumed from", show(answer.resumed_from)],
          ["Answered without the model", show(answer.preflight_clarified)],
          ["Context sent", `${show(answer.context_chars)} chars`],
        ]}
      />

      <Group
        label="Query"
        pairs={[
          ["SQL valid", show(answer.sql_valid)],
          ["Executed", show(answer.execution_success)],
          ["Rows returned", show(result.row_count)],
          ["Columns", show(result.columns)],
          ["Column types", show(result.types)],
          // The query's own time. Not the turn's -- that is "Took", below,
          // and it includes the model call.
          ["Query time", seconds(result.duration_ms)],
          ["Stayed in schema", show(answer.schema_grounded)],
          ["Invented names", show(answer.hallucinated)],
          ["Failure category", show(answer.failure_category)],
          ["Database error", show(answer.raw_error)],
        ]}
      />

      <Group
        label="Follow-up"
        pairs={[
          ["Required", show(followup.follow_up_required)],
          ["Type", show(followup.type)],
          ["Reason", show(followup.reason)],
          ["Question", show(followup.question)],
          // Absent means allowed, so only an explicit false is a no.
          ["Free text allowed", show(followup.allow_free_text !== false)],
          [
            "Suggestions",
            show((followup.suggestions || []).map((each) => each.id)),
          ],
        ]}
      />

      <Group
        label="Cost"
        pairs={[
          ["Prompt", show(tokens.prompt)],
          ["From cache", show(tokens.cache_read)],
          ["Cache write", show(tokens.cache_write)],
          ["Reply", show(tokens.completion)],
          ["Total", total ? total.toLocaleString() : "—"],
          ["Effective", total ? Math.round(effective).toLocaleString() : "—"],
          ["Tool calls", show(answer.tool_calls)],
          ["Took", seconds(answer.latency_ms)],
        ]}
      />
    </div>
  );
});

export default DebugDetails;
```

- [ ] **Step 6: Run to verify they pass**

```bash
npx react-scripts test --watchAll=false src/components/SqlChatbot/DebugDetails.test.jsx
```

Expected: PASS, 8 tests.

- [ ] **Step 7: Commit**

```bash
git add src/components/SqlChatbot/DebugDetails.jsx src/components/SqlChatbot/DebugDetails.test.jsx src/components/SqlChatbot/StateRail.jsx src/components/SqlChatbot/show.js
git commit -m "Restore the debug groups the port had dropped

The Python QA console showed five groups; the React port showed three. This
brings back Understanding and Follow-up, and fills in the Cost figures --
cache writes, the total, the weighted effective cost and tool calls.

Two fields are new to both: the query's own execution time and the column
types. Neither existed anywhere before; QueryRunner computed them and
summary() discarded them.

Query time is labelled as the query's, not the turn's. Took already reports
the turn, and it includes the model call -- presenting one as the other would
make the panel lie about where the time went.

Scoring stays out. Those fields need a known-correct answer to mean anything,
so in production they would read n/a on every turn.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Wire the page together

**Files:**
- Modify: `src/pages/SqlChatbotPage.jsx` (remove lines 38-220, rewire the render)
- Modify: `src/css/SqlChatbotPage.css` (question bubble; turn animation; debug disclosure animation)

**Interfaces:**
- Consumes: `Composer`, `CopyButton`, `DebugDetails`, `StateRail`, `useStickyScroll`, `show` — all from Tasks 4-7.
- Produces: the finished page.

**Context.** This is the integration task. Everything it imports is already tested. `SqlChatbotPage.jsx` keeps `turns`, `busy`, `debug`, `error`, `health`, `openDebug`, the session id and the abort controller, and loses the three components and the helper that moved out.

- [ ] **Step 1: Replace the imports and delete the moved code**

At the top of `src/pages/SqlChatbotPage.jsx`, replace the import block with:

```jsx
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { askChatbot, getChatbotHealth } from "../api/SqlChatbotApi";
import ChatResultGrid from "../components/SqlChatbot/ChatResultGrid";
import Composer from "../components/SqlChatbot/Composer";
import CopyButton from "../components/SqlChatbot/CopyButton";
import DebugDetails from "../components/SqlChatbot/DebugDetails";
import StateRail from "../components/SqlChatbot/StateRail";
import useStickyScroll from "../components/SqlChatbot/useStickyScroll";
import "../css/SqlChatbotPage.css";
```

Then delete, identified by name rather than by line number — each deletion
shifts what follows, so counted ranges go stale as you work:

- the `show` arrow function and its `/** A value as something printable… */`
  comment
- the `/* ---- debug: a turn ---- */` banner comment and the whole
  `DebugDetails` component, down to its closing `});`
- the `/* ---- debug: the state rail ---- */` banner comment and the whole
  `StateRail` component, down to its closing `});`

Keep the file's opening docblock, the `STARTERS` array, the `newSessionId`
arrow function, and the `/* ---- the page ---- */` banner.

After deleting, the first thing below the imports should be the file docblock's
neighbours — `STARTERS`, `newSessionId`, then the page component.

- [ ] **Step 2: Replace the scroll effect**

Delete:

```jsx
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, busy]);
```

Change the `bottom` ref declaration to a content ref and drop the now-unused `textarea` ref (the `Composer` owns its own):

```jsx
  const sessionId = useRef(newSessionId());
  const resetNext = useRef(false);
  const abort = useRef(null);
  const messages = useRef(null);
```

Add the hook call immediately after the refs:

```jsx
  // Follows the transcript while the reader is at the bottom, and leaves them
  // alone when they are not.
  useStickyScroll(messages);
```

In `send()`, remove the `textarea.current?.focus();` line from the `finally` block — the ref is gone and focus is no longer taken away, because the textarea is never disabled.

Then delete the two handlers the `Composer` has taken over — `const onKeyDown = (event) => {…}` and `const onInput = (event) => {…}`, together with the `// Grow with the text, up to a point…` comment above `onInput`. Find them by name, not by line number: Step 1's deletions have already shifted everything below them. They are orphaned by this change and nothing else calls them. Leave every other function in the file alone.

- [ ] **Step 3: Add the stop handler**

Beside `reset`, add:

```jsx
  // The controller is already created per turn and CanceledError is already
  // handled in send(); this only gives the reader a way to trigger it.
  const stop = useCallback(() => {
    abort.current?.abort();
    setBusy(false);
  }, []);
```

- [ ] **Step 4: Rewire the render**

Attach the content ref to the message list — change:

```jsx
          <div className="sqlchat-messages">
```

to:

```jsx
          <div className="sqlchat-messages" ref={messages}>
```

Delete the sentinel `<div ref={bottom} />` near the end of the list.

Add the copy button inside the answer, directly after the `ChatResultGrid` element and before the `suggestions.length ?` block:

```jsx
                      <CopyButton turn={turn} />
```

Wrap the debug panel so it can animate — replace the `{openDebug[turn.key] ? (<DebugDetails answer={answer} />) : null}` expression with:

```jsx
                          <div
                            className="sqlchat-debug-reveal"
                            data-open={openDebug[turn.key] ? "true" : "false"}
                          >
                            <div>
                              <DebugDetails answer={answer} />
                            </div>
                          </div>
```

The panel now always renders and is revealed by the grid animation; `grid-template-rows` cannot animate an element that is not there.

Finally, replace the whole `<form className="sqlchat-composer"> ... </form>` block **and** the `<p className="sqlchat-hint">` that follows it with:

```jsx
            <Composer
              value={input}
              onChange={setInput}
              onSubmit={() => send(input)}
              onStop={stop}
              busy={busy}
            />

            <p className="sqlchat-hint">
              Enter to send · Shift+Enter for a new line
            </p>
```

- [ ] **Step 5: Add the remaining CSS**

In `src/css/SqlChatbotPage.css`, replace the `.sqlchat .sqlchat-question { ... }` block (line 182) with:

```css
.sqlchat .sqlchat-question {
  /* Only as wide as the question. The old rule was max-width alone, so a
     three-word question still stretched to 82% of the column. */
  width: fit-content;
  max-width: min(82%, 60ch);
  margin-left: auto;
  margin-bottom: 16px;
  padding: 9px 14px;
  border-radius: 14px 14px 4px 14px;
  background: var(--sc-raised);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  animation: sqlchat-rise 0.15s ease-out both;
}
```

Then append, before the final `prefers-reduced-motion` block:

```css
/* --------------------------------------------------------- disclosure -- */

/* 0fr to 1fr, because height:auto is not animatable and a fixed max-height
   would clip a long SQL statement. */
.sqlchat .sqlchat-debug-reveal {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.18s ease;
}

.sqlchat .sqlchat-debug-reveal[data-open="true"] {
  grid-template-rows: 1fr;
}

.sqlchat .sqlchat-debug-reveal > div {
  overflow: hidden;
}

.sqlchat .sqlchat-grid {
  animation: sqlchat-fade 0.2s ease both;
}

@keyframes sqlchat-fade {
  from {
    opacity: 0;
  }
}
```

Note `.sqlchat-answer` already has `animation: sqlchat-rise 0.22s ease both` and the `sqlchat-rise` keyframes already exist — the question bubble reuses them rather than defining a second set.

- [ ] **Step 6: Run the whole frontend suite**

```bash
npx react-scripts test --watchAll=false src/components/SqlChatbot src/App.test.js
```

Expected: PASS. 40 tests across six files, plus `App.test.js`. By file:
`chatGridLayout` 7, `useStickyScroll` 6, `answerToText` 8, `CopyButton` 2,
`Composer` 9, `DebugDetails` 8.

If `App.test.js` was already failing before this work, say so in the report rather than fixing it — it is outside this plan.

- [ ] **Step 7: Verify the page by hand**

```bash
npx react-scripts start
```

On the Ask the Data page, confirm:

1. A short question's bubble hugs the text; a long one wraps and stops at 60ch.
2. The composer is a rounded box; the whole box takes the focus ring; it grows to about 200px then scrolls.
3. Send is grey and disabled when empty, coloured when there is text.
4. While a question is in flight the button is a dark stop square, pressing it cancels, and the textarea stays typeable.
5. Ask three long questions, scroll up while the third is answering: the view **stays** where you put it. Scroll back to the bottom: it follows again.
6. `Copy response` copies question, rows and — with debug on — the SQL. It reads `Copied` for about a second and a half.
7. With debug on, `Show query and details` slides open. `Query time` and `Column types` have values, and `Follow-up` is populated.
8. `Query time` and `Took` are different numbers.

- [ ] **Step 8: Commit**

```bash
git add src/pages/SqlChatbotPage.jsx src/css/SqlChatbotPage.css
git commit -m "Assemble the page from its parts

SqlChatbotPage held three components, a helper and a scroll effect in 545
lines. Those now live in components/SqlChatbot with tests of their own, and
this file is composition plus the send and reset logic.

Behaviour changes along the way: the question bubble is as wide as its
question rather than 82% of the column, the debug panel slides rather than
appearing, and the transcript follows new content without dragging the reader
back when they have scrolled up to read.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Update the spec's record of what shipped

**Files:**
- Modify: `docs/superpowers/specs/2026-09-09-ask-the-data-ui-design.md` (wren-poc repo)

**Interfaces:** none.

**Context.** Three of the spec's claims were corrected while planning, and each correction is already written into the spec. This task exists to record the *outcome* — what was built, and anything found during implementation that the spec still gets wrong. A spec that quietly diverges from the code is worse than no spec.

- [ ] **Step 1: Note the outcome**

Append to the spec:

```markdown
---

## 11. Built

Implemented 9 September 2026, in eight tasks. See
`docs/superpowers/plans/2026-09-09-ask-the-data-ui.md`.

Three claims in this spec were corrected during planning, before any code was
written, and the corrections are inline above:

- **§3.2** blamed the shared theme for the missing borders. Wrong: that rule
  is scoped to `.test_datatable_table`. The cause is AG Grid's own
  `solid transparent` default, which means there was never any blast radius.
- **§5** had the hook scrolling the message list. Wrong: the document
  scrolls; the message list is not a scroll container.
- **§9** specified PHPUnit. The module has none, so the backend check follows
  the module's own script pattern instead.
```

If implementation found anything else the spec gets wrong, add it to that list.

- [ ] **Step 2: Commit**

```bash
cd "c:/Users/ansh.gala/Desktop/Python/wren-poc"
git add docs/superpowers/specs/2026-09-09-ask-the-data-ui-design.md
git commit -m "Record what the UI work actually built

Three claims in the spec were wrong and were corrected before implementation:
the cause of the missing grid borders, what element scrolls, and the
existence of PHPUnit in the module. Noting them so the spec is not read later
as though it had been right all along.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Coverage

Every requirement in the spec, and the task that implements it.

| Spec | Requirement | Task |
|---|---|---|
| §3.1 | Page-size selector, lower pager threshold | 2, 3 |
| §3.1a | Height follows page size | 2, 3 |
| §3.2 | Vertical borders, scoped | 3 |
| §3.3 | `flex` removed so resizing holds | 3 |
| §4.1 | `duration_ms` and `types` through `summary()` | 1 |
| §4.2 | Query, Follow-up and Cost groups; Scoring excluded | 7 |
| §5 | Sticky auto-scroll | 4, 8 |
| §6 | Animations, inside the reduced-motion guard | 5, 6, 8 |
| §7.1 | Copy response | 5, 8 |
| §7.2 | Question width | 8 |
| §7.3 | Send button, disabled and stop states | 6, 8 |
| §7.4 | Rounded, growing input box | 6 |
| §8 | Sidebar deferred — no sidebar built | — |
| §9 | Tests and manual checks | every task |
| §10 | Out of scope respected | Global Constraints |
