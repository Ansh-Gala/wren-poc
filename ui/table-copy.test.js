/* Run: node --test ui/
 *
 * node --test is built in, so the console keeps its "no build step, no
 * dependencies" property while the formatting still gets tested.
 */

const test = require("node:test");
const assert = require("node:assert");

const { tableToText, cell } = require("./table-copy.js");

test("headers and rows come out tab-separated", () => {
  const out = tableToText(
    ["Task Id", "Task Display Name", "Task SLA Status"],
    [[1775, "Finalize number of designs", "Delayed"],
     [1787, "Design making in CAD/Software", "On Time"]],
  );
  assert.strictEqual(out,
    "Task Id\tTask Display Name\tTask SLA Status\n" +
    "1775\tFinalize number of designs\tDelayed\n" +
    "1787\tDesign making in CAD/Software\tOn Time");
});

test("the readable labels are what gets copied, not the column names", () => {
  const out = tableToText(["Business Object Ref Id"], [["22-Feb-26_13_Clothing"]]);
  assert.ok(out.startsWith("Business Object Ref Id"));
  assert.ok(!out.includes("business_object_ref_id"));
});

test("one row copies as header plus row", () => {
  assert.strictEqual(tableToText(["Count"], [[22]]), "Count\n22");
});

test("many rows all copy, not just the page shown", () => {
  const rows = Array.from({ length: 250 }, (_, i) => [i, `task ${i}`]);
  const out = tableToText(["Id", "Name"], rows);
  const lines = out.split("\n");
  assert.strictEqual(lines.length, 251);
  assert.strictEqual(lines[250], "249\ttask 249");
});

test("an empty result copies its headers rather than throwing", () => {
  assert.strictEqual(tableToText(["Task Id"], []), "Task Id");
});

test("no headers and no rows is the empty string", () => {
  assert.strictEqual(tableToText([], []), "");
  assert.strictEqual(tableToText(null, null), "");
  assert.strictEqual(tableToText(undefined, undefined), "");
});

test("NULL cells copy as empty, not as the word null", () => {
  // The table renders NULL so the reader can see it; a paste into a
  // spreadsheet wants the cell actually empty.
  assert.strictEqual(tableToText(["A", "B"], [[null, undefined]]), "A\tB\n\t");
});

test("zero and false survive, because they are values", () => {
  assert.strictEqual(tableToText(["A", "B"], [[0, false]]), "A\tB\n0\tfalse");
});

test("a tab or newline inside a value cannot break the table", () => {
  const out = tableToText(["Note"], [["line one\nline two"]], []);
  assert.strictEqual(out, "Note\nline one line two");
  assert.strictEqual(cell("a\tb"), "a b");
  assert.strictEqual(cell("a\r\n\r\nb"), "a b");
});

test("special characters and non-ASCII are copied as they are", () => {
  const out = tableToText(["Type"], [["AR_YD_Suiting & Co. — 50% \"quoted\""]]);
  assert.ok(out.includes("AR_YD_Suiting & Co. — 50% \"quoted\""));
});

test("a ragged row does not throw", () => {
  // Defensive: the server sends rows of uniform width, but a copy button is
  // not the place to discover otherwise.
  assert.strictEqual(tableToText(["A", "B"], [[1], null]), "A\tB\n1\n");
});
