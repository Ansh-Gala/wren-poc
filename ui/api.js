/* ===========================================================================
   API INTEGRATION — this is the only file that talks to a backend.
   ===========================================================================

   Point ENDPOINT at your service, untick "use mock responses" in the header,
   and nothing else in this console needs to change.

   REQUEST the console sends:

     POST <ENDPOINT>
     {
       "question":       "only the active ones",   // exactly what was typed
       "user_id":        12,                       // the asking TMS user; required.
                                                   //   400 if missing or not a positive
                                                   //   whole number, 403 without a
                                                   //   CHATBOT_RUN_ROLES role
       "session_id":     "qa-1712...",             // stable per conversation
       "reset_context":  false,                    // true right after Reset
       "action":         null,                     // set when a chip was clicked:
                                                   //   {type, field, operator, value}
       "debug":          false                     // see below
     }

   DEBUG is off unless the console asks for it, and it is enforced server-side
   rather than in the page: with it off the response simply does not contain
   the SQL, the schema names or the diagnostics, so there is nothing to hide
   in the DOM and nothing to find in the network tab. Off, the response is
   exactly these five fields:

     question, clarification, error, followup, result

   with `result` reduced to {column_labels, rows, row_count, truncated} and
   each suggestion reduced to {label}. Everything documented below arrives
   only with "debug": true.

   RESPONSE the console renders. Every field is optional -- anything missing
   shows as "-" rather than breaking the page -- but the more you return, the
   more of the panel is useful.

     {
       // -------------------------------------------------- what it decided
       "decision":             "new_block | follow_up | switch | rebase |
                                clarification_response",
       "question":             "only the active ones",       // as typed
       "normalized_question":  "only the active ones",       // after repair
       "repairs":              [{original, corrected, kind}],
       "resumed_from":         null,   // set when this answered a clarification
       "preflight_clarified":  false,  // decided without calling the model

       // ------------------------------------------------------- the query
       "generated_sql":        "SELECT ...",   // null if it asked instead
       "sql_valid":            true,
       "execution_success":    true,
       "error":                null,           // safe to show; never the raw one
       "raw_error":            null,           // the database's own words (debug only)
       "failure_category":     "",             // e.g. SILENT_SUBSTITUTION

       "result": {
         "columns":       ["business_object_id", "..."],   // debug only
         // What the table actually renders. Derived from `columns` by
         // pipeline/labels.py, so the query and the heading never disagree.
         "column_labels": ["Initiative Id", "..."],
         "rows":          [[112, "..."], ...],     // a preview is fine
         "row_count":     22,
         "truncated":     false,

         // Presentation metadata, all of it positional so that none of it
         // names a column and all of it survives redaction. `columns` does
         // not, and debug off is the mode the grid runs in.
         "column_order":   [1, 0, 2],   // display order, as positions
         "hidden_columns": [2],         // start collapsed, still exported
         // Which cell identifies the initiative. `ref_id` is the cell that
         // opens the details dialog; `id` is what the dialog is given. Any
         // of the three may be null -- an aggregate has none of them.
         "initiative":     {"id": 0, "ref_id": 1, "colour": null},
         // Initiative id -> the CSS class the colour bar draws. Absent when
         // the answer has no initiative, or no colour could be resolved.
         "colours":        {"112": "a_bl"},
         // The grouping the table nominated, if any. Empty lists mean the
         // grid shows records, not groups.
         "grouping": {
           "row_groups":    [0],
           "pivot_columns": [],
           "value_columns": [{"index": 3, "aggFunc": "sum"}]
         }
       },

       // ------------------------------------- scoring, when ground truth exists
       // Omit entirely in production; the panel shows "n/a".
       "semantic_match":     true,
       "semantic_issues":    ["projection includes extra column(s): [...]"],
       "projection_verdict": "exact | superset | missing | substituted",
       "result_match":       true,

       // ------------------------------------------------- what to say next
       "clarification": null,       // prose, when the system is asking
       "followup": {
         "follow_up_required": true,
         "type":     "clarification | exploration | none",
         "reason":   "ambiguous_entity | unknown_value | ambiguous_request |
                      useful_next_actions",
         "question": "Which AR_YD type did you mean?",
         "suggestions": [
           { "id": "set_entity_AR_YD_Suiting",
             "label": "AR_YD_Suiting",
             "action": {"type": "set_entity", "field": "business_object_type",
                        "operator": "=", "value": "AR_YD_Suiting"} }
         ],
         "allow_free_text": true
       },

       // -------------------------------------------- conversation-level state
       // The right-hand rail. Send the whole thing each turn; the console does
       // not try to maintain its own copy.
       "state": {
         "entity":    "AR_YD_Suiting",
         "tables":    ["tms_business_object_flat"],
         "filters":   {"business_object_status": "business_object_status = 'Active'"},
         "grouping":  [],
         "sorting":   null,
         "limit":     null,
         "intent":    "list",
         "previous_sql":   "SELECT ...",
         "turns_in_block": 2,
         "pending_question": null      // what the system is waiting on
       },
       "state_mutations": ["+ filter business_object_status = 'Active'"],

       // ---------------------------------------------------------- cost
       "tokens": {
         "prompt": 11072, "cache_read": 11070, "cache_write": 0,
         "completion": 87
       },
       "latency_ms":   6498,
       "tool_calls":   0,
       "context_chars": 526
     }

   =========================================================================== */

