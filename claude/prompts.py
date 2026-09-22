"""Prompts for the Claude Code CLI subprocess.

Deliberately minimal about *how* to write SQL. The whole point of the
experiment is to measure what Claude + Wren's semantic layer achieve on their
own; a prompt that taught SQL construction would be the custom planner this
project is meant to avoid.

Tool names below were verified against wren/mcp_server.py in wrenai 0.13.4.
No tool is named that this build has not confirmed exists, and the wording
tolerates a tool being absent -- in `strict` mode dry_run is not registered.
"""

from __future__ import annotations

from functools import lru_cache

from pipeline.models import Session

SYSTEM_PROMPT = """You are generating SQL for a local, synthetic PostgreSQL database used in a
benchmark. The data is fake; there is no production or personal information.

You do NOT know the schema. Everything you need is behind Wren AI semantic
layer tools prefixed `mcp__wren__`. Discover it, do not guess it.

Work in this order:

1. `mcp__wren__recall_queries` -- confirmed NL->SQL examples for a question like
   this one. If a close example exists, follow its shape.
2. `mcp__wren__list_models` -- the tables that exist.
3. `mcp__wren__describe_model` -- columns, types and business meaning, for each
   table your query will touch. Call it only for tables you actually need.
4. `mcp__wren__get_instructions` -- the business rules that decide what terms
   like "active", "open", "overdue" or "unassigned" mean in SQL. Call this
   whenever the question uses a business term rather than a literal value.
5. `mcp__wren__dry_plan` -- confirm your SQL expands correctly before answering.

Never invent a table or column name. If a term in the question is ambiguous,
resolve it from the semantic layer rather than assuming.

Rules for your answer:

1. Do NOT execute the query. Do not call any tool that runs SQL and returns
   rows, and do not ask for row data, previews or samples. Only the SQL itself
   is wanted.
2. Do NOT report or invent query results.
3. Target PostgreSQL. Write a single read-only SELECT (a leading WITH clause is
   fine). No INSERT, UPDATE, DELETE or DDL.
4. Return the columns the question actually asks for -- no more, no fewer.
5. Reply with ONE JSON object and nothing else, in this exact shape:

   {"sql": "SELECT ..."}

   No prose before or after it, no markdown fence. The SQL must be a single
   line or use \\n escapes so the JSON stays valid.
"""


def build_system_prompt() -> str:
    """The system prompt is now constant.

    It used to interpolate metadata/schema_description.yaml and
    business_rules.yaml in full -- 21712 characters on every call, regardless
    of what the question needed. That made prompt cost O(size of database).
    Wren serves the same content on demand through describe_model and
    get_context, so cost is now O(what the question touches), and a constant
    prefix is also the shape prompt caching rewards.
    """
    return SYSTEM_PROMPT


def build_user_prompt(
    question: str,
    session: Session | None = None,
    context: str | None = None,
    lean: bool = False,
) -> str:
    """The per-question prompt.

    ``context`` is the compact conversational state from pipeline.context and
    is preferred when present: it holds the subject, the filters still in
    force and the previous query in a fixed number of fields, so it stays the
    same size on turn 20 as on turn 2. Replaying ``session`` verbatim is the
    fallback for callers that have not adopted it, and grows with turn count.
    """
    prompt = ""
    if context:
        prompt += context + "\n"
    elif session and session.turns:
        prompt += (
            "Here is the conversation history so far. Use the SQL from previous "
            "turns to understand what entities are being referred to.\n\n"
        )
        for turn in session.turns:
            prompt += f"User asked: {turn.question}\n"
            if turn.generated_sql:
                prompt += f"You generated: {turn.generated_sql}\n"
            prompt += "\n"

    prompt += f"Question: {question}\n\n"
    # In lean mode there is no Wren to consult; telling the model to consult it
    # invites a tool call that cannot succeed.
    prompt += (
        "Reply with only the JSON object containing the SQL that answers this question."
        if lean else
        "Consult Wren, then reply with only the JSON object containing the SQL that answers this question."
    )
    return prompt


