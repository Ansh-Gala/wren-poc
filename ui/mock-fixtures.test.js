/* The mock must answer in the same shape the server does.
 *
 * Run: node --test "ui/*.test.js"
 *
 * Checked as text rather than by loading mock.js, which is a browser IIFE
 * assigning to window. A structural check is enough for the thing that goes
 * wrong: a fixture that returns rows without the readable headings, which the
 * console then renders using raw column names.
 */

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const mock = fs.readFileSync(path.join(__dirname, "mock.js"), "utf8");

test("every mock result carries column_labels beside columns", () => {
  const columns = (mock.match(/\bcolumns:/g) || []).length;
  const labels = (mock.match(/\bcolumn_labels:/g) || []).length;
  assert.ok(columns > 0, "expected the mock to define some results");
  assert.strictEqual(labels, columns,
    `${columns} result(s) define columns but only ${labels} define ` +
    "column_labels; the console would fall back to raw column names");
});

test("the mock never labels a column with its own database name", () => {
  // A label containing an underscore means someone pasted the column name in.
  const declared = mock.match(/column_labels:\s*(\[[^\]]*\]|[A-Z_]+)/g) || [];
  for (const block of declared) {
    assert.ok(!/"[a-z0-9]+_[a-z0-9_]+"/.test(block),
      `looks like a raw column name in ${block}`);
  }
});
