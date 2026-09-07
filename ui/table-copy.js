/* Turning a result table into text worth pasting.
 *
 * Its own file, and not part of app.js, for one reason: app.js is an IIFE with
 * no exports, so nothing in it can be tested without a browser. This can be,
 * and the formatting is where the fiddly cases live -- nulls, tabs inside a
 * value, an empty result.
 *
 * Tab-separated, because that is the one format that pastes correctly into a
 * spreadsheet and still reads as a table in a chat window or an editor. CSV
 * would need quoting rules and would paste into Excel as a single column.
 */

(function (root) {
  "use strict";

  /* A cell as text. Tabs and newlines inside a value would break the row and
   * column structure of the paste, so they collapse to spaces -- the shape of
   * the table matters more than a faithful copy of whitespace nobody can see. */
  function cell(value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/[\t\r\n]+/g, " ");
  }

  /* headers: the readable labels. rows: arrays of values, in column order. */
  function tableToText(headers, rows) {
    const lines = [];
    const head = (headers || []).map(cell);
    if (head.length) lines.push(head.join("\t"));
    for (const row of rows || []) lines.push((row || []).map(cell).join("\t"));
    return lines.join("\n");
  }

  const api = { tableToText: tableToText, cell: cell };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TableCopy = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