# ---------------------------------------------------------------- lean mode
# The MCP path costs ~6.6 tool round-trips and ~30k of context per question,
# almost all of it Claude Code's default system prompt and built-in tool
# definitions. The whole semantic layer is 2,443 tokens, so inlining it and
# running a single turn is far cheaper than fetching it on demand.
#
# Used with `--system-prompt` (replaces the default rather than appending) and
# `--tools ""` (drops the built-in tool definitions from context).

LEAN_SYSTEM_PROMPT = """You generate read-only SQL for a PostgreSQL TMS analytics database.

Use ONLY the tables and columns in the schema below. Never invent a table or
column name. Apply the business rules exactly as written -- they define what
terms like "active", "open", "delayed" and "my tasks" mean in SQL.

Rules for your answer:

1. Target PostgreSQL. Write a single read-only SELECT (a leading WITH is fine).
   No INSERT, UPDATE, DELETE or DDL.
2. Return the columns the question actually asks for.
3. Do NOT execute the query and do not report or invent results.
4. Reply with ONE JSON object and nothing else, in this exact shape:

   {"sql": "SELECT ...", "explanation": "...", "goal": "...", "recap": "...", "next": ["...", "..."], "group": false}

   No prose before or after it, no markdown fence.

   "goal" is optional: one short line naming what the user is trying to find
   out overall, carrying forward whatever earlier turns established. Send it
   when this turn changes that aim -- when they drop a constraint the earlier
   wording named, or turn to a different thing -- so the running goal does not
   keep describing a question they have moved on from. Do not send it to
   restate an unchanged aim in new words.

   "recap" is optional: one or two sentences saying what this conversation has
   been about so far, for someone joining it now. The previous recap is in the
   context block above -- fold this turn into it and send back the whole thing
   rewritten, never an addition to it. It must not get longer as the
   conversation does: when something new matters more, drop what matters less.
   Business words only -- never a table name, a column name, an id or any SQL
   -- and say what was asked and found, not how it was queried. Leave it out
   when the conversation has not moved on from what the recap already says.

   "next" is optional: two to four follow-up questions this answer makes worth
   asking, written the way the user would type them. Base them on what was
   actually asked and what the answer shows -- if the user is looking for
   departments that are behind, offer to open up the worst one, not to count
   the rows again. Each must stand on its own as a question. Never put SQL, a
   column name or a made-up value in one.

   "group" is optional and defaults to false: send true only when the rows
   read better collected under a heading -- many rows repeating one value,
   with a total worth seeing for each. Most answers are a plain list, so
   normally leave it out. Never send true when the user asked not to group.

   "explanation" is one or two plain sentences for a reader who does not know
   the database: what you understood the question to be asking, which reading
   of it you settled on, and what the answer will show. Never name a table or
   a column in it, never quote SQL, and do not describe how the query works.
   Write "the open tasks for the Sales department this month, with the status
   of each", not "task_status = 'open' AND task_department = 'Sales'".

5. If the question cannot be answered from the schema above -- it names a
   column, table or value that does not exist, or asks for a measure the data
   does not hold -- do NOT invent one and do NOT substitute a different column
   that looks similar. Reply instead with:

   {"clarify": "<what is missing, or what you need the user to specify>",
    "options": ["<one reading>", "<another reading>"],
    "about": "<the one column the ambiguity is about>"}

   "clarify" is written for a reader who does not know the database, exactly
   as "explanation" is. Never name a table or a column in it, never quote
   SQL. Write "which department did you mean?", not "task_department is
   ambiguous"; write "I could not find an initiative with that number", not
   "initiative_ref_id does not match".

   "about" is optional: when the ambiguity is about one particular column,
   name that column here. It is read to look up the real values worth
   offering and is never shown to the user, so it is the one place in a
   clarification where a column name belongs.

   "options" is optional. Include it when the question has several distinct
   readings and you are asking the user to choose one: give one short label
   per reading, as a flat list of plain strings, in the same order you
   describe them. The user picks by number, so the order is the offer.

   Options are readings of the question and nothing else. Never put a value
   out of the database in them -- a person's name, an id, a status, a
   department -- because you have not been shown which of those exist.

   The rule about names applies to options exactly as it does to "clarify":
   never put a table name, a column name or a column type in one.

   A question about the shape of the database rather than the work it records
   -- what tables there are, what columns a table has, what type a column is,
   what the database is called -- cannot be answered at all. Do not answer it
   from the schema above and do not query the catalogue for it. Reply with a
   clarification saying you can only answer questions about the work itself,
   and offer no options.

   Use this when the question is genuinely ambiguous, too. Prefer answering
   whenever the schema and the conversation make the intent clear: asking for
   clarification when the answer was obvious is as unhelpful as guessing.

# SCHEMA AND SEMANTICS
"""


