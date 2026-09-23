/* The SSE reader, against chunk boundaries that fall in awkward places.
 *
 * Run: node --test "ui/*.test.js"
 *
 * A network chunk can end anywhere -- between the two newlines that separate
 * events, inside a JSON string, or mid-UTF-8-character. Get the buffering
 * wrong and it still works in testing, because a small local response usually
 * arrives in one piece; it fails on a slow connection, which is the one place
 * nobody is watching. So the same body is replayed at several chunk sizes,
 * including one byte at a time.
 *
 * api.js is a browser IIFE assigning to a const, so it is evaluated with the
 * handful of globals it touches stubbed out.
 */

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { TextDecoder, TextEncoder } = require("node:util");

const SOURCE = fs.readFileSync(path.join(__dirname, "api.js"), "utf8");

const ROWS = '{"generated_sql":"SELECT 1","result":{"rows":[[3]],"row_count":1}}';
const ANSWER = '{"generated_sql":"SELECT 1","result":{"rows":[[3]],"row_count":1},' +
  '"followup":{"type":"none","suggestions":[]},"state":{"entity":"x"}}';
const BODY = `event: rows\ndata: ${ROWS}\n\nevent: answer\ndata: ${ANSWER}\n\n`;

/* api.js with `fetch` replaced by one that serves `body` in `size`-byte
   chunks. A fresh evaluation per call, so no state leaks between cases. */
function apiServing(body, size) {
  const bytes = Buffer.from(body, "utf8");
  let i = 0;
  const context = {
    window: { ReadableStream: true, TextDecoder: true },
    location: { protocol: "http:", origin: "http://test" },
    AbortController: class { constructor() { this.signal = null; } abort() {} },
    TextDecoder,
    setTimeout,
    clearTimeout,
    JSON,
    Error,
    fetch: async () => ({
      ok: true, status: 200, statusText: "OK",
      body: {
        getReader: () => ({
          read: async () => {
            if (i >= bytes.length) return { done: true };
            const slice = bytes.subarray(i, i + size);
            i += size;
            return { done: false, value: new Uint8Array(slice) };
          },
        }),
      },
    }),
  };
  return new Function(...Object.keys(context), `${SOURCE}; return API;`)(
    ...Object.values(context));
}

for (const size of [BODY.length, 64, 7, 1]) {
  const label = size === BODY.length ? "one chunk" : `${size}-byte chunks`;

  test(`rows arrive before the answer, in ${label}`, async () => {
    const seen = [];
    const answer = await apiServing(BODY, size).streamMessageToBackend(
      { question: "q" }, { useMock: false, onRows: (r) => seen.push(r) });

    assert.strictEqual(seen.length, 1, "the rows event was missed or repeated");
    assert.deepStrictEqual(seen[0].result.rows, [[3]]);
    assert.deepStrictEqual(answer.result.rows, [[3]]);
    assert.strictEqual(answer.state.entity, "x");
  });
}

test("a clarification sends no rows, and the page still gets its answer", async () => {
  const body = 'event: answer\ndata: {"clarification":"which one?"}\n\n';
  const seen = [];
  const answer = await apiServing(body, 5).streamMessageToBackend(
    { question: "q" }, { useMock: false, onRows: (r) => seen.push(r) });

  assert.deepStrictEqual(seen, []);
  assert.strictEqual(answer.clarification, "which one?");
});

test("a stream that ends without an answer is an error, not a blank turn", async () => {
  const body = `event: rows\ndata: ${ROWS}\n\n`;
  await assert.rejects(
    apiServing(body, 16).streamMessageToBackend({ question: "q" }, { useMock: false }),
    /without an answer/);
});

test("an error event is raised rather than silently dropped", async () => {
  const body = 'event: error\ndata: {"error":"the database refused"}\n\n';
  await assert.rejects(
    apiServing(body, 9).streamMessageToBackend({ question: "q" }, { useMock: false }),
    /the database refused/);
});

test("onRows is optional", async () => {
  const answer = await apiServing(BODY, 11).streamMessageToBackend(
    { question: "q" }, { useMock: false });
  assert.deepStrictEqual(answer.result.rows, [[3]]);
});
