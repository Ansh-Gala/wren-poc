/* Run: node --test ui/ */

const test = require("node:test");
const assert = require("node:assert");

const { tokenize, render, diffLines, renderDiff } = require("./sql-highlight.js");

const kinds = (sql) => tokenize(sql).filter((t) => t.type !== "space")
  .map((t) => `${t.type}:${t.text}`);

test("words are coloured by what they are", () => {
  assert.deepStrictEqual(
    kinds("SELECT COUNT(*) AS n FROM tms_task_flat WHERE x::integer > 1.5"),
    ["keyword:SELECT", "function:COUNT", "op:(", "op:*", "op:)", "keyword:AS", "ident:n",
     "keyword:FROM", "ident:tms_task_flat", "keyword:WHERE", "ident:x", "op:::",
     "type:integer", "op:>", "number:1.5"]);
});

test("strings, quoted names and comments stay whole", () => {
  assert.deepStrictEqual(
    kinds(`SELECT "Task Name" FROM t WHERE n = 'it''s -- not a comment' -- real\n/* b */`),
    ["keyword:SELECT", 'ident:"Task Name"', "keyword:FROM", "ident:t", "keyword:WHERE",
     "ident:n", "op:=", "string:'it''s -- not a comment'", "comment:-- real",
     "comment:/* b */"]);
});

test("a keyword called like a function is a function, case aside", () => {
  assert.deepStrictEqual(kinds("select coalesce(a, 0), left(b, 2)"),
    ["keyword:select", "function:coalesce", "op:(", "ident:a", "op:,", "number:0", "op:)",
     "op:,", "keyword:left", "op:(", "ident:b", "op:,", "number:2", "op:)"]);
});

test("nothing is lost: the tokens rebuild the input exactly", () => {
  const sql = "SELECT  a\n  FROM t\tWHERE b = E'x\\n' AND c = $$y$$ AND d ~* 'z' # ?";
  assert.strictEqual(tokenize(sql).map((t) => t.text).join(""), sql);
  assert.strictEqual(tokenize("SELECT 'unterminated").map((t) => t.text).join(""),
                     "SELECT 'unterminated");
});

/* Just enough of a DOM to see what render builds. */
function fakeDocument() {
  const node = (props) => ({
    children: [],
    appendChild(child) { this.children.push(child); return child; },
    get text() { return this.textContent ?? this.children.map((c) => c.text).join(""); },
    ...props,
  });
  return {
    createDocumentFragment: () => node({ tag: "#fragment" }),
    createElement: (tag) => node({ tag, className: "", textContent: undefined }),
    createTextNode: (value) => ({ tag: "#text", text: value }),
  };
}

test("render builds text nodes, so markup in a value stays text", () => {
  const sql = "SELECT 1 WHERE name = '<img src=x onerror=alert(1)>'";
  const fragment = render(sql, fakeDocument());
  assert.strictEqual(fragment.text, sql);
  const str = fragment.children.find((c) => c.className === "sql-string");
  assert.strictEqual(str.children[0].tag, "#text");
});

test("the diff pairs the aliased and the executed SQL line by line", () => {
  const aliased = "SELECT\n  task_id\nFROM t\nWHERE\n  n = 'PERSON_001'\n  AND s = 'open'";
  const executed = "SELECT\n  task_id\nFROM t\nWHERE\n  n = 'Rahul Sharma'\n  AND s = 'open'";
  assert.deepStrictEqual(diffLines(aliased, executed).map((l) => `${l.op}${l.text}`), [
    " SELECT", "   task_id", " FROM t", " WHERE",
    "-  n = 'PERSON_001'", "+  n = 'Rahul Sharma'", "   AND s = 'open'"]);
  assert.deepStrictEqual(diffLines("a\nb", "a\nb").map((l) => l.op), [" ", " "]);
  // A longer value re-wrapping the layout still diffs cleanly.
  assert.deepStrictEqual(diffLines("x\ny = 'A'\nz", "x\ny =\n  'A long one'\nz").map((l) => l.op),
    [" ", "-", "+", "+", " "]);
});

test("the diff renders every line, marked, losing nothing", () => {
  const rows = renderDiff("a = 'PERSON_001'", "a = 'Rahul'", fakeDocument()).children;
  assert.deepStrictEqual(rows.map((r) => r.className), ["diff-line diff-del", "diff-line diff-add"]);
  assert.deepStrictEqual(rows.map((r) => r.text), ["-a = 'PERSON_001'", "+a = 'Rahul'"]);
});

test("a PII alias inside a string is marked out", () => {
  const fragment = render("WHERE n = 'PERSON_001' OR m ILIKE '%LOCATION_002%'", fakeDocument());
  const aliases = [];
  const walk = (n) => {
    if (n.className === "sql-alias") aliases.push(n.textContent);
    (n.children || []).forEach(walk);
  };
  walk(fragment);
  assert.deepStrictEqual(aliases, ["PERSON_001", "LOCATION_002"]);
  assert.strictEqual(fragment.text, "WHERE n = 'PERSON_001' OR m ILIKE '%LOCATION_002%'");
});
