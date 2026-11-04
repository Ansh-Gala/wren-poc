/* The console itself: chat, per-turn debug, and the setup panel.
 *
 * Everything rendered here comes from one response object, or from GET /info
 * for the panel. The console keeps no opinion of its own -- it shows what the
 * backend said, which is the only way a debugging view can be trusted.
 */

(() => {

  const $ = (id) => document.getElementById(id);

  const el = {
    messages: $("messages"),
    emptyHint: $("empty-hint"),
    composer: $("composer"),
    input: $("input"),
    send: $("send"),
    debugMode: $("debug-mode"),
    errorBanner: $("error-banner"),
    resetContext: $("reset-context"),
    clearChat: $("clear-chat"),
    setup: $("setup"),
    setupRail: $("setup-rail"),
    toggleSetup: $("toggle-setup"),
  };

  const session = {
    id: `qa-${Date.now()}`,
    resetPending: false,        // send reset_context on the next request
    turns: 0,
    busy: false,
    info: null,                 // GET /info: databases, modes and model
    last: null,                 // the last answer's tokens (debug answers only)
    tokens: { answers: 0, prompt: 0, completion: 0 },   // this chat, so far
    usage: null,                // this month, all users: { used, limit }
  };

  /* Per-browser preferences, kept across a refresh. Storage can be blocked
     (private windows, policies), so every read and write may fail; the page
     then simply starts with the defaults. */
  function remembered(key, fallback) {
    try {
      const value = localStorage.getItem(key);
      return value === null ? fallback : value === "1";
    } catch {
      return fallback;
    }
  }

  function remember(key, on) {
    try { localStorage.setItem(key, on ? "1" : "0"); } catch {}
  }

  // Debug is a request parameter, not a stylesheet. The server omits SQL,
  // schema names and diagnostics when this is off, so there is nothing in the
  // page to hide -- and nothing in the network tab either.
  function debugEnabled() {
    return Boolean(el.debugMode && el.debugMode.checked);
  }

  // Who is asking: the TMS user id from the page address (?user_id=12). Sent
  // as typed; the server refuses a missing or malformed one rather than
  // guessing.
  function userId() {
    return new URLSearchParams(location.search).get("user_id");
  }

  /* ------------------------------------------------------------ helpers */

  function text(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = String(value);
    return node;
  }

  /* "-" for absent, "n/a" for a field that only exists with ground truth.
     The difference matters: one is a gap, the other is not applicable. */
  function show(value, absent = "-") {
    if (value === null || value === undefined || value === "") return absent;
    if (Array.isArray(value)) return value.length ? value.join(", ") : absent;
    if (typeof value === "object") {
      const keys = Object.keys(value);
      return keys.length ? keys.map((k) => `${k}: ${value[k]}`).join("\n") : absent;
    }
    return String(value);
  }

  function kv(pairs) {
    const dl = text("dl", "kv");
    for (const [key, value, tone] of pairs) {
      dl.append(text("dt", null, key));
      const dd = text("dd", tone || (value === "-" || value === "n/a" ? "v-none" : null), value);
      dl.append(dd);
    }
    return dl;
  }

  function group(title, ...nodes) {
    const wrap = text("div", "debug-group");
    wrap.append(text("h4", null, title), ...nodes);
    return wrap;
  }

  /* sql-highlight.js declares a top-level const: global, but not a property
     of window, so it has to be looked for by name. */
  const highlighter = typeof SqlHighlight !== "undefined" ? SqlHighlight : null;

  /* SQL as VS Code shows it. Laid out by the server when it sent a laid-out
     copy; coloured here. Plain text if the highlighter did not load. */
  function sqlBlock(sql) {
    const pre = text("pre", "sql");
    pre.append(highlighter ? highlighter.render(sql) : document.createTextNode(sql));
    return pre;
  }

  /* The SQL of one answer. With PII aliasing on there are two versions --
     what the LLM wrote, with aliases, and what ran, with the real values --
     shown as a diff by default, either one a click away. Remembered across
     answers, so a reader comparing turns is not made to click every time. */
  let sqlView = "diff";

  function sqlViews(r) {
    const aliased = r.generated_sql_pretty || r.generated_sql;
    const p = r.pii;
    const executed = p && p.enabled ? (p.executed_sql_pretty || p.executed_sql) : null;
    if (!executed || executed === aliased) return sqlBlock(aliased);

    const views = {
      diff: ["Diff", () => {
        const pre = text("pre", "sql sql-diff");
        pre.append(highlighter ? highlighter.renderDiff(aliased, executed)
                               : document.createTextNode(`${aliased}\n\n${executed}`));
        return pre;
      }],
      aliased: ["LLM SQL (aliases)", () => sqlBlock(aliased)],
      executed: ["Executed SQL (real values)", () => sqlBlock(executed)],
    };
    const wrap = text("div", "sql-views");
    const tabs = text("div", "sql-tabs");
    const body = text("div");
    const pick = (key) => {
      sqlView = key;
      for (const tab of tabs.children) tab.classList.toggle("active", tab.dataset.view === key);
      body.replaceChildren(views[key][1]());
    };
    for (const [key, [label]] of Object.entries(views)) {
      const tab = text("button", "sql-tab", label);
      tab.type = "button";
      tab.dataset.view = key;
      tab.addEventListener("click", () => pick(key));
      tabs.append(tab);
    }
    wrap.append(tabs, body);
    pick(sqlView);
    return wrap;
  }

  /* Alias -> what it stands for. Real values: only ever drawn in debug. */
  function aliasTable(aliases) {
    const table = text("table", "alias-table");
    const head = document.createElement("tr");
    for (const h of ["alias", "real value", "type", ""]) head.append(text("th", null, h));
    table.append(head);
    for (const a of aliases) {
      const tr = document.createElement("tr");
      tr.append(text("td", "alias", a.alias), text("td", null, a.original),
                text("td", "muted", a.label), text("td", "tag-new", a.new ? "new" : ""));
      table.append(tr);
    }
    return table;
  }

  /* -------------------------------------------------------- chat render */

  function addUser(question) {
    el.emptyHint?.remove();
    const msg = text("div", "msg msg-user");
    msg.append(text("div", "bubble", question));
    el.messages.append(msg);
    scroll();
  }

  function addThinking() {
    const msg = text("div", "msg msg-bot");
    msg.append(text("div", "thinking", "thinking"));
    el.messages.append(msg);
    scroll();
    return msg;
  }

  function addError(message) {
    const msg = text("div", "msg msg-bot");
    const head = text("div", "head");
    head.append(text("span", "mode mode-error", "error"));
    msg.append(head, text("div", "error-text", message));
    el.messages.append(msg);
    scroll();
  }

  function addResponse(r) {
    const msg = text("div", "msg msg-bot");
    // Which turn this was, so turning debug on later can fill in its SQL.
    msg.dataset.turn = String(session.turns);

    // ---- head ------------------------------------------------------------
    // Most of this is diagnostic and the server does not send it with debug
    // off, so the whole block is conditional rather than each field guarded.
    const followup = r.followup || { type: "none", suggestions: [] };
    const head = text("div", "head");

    if (debugEnabled()) {
      const mode = r.decision || (followup.type === "clarification" ? "clarification" : "answer");
      head.append(text("span", `mode mode-${mode}`, mode));

      const repairs = r.repairs || [];
      if (repairs.length) head.append(text("span", "tag", `${repairs.length} repair(s)`));
      if (r.resumed_from) head.append(text("span", "tag", `resumed from "${r.resumed_from}"`));
      if (r.failure_category) head.append(text("span", "tag tag-bad", r.failure_category));
      if (r.execution_success === true) {
        head.append(text("span", "tag tag-ok", `${show((r.result || {}).row_count, "?")} row(s)`));
      } else if (r.sql_valid === false && r.generated_sql) {
        head.append(text("span", "tag tag-bad", "sql invalid"));
      }
      if (r.latency_ms !== null && r.latency_ms !== undefined) {
        head.append(text("span", "tag", `${(r.latency_ms / 1000).toFixed(1)}s`));
      }
    } else if (r.result && (r.result.row_count !== undefined || r.result.rows)) {
      // A row count is an answer, not a diagnostic.
      head.append(text("span", "tag tag-ok",
        `${show(r.result.row_count, (r.result.rows || []).length)} row(s)`));
    }
    if (head.childNodes.length) msg.append(head);

    // ---- what it said ----------------------------------------------------
    if (r.clarification) {
      msg.append(text("div", "clarify-text", r.clarification));
    }
    if (r.error) {
      msg.append(text("div", "error-text", r.error));
    }

    // ---- the SQL, always in the same place -------------------------------
    if (debugEnabled()) {
      if (r.generated_sql) {
        msg.append(sqlViews(r));
      } else if (!r.clarification && !r.error) {
        msg.append(text("pre", "sql sql-none", "no SQL generated"));
      }
    }

    const columnsPresent = r.result
      && ((r.result.column_labels || []).length || (r.result.columns || []).length);
    if (columnsPresent) {
      msg.append(resultTable(r.result));
    }

    // ---- suggestions as chips -------------------------------------------
    const suggestions = followup.suggestions || [];
    if (suggestions.length) {
      const chips = text("div", "chips");
      for (const s of suggestions) {
        const chip = text("button", "chip");
        chip.type = "button";
        chip.append(document.createTextNode(s.label));
        if (s.action && s.action.type) {
          chip.append(text("small", null, `  ${s.action.type}`));
        }
        // The chip sends its label as the next message, and carries the
        // structured action alongside so the backend need not re-derive it.
        chip.addEventListener("click", () => ask(s.label, s.action));
        chips.append(chip);
      }
      msg.append(chips);
    }

    if (debugEnabled()) msg.append(debugPane(r));
    el.messages.append(msg);
    scroll();
    // Returned so the table drawn from the `rows` event can be swapped for
    // the finished answer without the page jumping.
    return msg;
  }

  /* Copies the whole result, not the eight rows on screen. */
  function copyButton(headers, rows) {
    const button = text("button", "copy-btn", "Copy");
    button.type = "button";
    button.title = "Copy this table (tab-separated)";
    button.addEventListener("click", async () => {
      const payload = TableCopy.tableToText(headers, rows);
      try {
        await navigator.clipboard.writeText(payload);
      } catch {
        // The Clipboard API needs a secure context. 127.0.0.1 counts; a bare
        // LAN address does not, and this console is reached both ways.
        const scratch = document.createElement("textarea");
        scratch.value = payload;
        scratch.setAttribute("readonly", "");
        scratch.style.position = "fixed";
        scratch.style.opacity = "0";
        document.body.append(scratch);
        scratch.select();
        document.execCommand("copy");
        scratch.remove();
      }
      // Per button, so copying one table leaves every other one alone.
      button.textContent = "Copied";
      button.classList.add("copied");
      clearTimeout(button._reset);
      button._reset = setTimeout(() => {
        button.textContent = "Copy";
        button.classList.remove("copied");
      }, 1600);
    });
    return button;
  }

  function resultTable(result) {
    const wrap = text("div", "rows");

    // Labels are what the server sends for display; the raw column names only
    // arrive under debug, so they are the fallback rather than the source.
    const headers = result.column_labels || result.columns || [];
    const rows = result.rows || [];

    const bar = text("div", "rows-bar");
    bar.append(text("span", "rows-count",
      `${result.row_count ?? rows.length} row(s)` +
      (result.truncated ? " — preview truncated" : "")));
    bar.append(copyButton(headers, rows));
    wrap.append(bar);

    // The table scrolls inside its own box so the bar above, and the copy
    // button on it, stay where they were put.
    const scroller = text("div", "rows-scroll");
    const table = document.createElement("table");

    const thead = document.createElement("thead");
    const hrow = document.createElement("tr");
    for (const c of headers) hrow.append(text("th", null, c));
    thead.append(hrow);
    table.append(thead);

    const tbody = document.createElement("tbody");
    for (const row of rows.slice(0, 8)) {
      const tr = document.createElement("tr");
      for (const cell of row) {
        // Right-aligned only where the value is actually a figure; the class
        // does nothing in the debug view, which is monospaced throughout.
        const td = text("td", typeof cell === "number" ? "num" : null,
                        cell === null ? "NULL" : cell);
        tr.append(td);
      }
      tbody.append(tr);
    }
    table.append(tbody);
    scroller.append(table);
    wrap.append(scroller);
    return wrap;
  }

  /* --------------------------------------------------- per-turn debug */

  function debugPane(r) {
    const details = text("details", "debug");
    details.append(text("summary", null, "debug — this request"));
    const body = text("div", "debug-body");

    const llm = r.llm || {};
    body.append(group("Model", kv([
      ["model", show(llm.model, "CLI default")],
      ["provider", show(llm.provider)],
      ["mode", show(llm.mode)],
    ])));

    body.append(piiGroup(r));

    body.append(group("Understanding", kv([
      ["decision", show(r.decision)],
      ["original", show(r.question)],
      ["normalized", show(r.normalized_question)],
      ["repairs", (r.repairs || []).length
        ? r.repairs.map((x) => `${x.original} → ${x.corrected} (${x.kind})`).join(", ")
        : "-"],
      ["resumed from", show(r.resumed_from)],
      ["context chars", show(r.context_chars)],
    ])));

    body.append(group("Query", kv([
      ["sql valid", boolish(r.sql_valid), tone(r.sql_valid)],
      ["executed", boolish(r.execution_success), tone(r.execution_success)],
      ["row count", show(r.result.row_count)],
      ["columns", show(r.result.columns)],
      ["failure category", show(r.failure_category), r.failure_category ? "v-bad" : "v-none"],
      ["error", show(r.error), r.error ? "v-bad" : "v-none"],
    ])));

    // Only meaningful against a known-correct answer. Says so when absent
    // rather than showing a misleading "false".
    body.append(group("Scoring (needs ground truth)", kv([
      ["result match", boolish(r.result_match, "n/a"), tone(r.result_match)],
      ["semantic match", boolish(r.semantic_match, "n/a"), tone(r.semantic_match)],
      ["projection", show(r.projection_verdict, "n/a")],
      ["semantic issues", r.semantic_issues.length ? r.semantic_issues.join(" | ") : "-"],
    ])));

    const f = r.followup || {};
    body.append(group("Follow-up", kv([
      ["required", f.follow_up_required ? "yes" : "no"],
      ["type", show(f.type)],
      ["reason", show(f.reason)],
      ["question", show(f.question)],
      ["free text allowed", f.allow_free_text === false ? "no" : "yes"],
      ["suggestions", (f.suggestions || []).length
        ? (f.suggestions || []).map((s) => `${s.id} → ${JSON.stringify(s.action)}`).join("\n")
        : "-"],
    ])));

    const t = r.tokens || {};
    const total = (t.prompt || 0) + (t.completion || 0);
    // Cache reads bill at a fraction of fresh input, so the effective figure
    // is the one that tracks what a turn actually costs.
    const effective = (t.prompt || 0) - (t.cache_read || 0)
      + (t.cache_read || 0) * 0.1 + (t.completion || 0);
    body.append(group("Cost", kv([
      ["prompt tokens", show(t.prompt)],
      ["cache read", show(t.cache_read)],
      ["cache write", show(t.cache_write)],
      ["completion", show(t.completion)],
      ["total", total ? total.toLocaleString() : "-"],
      ["effective", total ? Math.round(effective).toLocaleString() : "-"],
      ["tool calls", show(r.tool_calls)],
      ["latency", r.latency_ms !== null ? `${Math.round(r.latency_ms)} ms` : "-"],
    ])));

    if ((r.state_mutations || []).length) {
      const ul = text("ul", "mutations");
      for (const m of r.state_mutations) ul.append(text("li", null, m));
      body.append(group("State mutations", ul));
    }

    details.append(body);
    return details;
  }

  /* What aliasing did: what the model was sent, how each value was aliased,
     and the SQL both ways -- as the model wrote it, and as it ran. */
  function piiGroup(r) {
    const p = r.pii;
    if (!p) return group("PII aliasing", kv([["status", "not reported", "v-none"]]));
    if (!p.enabled) return group("PII aliasing", kv([["status", "off (PII_ALIASING)", "v-none"]]));

    const aliases = p.aliases || [];
    const thisTurn = aliases.filter((a) => a.used || a.new);
    const nodes = [kv([
      ["status", "on", "v-ok"],
      ["detector", `${show(p.model)} at ${show(p.threshold)}, ${show(p.detect_ms)} ms`],
      ["sent to LLM", show(p.sent_to_llm)],
      ["tripwire", p.masked ? `${p.masked} known value(s) masked in a prompt` : "nothing caught",
       p.masked ? "v-bad" : "v-none"],
    ])];
    nodes.push(text("div", "sql-label", thisTurn.length
      ? "Aliased on this turn" : "Nothing personal found on this turn"));
    if (thisTurn.length) nodes.push(aliasTable(thisTurn));
    // Both versions of the SQL are above the table, under its Diff / LLM /
    // Executed switch; repeating them here would put three copies on screen.
    return group("PII aliasing", ...nodes);
  }

  const boolish = (v, absent = "-") =>
    v === null || v === undefined ? absent : v ? "yes" : "no";
  const tone = (v) => (v === null || v === undefined ? "v-none" : v ? "v-ok" : "v-bad");

  /* ------------------------------------------------------ setup panel */

  /* Which databases the chatbot reads and writes, its modes and its model.
     From GET /info; answers refresh the model and PII from the turn itself. */
  function renderSetup() {
    const info = session.info;
    if (!info) {
      el.setup.replaceChildren(text("p", "setup-warn",
        "The server did not answer /info. Is scripts/serve_api.py running?"));
      return;
    }
    const read = (info.databases || {}).read || {};
    const write = (info.databases || {}).write;
    const llm = info.llm || {};
    el.setup.replaceChildren(
      card("Read database", [
        ["name", show(read.name)],
        ["user", show(read.user)],
        ["metadata", show(info.metadata)],
      ]),
      card("Write database (chats)", write
        ? [["name", show(write.name)], ["user", show(write.user)],
           ["saving chats", onOff(write.saving)]]
        : [["status", "not set: chats are not saved"]]),
      card("Modes", [
        ["PII aliasing", onOff(info.pii ? info.pii.enabled : null)],
        ["streaming", onOff(info.stream)],
        ["debug", onOff(debugEnabled())],
      ]),
      card("Model", [
        ["model", show(llm.model, "CLI default")],
        ["provider", show(llm.provider)],
      ]),
      card("Tokens", tokenRows()),
    );
  }

  /* Token counts arrive only with debug answers: with debug off the server
     sends the conversation and nothing else. */
  function tokenRows() {
    const n = (value) => Number(value || 0).toLocaleString();
    const rows = [];
    if (session.last) {
      rows.push(["last answer: in", n(session.last.prompt)],
                ["of which cached", n(session.last.cache_read)],
                ["last answer: out", n(session.last.completion)]);
    }
    const t = session.tokens;
    if (t.answers) {
      rows.push(["this chat", `${n(t.prompt + t.completion)} (${t.answers} answers)`]);
    }
    if (session.usage) {
      const { used, limit } = session.usage;
      rows.push(["this month, all users", limit ? `${n(used)} of ${n(limit)}` : n(used)]);
    }
    if (!rows.length) {
      rows.push(["status", debugEnabled() ? "no answer yet" : "shown in debug mode"]);
    }
    return rows;
  }

  function countTokens(r) {
    const t = r.tokens || {};
    if (!t.prompt && !t.completion) return;
    session.last = t;
    session.tokens.answers += 1;
    session.tokens.prompt += t.prompt || 0;
    session.tokens.completion += t.completion || 0;
    if (r.token_usage) session.usage = r.token_usage;
  }

  function forgetTokens() {
    session.last = null;
    session.tokens = { answers: 0, prompt: 0, completion: 0 };
  }

  function card(title, rows) {
    const box = text("section", "setup-card");
    box.append(text("h3", null, title));
    for (const [label, value] of rows) {
      const row = text("div", "setup-row");
      row.append(text("span", "setup-label", label),
                 value instanceof Node ? value : text("span", "setup-value", value));
      box.append(row);
    }
    return box;
  }

  function onOff(on) {
    if (on === null || on === undefined) return text("span", "pill", "unknown");
    return text("span", `pill ${on ? "pill-on" : "pill-off"}`, on ? "ON" : "OFF");
  }

  /* ---------------------------------------------------------- sending */

  async function ask(question, action = null) {
    if (session.busy) return;
    const q = (question || "").trim();
    if (!q) return;

    setBusy(true);
    hideError();
    addUser(q);
    const placeholder = addThinking();

    const payload = {
      question: q,
      user_id: userId(),
      session_id: session.id,
      reset_context: session.resetPending,
      action,
      debug: debugEnabled(),
    };

    // The table as soon as the query has run, about a second before the
    // sentences around it are written. It is drawn with what the `rows` event
    // carries and nothing else -- no explanation, no chips, no grouping,
    // because none of that exists yet. The finished answer replaces it.
    // Declared out here so the catch below can clear it too.
    let early = null;

    try {
      // /ask/stream only when the server streams (STREAM_ANSWERS, from
      // /info); otherwise /ask, one plain JSON reply.
      const r = session.info?.stream
        ? await API.streamMessageToBackend(payload, {
            onRows(partial) {
              placeholder.remove();
              early = addResponse(partial);
            },
          })
        : await API.sendMessageToBackend(payload);
      if (early) early.remove();
      placeholder.remove();
      session.resetPending = false;
      session.turns += 1;
      countTokens(r);
      learnFrom(r);
      renderSetup();
      addResponse(r);
    } catch (err) {
      placeholder.remove();
      // A stream that failed after the table arrived would otherwise leave a
      // half-turn on screen, with rows above an error about the same turn.
      if (early) early.remove();
      addError(err.message || String(err));
      showError(`Request failed: ${err.message || err}`);
    } finally {
      setBusy(false);
      el.input.focus();
    }
  }

  function setBusy(busy) {
    session.busy = busy;
    el.send.disabled = busy;
    el.send.textContent = busy ? "Sending…" : "Send";
  }

  function showError(message) {
    el.errorBanner.textContent = message;
    el.errorBanner.hidden = false;
  }
  function hideError() { el.errorBanner.hidden = true; }

  function scroll() { el.messages.scrollTop = el.messages.scrollHeight; }

  /* ------------------------------------------------------------ wiring */

  el.composer.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = el.input.value;
    el.input.value = "";
    el.input.style.height = "auto";
    ask(q);
  });

  el.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      el.composer.requestSubmit();
    }
  });

  el.input.addEventListener("input", () => {
    el.input.style.height = "auto";
    el.input.style.height = `${Math.min(el.input.scrollHeight, 140)}px`;
  });

  el.resetContext.addEventListener("click", () => {
    session.resetPending = true;
    // A new session id is a new saved chat, with aliases of its own.
    session.id = `qa-${Date.now()}`;
    forgetTokens();
    renderSetup();
    const note = text("div", "msg msg-bot");
    note.append(text("div", "muted", "— context reset; the next question starts a new thread —"));
    el.messages.append(note);
    scroll();
  });

  el.clearChat.addEventListener("click", () => {
    el.messages.replaceChildren();
    session.resetPending = true;
    session.id = `qa-${Date.now()}`;
    session.turns = 0;
    forgetTokens();
    renderSetup();
    hideError();
  });

  /* The setup panel, shown or hidden; remembered across a refresh. */
  function paintSetupPanel(shown) {
    el.setupRail.hidden = !shown;
    document.querySelector(".layout").classList.toggle("no-rail", !shown);
    el.toggleSetup.textContent = shown ? "Hide setup" : "Show setup";
    el.toggleSetup.setAttribute("aria-expanded", String(shown));
  }

  el.toggleSetup.addEventListener("click", () => {
    const shown = el.setupRail.hidden;
    remember("wren.setup", shown);
    paintSetupPanel(shown);
  });

  async function loadInfo() {
    try {
      const res = await fetch(API.INFO_ENDPOINT);
      if (res.ok) session.info = await res.json();
    } catch {
      // No server to ask: the panel says so rather than guessing.
    }
    renderSetup();
  }

  // A debug answer carries the model and PII the turn actually used.
  function learnFrom(r) {
    if (!session.info || (!r.llm && !r.pii)) return;
    if (r.llm) session.info.llm = r.llm;
    if (r.pii) session.info.pii = { enabled: Boolean(r.pii.enabled), model: r.pii.model || null };
  }

  /* Debug detail for answers already on screen.
   *
   * The SQL for those never left the server -- that is the point of the
   * switch -- so it cannot be un-hidden in the page. It is still held per
   * conversation on the server, though, so turning debug on fetches it and
   * fills in the messages that are already there. Nothing is re-executed.
   */
  async function revealEarlierDebug() {
    let turns;
    try {
      const res = await fetch(API.DEBUG_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId(), session_id: session.id }),
      });
      if (!res.ok) return;
      turns = (await res.json()).turns || [];
    } catch {
      return;   // no history to offer, and that is not an error
    }

    for (const r of turns) {
      const msg = el.messages.querySelector(`[data-turn="${r.turn_index}"]`);
      if (!msg || msg.dataset.debugFilled) continue;
      msg.dataset.debugFilled = "1";

      if (r.generated_sql) {
        const sql = sqlViews(r);
        const rows = msg.querySelector(".rows");
        if (rows) msg.insertBefore(sql, rows);
        else msg.append(sql);
      }
      msg.append(debugPane(r));
    }
  }

  function hideEarlierDebug() {
    for (const msg of el.messages.querySelectorAll("[data-turn]")) {
      for (const node of msg.querySelectorAll(":scope > .sql, :scope > .sql-views, :scope > .debug")) {
        node.remove();
      }
      delete msg.dataset.debugFilled;
    }
  }

  if (el.debugMode) {
    el.debugMode.addEventListener("change", () => {
      remember("wren.debug", debugEnabled());
      paintDebug();
      renderSetup();
      hideError();
      if (debugEnabled()) revealEarlierDebug();
      else hideEarlierDebug();
    });
  }

  function paintDebug() {
    // Debug on is a QA console; debug off is a chatbot. The two want opposite
    // things from a stylesheet, so the whole chat theme hangs off this class.
    document.body.classList.toggle("chat-mode", !debugEnabled());
  }

  if (el.debugMode) el.debugMode.checked = remembered("wren.debug", false);
  paintDebug();
  paintSetupPanel(remembered("wren.setup", true));
  loadInfo();
  el.input.focus();
})();
