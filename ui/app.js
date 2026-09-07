/* The console itself: chat, per-turn debug, conversation state.
 *
 * Everything rendered here comes from one response object. The console keeps
 * no opinion of its own about what the state is -- it shows what the backend
 * last said it was, which is the only way a debugging view can be trusted.
 */

(() => {

  const $ = (id) => document.getElementById(id);

  const el = {
    messages: $("messages"),
    emptyHint: $("empty-hint"),
    composer: $("composer"),
    input: $("input"),
    send: $("send"),
    useMock: $("use-mock"),
    debugMode: $("debug-mode"),
    stateRail: $("state-rail"),
    sourceBadge: $("source-badge"),
    errorBanner: $("error-banner"),
    resetContext: $("reset-context"),
    clearChat: $("clear-chat"),
    stateFields: $("state-fields"),
    statePending: $("state-pending"),
    stateMutations: $("state-mutations"),
    totals: $("totals"),
  };

  const session = {
    id: `qa-${Date.now()}`,
    state: {},                  // last state the backend reported
    resetPending: false,        // send reset_context on the next request
    turns: 0,
    tokens: 0,
    llmCalls: 0,
    repairs: 0,
    busy: false,
  };

  // Debug is a request parameter, not a stylesheet. The server omits SQL,
  // schema names and diagnostics when this is off, so there is nothing in the
  // page to hide -- and nothing in the network tab either.
  function debugEnabled() {
    return Boolean(el.debugMode && el.debugMode.checked);
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

  function group(title, node) {
    const wrap = text("div", "debug-group");
    wrap.append(text("h4", null, title), node);
    return wrap;
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

    // ---- head ------------------------------------------------------------
    // Most of this is diagnostic and the server does not send it with debug
    // off, so the whole block is conditional rather than each field guarded.
    const followup = r.followup || { type: "none", suggestions: [] };
    const head = text("div", "head");

    if (debugEnabled()) {
      const mode = r.decision || (followup.type === "clarification" ? "clarification" : "answer");
      head.append(text("span", `mode mode-${mode}`, mode));

      if (r.preflight_clarified) head.append(text("span", "tag", "no model call"));
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
        msg.append(text("pre", "sql", r.generated_sql));
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

    const table = document.createElement("table");

    const thead = document.createElement("thead");
    const hrow = document.createElement("tr");
    for (const c of headers) hrow.append(text("th", null, c));
    thead.append(hrow);
    table.append(thead);

    const tbody = document.createElement("tbody");
    for (const row of rows.slice(0, 8)) {
      const tr = document.createElement("tr");
      for (const cell of row) tr.append(text("td", null, cell === null ? "NULL" : cell));
      tbody.append(tr);
    }
    table.append(tbody);
    wrap.append(table);
    return wrap;
  }

  /* --------------------------------------------------- per-turn debug */

  function debugPane(r) {
    const details = text("details", "debug");
    details.append(text("summary", null, "debug — this request"));
    const body = text("div", "debug-body");

    body.append(group("Understanding", kv([
      ["decision", show(r.decision)],
      ["original", show(r.question)],
      ["normalized", show(r.normalized_question)],
      ["repairs", r.repairs.length
        ? r.repairs.map((x) => `${x.original} → ${x.corrected} (${x.kind})`).join(", ")
        : "-"],
      ["resumed from", show(r.resumed_from)],
      ["preflight clarified", r.preflight_clarified ? "yes" : "no"],
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

    if (r.state_mutations.length) {
      const ul = text("ul", "mutations");
      for (const m of r.state_mutations) ul.append(text("li", null, m));
      body.append(group("State mutations", ul));
    }

    details.append(body);
    return details;
  }

  const boolish = (v, absent = "-") =>
    v === null || v === undefined ? absent : v ? "yes" : "no";
  const tone = (v) => (v === null || v === undefined ? "v-none" : v ? "v-ok" : "v-bad");

  /* ------------------------------------------------- conversation state */

  function renderState() {
    const s = session.state || {};
    el.stateFields = swap(el.stateFields, kv([
      ["entity", show(s.entity)],
      ["tables", show(s.tables)],
      ["filters", show(s.filters)],
      ["grouping", show(s.grouping)],
      ["sorting", show(s.sorting)],
      ["limit", show(s.limit)],
      ["intent", show(s.intent)],
      ["turns in block", show(s.turns_in_block)],
      ["previous sql", show(s.previous_sql)],
    ]));

    el.statePending.textContent = s.pending_question || "none";
    el.statePending.className = s.pending_question ? "pending" : "pending muted";

    el.totals = swap(el.totals, kv([
      ["turns", String(session.turns)],
      ["model calls", String(session.llmCalls)],
      ["calls avoided", String(session.turns - session.llmCalls)],
      ["repairs made", String(session.repairs)],
      ["total tokens", session.tokens.toLocaleString()],
    ]));
  }

  /* Replace a node and hand back the new one. The caller has to keep the
     returned reference: replaceWith leaves the old node detached, so a second
     render against the stale handle updates nothing anyone can see. */
  function swap(oldNode, newNode) {
    newNode.id = oldNode.id;
    oldNode.replaceWith(newNode);
    return newNode;
  }

  function renderMutations(list) {
    el.stateMutations.replaceChildren();
    if (!list || !list.length) {
      el.stateMutations.append(text("li", "muted", "none this turn"));
      return;
    }
    for (const m of list) el.stateMutations.append(text("li", null, m));
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
      session_id: session.id,
      reset_context: session.resetPending,
      action,
      debug: debugEnabled(),
      // Only the mock needs this; a real backend keeps its own session state.
      _state: session.state,
    };

    try {
      const r = await API.sendMessageToBackend(payload, { useMock: mockEnabled() });
      placeholder.remove();
      session.resetPending = false;
      session.turns += 1;
      session.repairs += r.repairs.length;
      session.tokens += (r.tokens.prompt || 0) + (r.tokens.completion || 0);
      // A preflight clarification is the one path that never reaches a model.
      // Counting on token figures instead would undercount any backend that
      // does not report usage.
      if (!r.preflight_clarified) session.llmCalls += 1;
      session.state = r.state || {};
      addResponse(r);
      renderState();
      renderMutations(r.state_mutations);
    } catch (err) {
      placeholder.remove();
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

  // Starter chips in the empty state.
  el.messages.addEventListener("click", (e) => {
    const starter = e.target.closest("[data-send]");
    if (starter) ask(starter.dataset.send);
  });

  el.resetContext.addEventListener("click", () => {
    session.state = {};
    session.resetPending = true;
    session.id = `qa-${Date.now()}`;
    renderState();
    renderMutations(["context reset — next turn starts clean"]);
    const note = text("div", "msg msg-bot");
    note.append(text("div", "muted", "— context reset; the next question starts a new thread —"));
    el.messages.append(note);
    scroll();
  });

  el.clearChat.addEventListener("click", () => {
    el.messages.replaceChildren();
    session.state = {};
    session.resetPending = true;
    session.id = `qa-${Date.now()}`;
    session.turns = session.tokens = session.llmCalls = session.repairs = 0;
    hideError();
    renderState();
    renderMutations(null);
  });

  // The mock is optional: production builds ship no mock.js and no toggle,
  // so every read of it goes through here rather than touching el.useMock.
  function mockEnabled() {
    return Boolean(window.MOCK && el.useMock && el.useMock.checked);
  }

  function paintSource() {
    const mock = mockEnabled();
    el.sourceBadge.textContent = mock ? "mock" : "live";
    el.sourceBadge.className = `badge ${mock ? "badge-mock" : "badge-live"}`;
    el.sourceBadge.title = mock ? "recorded fixtures" : API.ENDPOINT;
  }

  if (el.useMock) {
    el.useMock.addEventListener("change", () => {
      paintSource();
      hideError();
    });
  }

  if (el.debugMode) {
    el.debugMode.addEventListener("change", () => {
      // The rail reports tables and filters, which is database metadata, so
      // it is only populated at all when debug is on. Turns already on screen
      // keep whatever they were rendered with: the SQL for those never left
      // the server, so there is nothing to reveal without asking again.
      paintDebug();
      hideError();
    });
  }

  function paintDebug() {
    if (el.stateRail) el.stateRail.hidden = !debugEnabled();
  }

  paintDebug();

  // Served by scripts/serve_api.py rather than opened off disk? Then a real
  // backend is demonstrably there, and asking it is what you came for.
  if (location.protocol.startsWith("http") && el.useMock) el.useMock.checked = false;
  paintSource();

  renderState();
  el.input.focus();
})();