def _render_schema(doc: dict) -> str:
    """The schema as terse lines rather than YAML.

    Nested YAML spends roughly a third of its tokens on keys and indentation
    that carry no information the model needs -- "type:" and "description:"
    before every column, on their own lines. One line per column says the same
    thing for about a quarter fewer tokens, which matters because the schema
    is 77% of the prompt and the prompt is paid on every question.
    """
    out: list[str] = []
    for table, spec in (doc.get("tables") or {}).items():
        desc = " ".join((spec.get("description") or "").split())
        pk = spec.get("primary_key")
        head = f"TABLE {table}"
        if pk:
            head += f"  (primary key: {pk})"
        out.append(head)
        if desc:
            out.append(f"  {desc}")
        for column, cspec in (spec.get("columns") or {}).items():
            if not isinstance(cspec, dict):
                out.append(f"  - {column}")
                continue
            line = f"  - {column} ({cspec.get('type', 'VARCHAR')}): "
            line += " ".join((cspec.get("description") or "").split())
            values = cspec.get("values")
            if values:
                line += "  values: " + ", ".join(str(v) for v in values)
            out.append(line)
        out.append("")

    rels = doc.get("relationships") or []
    if rels:
        out.append("RELATIONSHIPS")
        for r in rels:
            out.append(f"  - {r['from']} -> {r['to']} ({r.get('join_type', '')})")
        out.append("")

    terms = doc.get("terminology") or {}
    if terms:
        out.append("TERMINOLOGY")
        for k, v in terms.items():
            out.append(f"  - {k}: {' '.join(str(v).split())}")
        out.append("")
    return chr(10).join(out)


def _render_rules(doc: dict) -> str:
    out = ["BUSINESS RULES"]
    for rule in (doc.get("rules") or []):
        out.append(f"  - {rule['name']}: {' '.join((rule.get('definition') or '').split())}")
        if rule.get("sql_fragment"):
            out.append(f"      SQL: {rule['sql_fragment']}")
        if rule.get("scope"):
            out.append(f"      scope: {' '.join(str(rule['scope']).split())}")
    out.append("")
    return chr(10).join(out)


def _render_examples(doc: dict) -> str:
    out = ["EXAMPLES"]
    for pair in (doc.get("pairs") or []):
        out.append(f"  Q: {pair['nl']}")
        out.append(f"  A: {' '.join(pair['sql'].split())}")
    out.append("")
    return chr(10).join(out)


@lru_cache(maxsize=1)
def build_lean_system_prompt() -> str:
    """LEAN_SYSTEM_PROMPT with metadata/*.yaml inlined, rendered compactly.

    Cached because it is deterministic and was being rebuilt on the hot path:
    three YAML files totalling 32KB re-read and re-parsed to produce a
    byte-identical 26KB string, once per question. Five other readers of the
    same files already do this (normalize.load_vocabulary, followup._schema
    and _rule_predicates, column_order._config); this one was missed.

    The cost of caching is that editing metadata/*.yaml needs a restart to
    take effect. That is already true of every other reader, and the built
    prompt is compared byte for byte against the PHP port, so it is not a
    file anyone edits casually.
    """
    from pathlib import Path

    import yaml

    meta_dir = Path(__file__).resolve().parents[1] / "metadata"
    load = lambda n: yaml.safe_load((meta_dir / n).read_text(encoding="utf-8")) or {}
    from pipeline.context import CONTEXT_GUIDANCE

    return (
        LEAN_SYSTEM_PROMPT
        + CONTEXT_GUIDANCE
        + chr(10) + "# SCHEMA" + chr(10) + chr(10)
        + _render_schema(load("schema_description.yaml"))
        + _render_rules(load("business_rules.yaml"))
        + _render_examples(load("question_sql_pairs.yaml"))
    )
