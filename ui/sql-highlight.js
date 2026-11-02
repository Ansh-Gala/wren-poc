/* SQL coloured the way VS Code's Dark+ theme colours it.
 *
 * Run the tests: node --test ui/
 *
 * Builds DOM nodes, never an HTML string: the SQL carries values typed by
 * users and read from the database, and a value is text, whatever it says.
 * Lossless by construction -- the tokens joined back together are the input,
 * character for character -- so colouring can never change what is shown.
 */

const SqlHighlight = (() => {

  const KEYWORDS = new Set(`
    select from where and or not in is null as on join left right inner outer full
    cross natural lateral using group by order having limit offset distinct case when
    then else end with recursive union all intersect except like ilike similar to
    between exists any some asc desc nulls first last over partition filter within
    window rows range preceding following current row unbounded interval true false
    cast at time zone escape fetch next only percent ties array values
  `.trim().split(/\s+/));

  const TYPES = new Set(`
    int integer bigint smallint numeric decimal real double precision float text
    varchar char character boolean bool date timestamp timestamptz interval json
    jsonb uuid
  `.trim().split(/\s+/));

  // A PII alias inside a string: PERSON_001, LOCATION_002 (pipeline/pii.py).
  const ALIAS = /\b(?:PERSON|EMAIL|LOCATION|COMPANY|VENDOR|AGE|PHONE)_\d{3,}\b/g;

  // In order: the first that matches at the cursor wins.
  const RULES = [
    ["space", /^\s+/],
    ["comment", /^--[^\n]*/],
    ["comment", /^\/\*[\s\S]*?(?:\*\/|$)/],
    ["string", /^[eEnN]?'(?:[^']|'')*(?:'|$)/],
    ["string", /^\$\$[\s\S]*?(?:\$\$|$)/],
    ["ident", /^"(?:[^"]|"")*(?:"|$)/],
    ["number", /^\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/],
    ["word", /^[A-Za-z_][A-Za-z0-9_$]*/],
    ["op", /^(?:::|<>|!=|<=|>=|\|\||[-+*\/%=<>(),.;\[\]:])/],
    ["other", /^[\s\S]/],
  ];

  function tokenize(sql) {
    const out = [];
    let rest = String(sql ?? "");
    while (rest) {
      for (const [type, pattern] of RULES) {
        const m = pattern.exec(rest);
        if (!m) continue;
        out.push({ type, text: m[0] });
        rest = rest.slice(m[0].length);
        break;
      }
    }
    // Words take their colour from what they are and what follows them.
    for (let i = 0; i < out.length; i++) {
      const tok = out[i];
      if (tok.type !== "word") continue;
      const lower = tok.text.toLowerCase();
      const next = out.slice(i + 1).find((t) => t.type !== "space");
      if (next && next.text === "(" && !KEYWORDS.has(lower)) tok.type = "function";
      else if (TYPES.has(lower)) tok.type = "type";
      else if (KEYWORDS.has(lower)) tok.type = "keyword";
      else tok.type = "ident";
    }
    return out;
  }

  /* A DocumentFragment of spans, one per token. `doc` is the document to
     build with, so the tests can hand in a stand-in. */
  function render(sql, doc = document) {
    const fragment = doc.createDocumentFragment();
    for (const tok of tokenize(sql)) {
      if (tok.type === "space" || tok.type === "other") {
        fragment.appendChild(doc.createTextNode(tok.text));
        continue;
      }
      const span = doc.createElement("span");
      span.className = `sql-${tok.type}`;
      if (tok.type === "string") appendString(span, tok.text, doc);
      else span.textContent = tok.text;
      fragment.appendChild(span);
    }
    return fragment;
  }

  function appendString(span, text, doc) {
    let at = 0;
    for (const m of text.matchAll(ALIAS)) {
      if (m.index > at) span.appendChild(doc.createTextNode(text.slice(at, m.index)));
      const alias = doc.createElement("span");
      alias.className = "sql-alias";
      alias.textContent = m[0];
      alias.title = "PII alias: the real value goes in only when the query runs";
      span.appendChild(alias);
      at = m.index + m[0].length;
    }
    if (at < text.length) span.appendChild(doc.createTextNode(text.slice(at)));
  }

  /* Two versions of a statement, line by line: [{op, text}] with op " " for
     a line both share, "-" for one only `before` has, "+" for one only
     `after` has. A longest-common-subsequence diff, so lines that moved
     because a longer value re-wrapped the layout still pair up correctly. */
  function diffLines(before, after) {
    const a = String(before ?? "").split("\n");
    const b = String(after ?? "").split("\n");
    const lcs = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
    for (let i = a.length - 1; i >= 0; i--) {
      for (let j = b.length - 1; j >= 0; j--) {
        lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
      }
    }
    const out = [];
    let i = 0;
    let j = 0;
    while (i < a.length && j < b.length) {
      if (a[i] === b[j]) { out.push({ op: " ", text: a[i] }); i++; j++; }
      else if (lcs[i + 1][j] >= lcs[i][j + 1]) out.push({ op: "-", text: a[i++] });
      else out.push({ op: "+", text: b[j++] });
    }
    while (i < a.length) out.push({ op: "-", text: a[i++] });
    while (j < b.length) out.push({ op: "+", text: b[j++] });
    return out;
  }

  /* diffLines as coloured lines: one block per line, marked and tinted. */
  function renderDiff(before, after, doc = document) {
    const fragment = doc.createDocumentFragment();
    const kind = { " ": "same", "-": "del", "+": "add" };
    for (const line of diffLines(before, after)) {
      const row = doc.createElement("span");
      row.className = `diff-line diff-${kind[line.op]}`;
      const mark = doc.createElement("span");
      mark.className = "diff-mark";
      mark.textContent = line.op;
      row.appendChild(mark);
      row.appendChild(render(line.text, doc));
      fragment.appendChild(row);
    }
    return fragment;
  }

  return { tokenize, render, diffLines, renderDiff };
})();

if (typeof module !== "undefined") module.exports = SqlHighlight;
