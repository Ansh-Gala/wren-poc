/* ===========================================================================
   API INTEGRATION — this is the only file that talks to a backend.
   ===========================================================================

   Point ENDPOINT at your service, untick "use mock responses" in the header,
   and nothing else in this console needs to change.

   REQUEST the console sends:

     POST <ENDPOINT>
     {
       "question":       "only the active ones",   // exactly what was typed
       "session_id":     "qa-1712...",             // stable per conversation
       "reset_context":  false,                    // true right after Reset
       "action":         null                      // set when a chip was clicked:
                                                   //   {type, field, operator, value}
     }

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
       "error":                null,
       "failure_category":     "",             // e.g. SILENT_SUBSTITUTION

       "result": {
         "columns":   ["business_object_id", "..."],
         "rows":      [[112, "..."], ...],     // a preview is fine
         "row_count": 22,
         "truncated": false
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

  const ENDPOINT = "http://localhost:8000/ask";   // <-- your backend
  const TIMEOUT_MS = 60000;

  /* THE INTEGRATION POINT. Everything above is documentation for this call. */
  async function sendMessageToBackend(payload, { useMock = true } = {}) {
    if (useMock) return MOCK.respond(payload);

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
        throw new Error(`backend returned ${res.status} ${res.statusText}`);
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

  return { sendMessageToBackend, normalize, ENDPOINT };
})();
