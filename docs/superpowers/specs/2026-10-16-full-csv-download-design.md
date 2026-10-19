# Full CSV download for large chatbot results — design

Date: 2026-10-16. Repos: Drupal `vf_sql_chatbot` and the React frontend.
PHP-only: Python is not changed, and parity does not cover `ChatRuntime`.

## Goal

- The chat table shows at most 200 rows.
- When a result has more rows, a "Show More Data" button opens a modal.
- The modal asks the backend to run the question's SQL again with no row cut.
  It shows a spinner while it waits, then a "Download CSV" button that saves
  every row.
- If the request fails, the modal shows an error message and "Try again".

## Decisions (agreed with the user)

| Question | Decision |
|---|---|
| Who builds the backend | Me, in `vf_sql_chatbot` |
| Where the 200 cut happens | Backend sends 200. Frontend also cuts to 200 as a guard. |
| When the button shows | Only when `truncated` is true (more than 200 rows) |
| The existing CSV / Excel downloads | No change. They export the rows on screen. |
| How the file arrives | One GET request. The reply body is the CSV. No file is stored on the server, because the server cannot write files (gotchas §19). |

## Backend

### A. Cut the shown rows to 200

`ChatRuntime` adds a constant `SHOWN_ROWS = 200`. Before `presentRows()`, in
both `toResponse()` and `rowsEvent()`, the summary is cut:

- `rows` = the first 200 rows.
- `row_count` = the full count. It does not change.
- `truncated` = `row_count > 200`.

These things do not change:
- The raw turn result `$r['actual_result']`. `recordTurn()` and the history
  metadata still see the full result.
- Charts. `ChartCheck` refuses more than 100 rows, and it already refuses
  results with `truncated`.

### B. Tell the browser which question this is

`ChatRuntime::ask()` gets `$chatId` from `store->save()`, which runs **after**
`toResponse()`. So, right after `save()`, `ask()` sets
`$full['result']['download'] = ['chat_id' => $chatId, 'turn' => $turnIndex + 1]`.
It does this only when `$chatId` is not NULL and `result.truncated` is true.
`turn` is the stored `sequence_number`. `toResponse()` does not change its
signature.

Add `download` to `Redactor::PUBLIC_RESULT_FIELDS`. Both values are integers
and name no table or column.

The streamed `rows` event does not get `download`. The chat id does not exist
yet at that time. The `answer` event, which is always complete, carries it.

### C. New endpoint

`GET /api/sql-chat/chats/{chat_id}/turns/{turn}/csv`

It is a route plus a controller (`CsvController::download`), the same as
`StreamController`, because it does not return JSON. The route requires
`_permission: 'use vf sql chatbot'` and has `no_cache: TRUE`.

Steps:
1. `store->openChat($chat_id)`. If it returns NULL, return 404 `{"error": "No such chat."}`.
   This is the ownership check.
2. Find the turn whose `sequence_number` is `(int) $turn`, with status
   `TurnOutcome::SUCCESS` and a `generated_sql` that is not empty. If there is
   none, return 404 `{"error": "No such answer."}`.
3. `safety->assertReadOnly($sql)`, then `schemaChecker->check($sql)['grounded']`.
   If either fails, return 422 with a fixed sentence. Do not echo the SQL.
4. `queryRunner->runReadonly($sql)`, with the configured 100 s timeout.
   If it fails, return 500 `{"error": redactor->safeError(error, sqlstate)}`.
5. Build the CSV in memory with `fputcsv` on `php://temp`:
   - The header row is `labels->withColumnLabels(['columns' => ...])['column_labels']`.
   - The rows are the values from `QueryRunner::summary()` (JSON-safe values).
   - The columns are in the SQL's order. Hidden columns are included.
   - A text cell that starts with `=`, `+`, `-`, `@`, a tab or a CR gets a
     leading `'`. This stops formula injection in Excel. Numbers are not changed.
6. Return `text/csv; charset=utf-8` with a UTF-8 BOM and
   `Content-Disposition: attachment; filename="chat-<id>-answer-<turn>.csv"`.
   No `X-Row-Count` header: the site's CORS setting has `exposedHeaders: false`,
   so the browser could not read it.

Notes:
- If the model's SQL has its own `LIMIT`, the limit stays. It is part of the answer.
- The SQL runs again now, so the data can differ a little from the table on screen.
- Clear the cache once after deploy: there is a new route and a new controller (gotchas §3).

## Frontend

- `src/api/Constants.jsx`: no change. The path is built from the existing
  `SqlChatChatsUrl` as `${SqlChatChatsUrl}/${chatId}/turns/${turn}/csv`.
- `src/api/SqlChatbotApi.jsx`: add
  `downloadFullCsv({ chatId, turn, signal })`. It uses `jsonConfig(url, "get")`
  with `params: {}` (no `_format`) and `responseType: "blob"`. It returns
  the Blob.
- `ChatResultGrid.jsx`:
  - `rows = (result?.rows || []).slice(0, 200)`.
  - When `result.truncated && result.download`, show a "Show More Data" button
    in `.sqlchat-grid-actions`. A click calls
    `setModalState({ show: true, modalType: "SqlChatFullCsv", data: { ...result.download, fileName } })`.
- New `src/components/Modals/SqlChatFullCsv.jsx`, registered in `Modals/index.jsx`.
  It uses react-bootstrap `Modal`, `ModalCloseBtn` and Bootstrap's
  `spinner-border` (the app's `three-quarter-spinner` is white, made for a dark
  overlay, and does not show on a white modal).
  The request starts when the modal opens. An `AbortController` stops it when
  the modal closes. It has three states:
  - **Loading:** a spinner and "Preparing the full file…".
  - **Done:** "The file is ready." and a **Download CSV** button. The button saves
    the Blob through an object URL as `<fileName>-full.csv`.
  - **Error:** a 404 shows "This answer can no longer be found." Any other
    error shows "The file could not be made. Please try again." The modal also
    shows a **Try again** button.

## Out of scope

- Chats opened again from history. Their rows are never saved, so they show
  no table and no button.
- Excel for the full result.
- The Python pipeline.

## Checks

- **Backend:** a scratchpad bootstrap script on a real turn. It signs in as a
  test user with a sentinel session. It checks these things:
  - A result with more than 200 rows gives `rows` = 200, the full `row_count`,
    `truncated` = true, and a `download` field.
  - The CSV has `row_count` + 1 lines and the label header.
  - Another user's chat gives 404.
  - A bad turn number gives 404.
- **Backend:** the existing harnesses still pass: `tests/context/check.php`,
  `adversarial.php`, `outcome/check.php`, `provider/check.php`, and parity.
- **No smoke-question run:** `run_suite.php` calls `TurnRunner` directly and
  never reaches `ChatRuntime`, so it cannot test this change. The user's
  browser test covers the live path.
- **Frontend:** ESLint on the changed files, then `npm run dev` with
  "compiled successfully". The user tests the UI.
- **Branches:** feature branches in both repos. Merge only when the user confirms.
