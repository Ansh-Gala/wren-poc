/* Mock backend.
 *
 * Every fixture below is a real turn, lifted from
 * results/followup_v2/raw/turns.jsonl -- the SQL, the row counts, the
 * suggestion ids and the token figures are what the system actually produced,
 * not invented shapes. That matters for a console whose job is to show field
 * values: a mock with plausible-looking made-up fields would hide exactly the
 * mismatches this page exists to catch.
 *
 * Matching is by pattern rather than by script, so you can type the turns of a
 * thread in any order and still get a sensible answer while testing the UI.
 */

const MOCK = (() => {

  const LATENCY_MS = 450;   // enough to see the loading state

  const BO = "tms_business_object_flat";
  const TK = "tms_task_flat";

  const suggest = (id, label, action) => ({ id, label, action });

  const EXPLORE_BO = {
    follow_up_required: true,
    type: "exploration",
    reason: "useful_next_actions",
    question: "What would you like to explore next?",
    allow_free_text: true,
    suggestions: [
      suggest("filter_active_business_object", "Only the active ones",
        { type: "add_filter", field: "business_object_status", operator: "=", value: "Active" }),
      suggest("group_business_unit", "Group by business unit",
        { type: "add_group_by", field: "business_unit" }),
      suggest("sort_business_object_client_due_at", "Sort by business object client due at",
        { type: "set_sort", field: "business_object_client_due_at", operator: "DESC" }),
      suggest("aggregate_count", "Just count them",
        { type: "set_aggregate", field: "*", operator: "COUNT" }),
    ],
  };

  const EXPLORE_FILTERED = {
    follow_up_required: true,
    type: "exploration",
    reason: "useful_next_actions",
    question: "What would you like to explore next?",
    allow_free_text: true,
    suggestions: [
      suggest("group_business_unit", "Group by business unit",
        { type: "add_group_by", field: "business_unit" }),
      suggest("sort_business_object_client_due_at", "Sort by business object client due at",
        { type: "set_sort", field: "business_object_client_due_at", operator: "DESC" }),
      suggest("remove_business_object_status", "Remove the business object status filter",
        { type: "remove_filter", field: "business_object_status" }),
      suggest("aggregate_count", "Just count them",
        { type: "set_aggregate", field: "*", operator: "COUNT" }),
    ],
  };

  const BO_COLUMNS = ["business_object_id", "business_object_ref_id",
                      "business_unit", "business_object_status"];
  const BO_ROWS = [
    [112, "AR_DummyEve011_Suiting", "unit1", "Active"],
    [109, "AR_12312_Suiting_YD_Merch", "unit1", "Active"],
    [131, "AR_Suiting_YD_0031", "unit1", "Closed"],
  ];

  const tokens = (prompt, cacheRead, completion) => ({
    prompt, cache_read: cacheRead, cache_write: 0, completion,
  });

  /* Each fixture: when it applies, and what comes back. `state` is what the
     rail shows afterwards, so a thread reads correctly turn by turn. */
  const FIXTURES = [

    // -- a truncated name. Answered without any model call at all. ---------
    {
      test: (q) => /\bAR_YD\b/i.test(q) && !/AR_YD_/i.test(q),
      build: (q) => ({
        decision: "new_block",
        normalized_question: q,
        preflight_clarified: true,
        generated_sql: null,
        sql_valid: false,
        execution_success: false,
        clarification: "Which AR_YD type did you mean?",
        followup: {
          follow_up_required: true,
          type: "clarification",
          reason: "ambiguous_entity",
          question: "Which AR_YD type did you mean?",
          allow_free_text: true,
          suggestions: [
            suggest("set_entity_AR_YD_SHIRTING", "AR_YD_SHIRTING",
              { type: "set_entity", field: "business_object_type", operator: "=", value: "AR_YD_SHIRTING" }),
            suggest("set_entity_AR_YD_Shirting", "AR_YD_Shirting",
              { type: "set_entity", field: "business_object_type", operator: "=", value: "AR_YD_Shirting" }),
            suggest("set_entity_AR_YD_Suiting", "AR_YD_Suiting",
              { type: "set_entity", field: "business_object_type", operator: "=", value: "AR_YD_Suiting" }),
          ],
        },
        state: { pending_question: q, turns_in_block: 0 },
        state_mutations: ["awaiting a choice of business_object_type"],
        tokens: tokens(0, 0, 0),
        latency_ms: 0.33,
        tool_calls: 0,
        context_chars: 0,
      }),
    },

    // -- a measure the schema does not hold --------------------------------
    {
      test: (q) => /\b(revenue|profit|margin|cost|price|discount)\b/i.test(q),
      build: (q) => ({
        decision: "new_block",
        normalized_question: q,
        generated_sql: null,
        sql_valid: false,
        execution_success: false,
        clarification:
          "The schema has no revenue or cost column for business objects or " +
          "tasks, so there is no way to compute that figure.",
        followup: {
          follow_up_required: true,
          type: "clarification",
          reason: "ambiguous_request",
          question:
            "The schema has no revenue or cost column for business objects or " +
            "tasks, so there is no way to compute that figure.",
          suggestions: [],
          allow_free_text: true,
        },
        state: { pending_question: q },
        state_mutations: [],
        tokens: tokens(10857, 10855, 56),
        latency_ms: 6566,
        tool_calls: 0,
        context_chars: 0,
      }),
    },

    // -- a value the column does not take ----------------------------------
    {
      test: (q) => /\b(breached|pending|archived|purple)\b/i.test(q),
      build: (q) => ({
        decision: "new_block",
        normalized_question: q,
        generated_sql: null,
        sql_valid: false,
        execution_success: false,
        clarification:
          "task_sla_status only takes the values Delayed and On Time; there " +
          "is no Breached.",
        followup: {
          follow_up_required: true,
          type: "clarification",
          reason: "unknown_value",
          question:
            "task_sla_status only takes the values Delayed and On Time; there " +
            "is no Breached.",
          allow_free_text: true,
          suggestions: [
            suggest("filter_task_sla_status_Delayed", "Delayed",
              { type: "add_filter", field: "task_sla_status", operator: "=", value: "Delayed" }),
            suggest("filter_task_sla_status_On_Time", "On Time",
              { type: "add_filter", field: "task_sla_status", operator: "=", value: "On Time" }),
          ],
        },
        state: { tables: [TK], pending_question: q },
        state_mutations: [],
        tokens: tokens(10853, 10851, 61),
        latency_ms: 5210,
        tool_calls: 0,
        context_chars: 0,
      }),
    },

    // -- answering the clarification ---------------------------------------
    {
      test: (q) => /^\s*(AR_YD_Suiting|AR_YD_Shirting|AR_YD_SHIRTING|set_entity_\S+)\s*$/i.test(q),
      build: (q) => {
        const value = q.trim().replace(/^set_entity_/i, "");
        return {
          decision: "clarification_response",
          normalized_question: `Show the ${value} items`,
          resumed_from: q.trim(),
          generated_sql:
            `SELECT business_object_id, business_object_ref_id, business_unit, ` +
            `business_object_status\nFROM ${BO}\nWHERE business_object_type = '${value}'`,
          sql_valid: true,
          execution_success: true,
          result: { columns: BO_COLUMNS, rows: BO_ROWS, row_count: 22, truncated: true },
          semantic_match: true,
          projection_verdict: "superset",
          semantic_issues: ["projection includes extra column(s): ['business_object_status', 'business_unit']"],
          followup: EXPLORE_BO,
          state: {
            entity: value, tables: [BO],
            filters: { business_object_type: `business_object_type = '${value}'` },
            grouping: [], sorting: null, limit: null, intent: "list",
            previous_sql: `SELECT ... FROM ${BO} WHERE business_object_type = '${value}'`,
            turns_in_block: 1, pending_question: null,
          },
          state_mutations: [
            `resolved "${q.trim()}" into "Show the ${value} items"`,
            `+ filter business_object_type = '${value}'`,
          ],
          tokens: tokens(10852, 10850, 74),
          latency_ms: 5958,
          tool_calls: 0,
          context_chars: 0,
        };
      },
    },

    // -- a typo, repaired before anything else sees it ---------------------
    {
      test: (q) => /\b(itmes|tsaks|usres|colur|objets|actie|delyaed|clsoed|activ|staus|buisness)\b/i.test(q),
      build: (q) => {
        const FIXES = {
          itmes: "items", tsaks: "tasks", usres: "users", colur: "color",
          objets: "objects", actie: "active", delyaed: "delayed",
          clsoed: "closed", activ: "active", staus: "status",
          buisness: "business",
        };
        const repairs = [];
        const fixed = q.replace(/[A-Za-z]+/g, (w) => {
          const to = FIXES[w.toLowerCase()];
          if (!to) return w;
          repairs.push({ original: w, corrected: to, kind: "typo" });
          return to;
        });
        return {
          decision: "new_block",
          normalized_question: fixed,
          repairs,
          generated_sql:
            `SELECT business_object_id, business_object_ref_id, business_unit, ` +
            `business_object_status\nFROM ${BO}\nWHERE business_object_type = 'AR_YD_Suiting'`,
          sql_valid: true,
          execution_success: true,
          result: { columns: BO_COLUMNS, rows: BO_ROWS, row_count: 22, truncated: true },
          semantic_match: true,
          projection_verdict: "superset",
          semantic_issues: [],
          followup: EXPLORE_BO,
          state: {
            entity: "AR_YD_Suiting", tables: [BO],
            filters: { business_object_type: "business_object_type = 'AR_YD_Suiting'" },
            grouping: [], sorting: null, limit: null, intent: "list",
            previous_sql: `SELECT ... FROM ${BO} WHERE business_object_type = 'AR_YD_Suiting'`,
            turns_in_block: 1, pending_question: null,
          },
          state_mutations: repairs.map((r) => `repaired "${r.original}" -> "${r.corrected}"`),
          tokens: tokens(10851, 10849, 74),
          latency_ms: 7052,
          tool_calls: 0,
          context_chars: 0,
        };
      },
    },

    // -- narrowing the thread ----------------------------------------------
    {
      test: (q, s) => /^\s*(only|just)\b/i.test(q) && !!s.entity,
      build: (q, s) => {
        const black = /black|green|red|white/i.test(q);
        const field = black ? "business_object_color" : "business_object_status";
        const value = black
          ? q.match(/black|green|red|white/i)[0].replace(/^./, (c) => c.toUpperCase())
          : "Active";
        const filters = { ...(s.filters || {}), [field]: `${field} = '${value}'` };
        return {
          decision: "follow_up",
          normalized_question: q,
          generated_sql:
            `SELECT business_object_id, business_object_ref_id, business_unit, ` +
            `business_object_status\nFROM ${BO}\nWHERE ` +
            Object.values(filters).join("\n  AND "),
          sql_valid: true,
          execution_success: true,
          result: { columns: BO_COLUMNS, rows: BO_ROWS.slice(0, 2), row_count: black ? 12 : 19, truncated: true },
          semantic_match: true,
          projection_verdict: "superset",
          semantic_issues: [],
          followup: EXPLORE_FILTERED,
          state: { ...s, filters, intent: "list", turns_in_block: (s.turns_in_block || 0) + 1 },
          state_mutations: [`+ filter ${field} = '${value}'`],
          tokens: tokens(11072, 11070, 87),
          latency_ms: 6499,
          tool_calls: 0,
          context_chars: 526,
        };
      },
    },

    // -- counting what is on the table -------------------------------------
    {
      test: (q, s) => /^\s*how many\b|^\s*count\b/i.test(q) && !!s.entity,
      build: (q, s) => ({
        decision: "follow_up",
        normalized_question: q,
        generated_sql:
          `SELECT COUNT(*)\nFROM ${BO}\nWHERE ` +
          Object.values(s.filters || {}).join("\n  AND "),
        sql_valid: true,
        execution_success: true,
        result: { columns: ["count"], rows: [[19]], row_count: 1, truncated: false },
        semantic_match: true,
        projection_verdict: "exact",
        semantic_issues: [],
        followup: EXPLORE_FILTERED,
        state: { ...s, intent: "aggregate", turns_in_block: (s.turns_in_block || 0) + 1 },
        state_mutations: ["intent list -> aggregate"],
        tokens: tokens(11099, 11097, 41),
        latency_ms: 4820,
        tool_calls: 0,
        context_chars: 604,
      }),
    },

    // -- a new subject mid-thread ------------------------------------------
    {
      test: (q) => /\b(my (open|delayed) tasks|all users|list users)\b/i.test(q),
      build: (q) => ({
        decision: "new_block",
        normalized_question: q,
        generated_sql:
          `SELECT task_id, task_display_name\nFROM ${TK}\n` +
          `WHERE assigned_user_id = 1 AND task_status = 'open'`,
        sql_valid: true,
        execution_success: true,
        result: {
          columns: ["task_id", "task_display_name"],
          rows: [[921, "Data base sheet generation"], [944, "Sample approval"]],
          row_count: 17, truncated: true,
        },
        semantic_match: true,
        projection_verdict: "exact",
        semantic_issues: [],
        followup: {
          follow_up_required: true,
          type: "exploration",
          reason: "useful_next_actions",
          question: "What would you like to explore next?",
          allow_free_text: true,
          suggestions: [
            suggest("filter_delayed_task", "Only the delayed ones",
              { type: "add_filter", field: "task_sla_status", operator: "=", value: "Delayed" }),
            suggest("group_task_department", "Group by task department",
              { type: "add_group_by", field: "task_department" }),
            suggest("remove_task_status", "Remove the task status filter",
              { type: "remove_filter", field: "task_status" }),
          ],
        },
        state: {
          entity: null, tables: [TK],
          filters: {
            assigned_user_id: "assigned_user_id = 1",
            task_status: "task_status = 'open'",
          },
          grouping: [], sorting: null, limit: null, intent: "list",
          previous_sql: `SELECT ... FROM ${TK} WHERE assigned_user_id = 1 AND task_status = 'open'`,
          turns_in_block: 1, pending_question: null,
        },
        state_mutations: [
          "new block: previous subject and filters dropped",
          "+ filter assigned_user_id = 1",
          "+ filter task_status = 'open'",
        ],
        tokens: tokens(10921, 10919, 66),
        latency_ms: 6120,
        tool_calls: 0,
        context_chars: 0,
      }),
    },
  ];

  /* The default: a plain list for whatever type was named. */
  function fallback(q) {
    const named = (q.match(/AR_[A-Za-z_]+/) || [])[0] || "AR_YD_Suiting";
    return {
      decision: "new_block",
      normalized_question: q,
      generated_sql:
        `SELECT business_object_id, business_object_ref_id, business_unit, ` +
        `business_object_status\nFROM ${BO}\nWHERE business_object_type = '${named}'`,
      sql_valid: true,
      execution_success: true,
      result: { columns: BO_COLUMNS, rows: BO_ROWS, row_count: 22, truncated: true },
      semantic_match: true,
      projection_verdict: "superset",
      semantic_issues: ["projection includes extra column(s): ['business_object_status', 'business_unit']"],
      followup: EXPLORE_BO,
      state: {
        entity: named, tables: [BO],
        filters: { business_object_type: `business_object_type = '${named}'` },
        grouping: [], sorting: null, limit: null, intent: "list",
        previous_sql: `SELECT ... FROM ${BO} WHERE business_object_type = '${named}'`,
        turns_in_block: 1, pending_question: null,
      },
      state_mutations: [`+ filter business_object_type = '${named}'`],
      tokens: tokens(10851, 10849, 74),
      latency_ms: 6980,
      tool_calls: 0,
      context_chars: 0,
    };
  }

  async function respond(payload) {
    const question = (payload.question || "").trim();
    const state = payload.reset_context ? {} : (payload._state || {});

    await new Promise((r) => setTimeout(r, LATENCY_MS));

    // Deliberately reachable: type this to see the error state render.
    if (/^\s*fail\b/i.test(question)) {
      throw new Error("mock failure, so the error state can be tested");
    }

    const fixture = FIXTURES.find((f) => f.test(question, state));
    const body = fixture ? fixture.build(question, state) : fallback(question);
    return API.normalize({ question, ...body });
  }

  return { respond };
})();