const API = (() => {

  /* Served by scripts/serve_api.py? Then talk to whoever served this page --
     same origin, so there is no CORS to configure. Opened straight off disk,
     fall back to the default port. Override either by editing this line. */
  const ENDPOINT = location.protocol.startsWith("http")
    ? `${location.origin}/ask`
    : "http://localhost:8000/ask";

  // Debug detail for turns already answered. Same origin, same shape of
  // call; it reads what the server kept and executes nothing.
  const DEBUG_ENDPOINT = location.protocol.startsWith("http")
    ? `${location.origin}/debug`
    : "http://localhost:8000/debug";

  // The same turn, delivered in two parts. See streamMessageToBackend.
  const STREAM_ENDPOINT = ENDPOINT + "/stream";

  const TIMEOUT_MS = 120000;   // a cold model call can take a while

  // The server's own sentence when it sent one ("user_id is required"),
  // else the status line.
  async function refusal(res) {
    try {
      const body = await res.json();
      if (body && body.error) return body.error;
    } catch {}
    return `backend returned ${res.status} ${res.statusText}`;
  }

  /* THE INTEGRATION POINT. Everything above is documentation for this call. */
  async function sendMessageToBackend(payload, { useMock = true } = {}) {
    // window.MOCK is absent in a production build, which drops mock.js. Asking
    // the real backend is the right fallback; throwing would be a blank page.
    if (useMock && window.MOCK) return MOCK.respond(payload);

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const res = await fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (!res.ok) {
        throw new Error(await refusal(res));
      }
      return normalize(await res.json());
    } catch (err) {
      if (err.name === "AbortError") {
        throw new Error(`no response within ${TIMEOUT_MS / 1000}s`);
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  /* THE SAME CALL, IN TWO PARTS.

     The backend knows the SQL about a second before it has finished writing
     the sentences around it, so /ask/stream sends the table as soon as it has
     run the query and the rest when it is written:

       event: rows      what the query returned -- no explanation, no chips
       event: answer    exactly what POST /ask returns

     `onRows` may never fire: a turn that asks for clarification has no SQL.
     `onAnswer` always fires, and carries everything, so the page is correct
     whether or not the early table arrived.

     Falls back to the plain call when the browser cannot read a stream, or
     when the mock is on -- the mock has nothing to stream. */
  async function streamMessageToBackend(payload, { useMock = true, onRows } = {}) {
    if ((useMock && window.MOCK) || !window.ReadableStream || !window.TextDecoder) {
      return sendMessageToBackend(payload, { useMock });
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const res = await fetch(STREAM_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        throw new Error(await refusal(res));
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let answer = null;

      // An event ends at a blank line, and a chunk can split one anywhere --
      // including mid-character, which is why the decoder is told to stream.
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let cut;
        while ((cut = buffer.indexOf("\n\n")) !== -1) {
          const block = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);

          let name = null;
          let data = null;
          for (const line of block.split("\n")) {
            if (line.startsWith("event: ")) name = line.slice(7).trim();
            else if (line.startsWith("data: ")) {
              try { data = JSON.parse(line.slice(6)); } catch (e) { data = null; }
            }
          }
          if (!data) continue;
          if (name === "rows" && onRows) onRows(normalize(data));
          else if (name === "answer") answer = normalize(data);
          else if (name === "error") throw new Error(data.error || "turn failed");
        }
      }

      if (!answer) throw new Error("the stream ended without an answer");
      return answer;
    } catch (err) {
      if (err.name === "AbortError") {
        throw new Error(`no response within ${TIMEOUT_MS / 1000}s`);
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  /* Fill in what a response left out, so the renderer never has to guard.
     Deliberately non-destructive: a backend that returns more than this keeps
     whatever else it sent. */
  function normalize(raw) {
    const r = raw || {};
    return {
      decision: r.decision || "",
      question: r.question || "",
      normalized_question: r.normalized_question || r.question || "",
      repairs: r.repairs || [],
      resumed_from: r.resumed_from ?? null,
      preflight_clarified: !!r.preflight_clarified,

      generated_sql: r.generated_sql ?? null,
      sql_valid: r.sql_valid ?? null,
      execution_success: r.execution_success ?? null,
      error: r.error ?? null,
      failure_category: r.failure_category || "",

      result: r.result || {},

      semantic_match: r.semantic_match ?? null,
      semantic_issues: r.semantic_issues || [],
      projection_verdict: r.projection_verdict || "",
      result_match: r.result_match ?? null,

      clarification: r.clarification ?? null,
      followup: r.followup || { type: "none", suggestions: [] },

      state: r.state || {},
      state_mutations: r.state_mutations || [],

      tokens: r.tokens || {},
      latency_ms: r.latency_ms ?? null,
      tool_calls: r.tool_calls ?? null,
      context_chars: r.context_chars ?? null,
    };
  }

  return { sendMessageToBackend, streamMessageToBackend, normalize,
           ENDPOINT, STREAM_ENDPOINT, DEBUG_ENDPOINT };
})();
