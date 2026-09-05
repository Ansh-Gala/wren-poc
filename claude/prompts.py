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

from benchmark.models import Session

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


def build_user_prompt(question: str, session: Session | None = None) -> str:
    prompt = ""
    if session and session.turns:
        prompt += "Here is the conversation history so far. Use the SQL from previous turns to understand what entities are being referred to. If you are asked to filter the previous result, nest the previous SQL query into your new query instead of asking for row data.\n\n"
        for turn in session.turns:
            prompt += f"User asked: {turn.question}\n"
            if turn.generated_sql:
                prompt += f"You generated: {turn.generated_sql}\n"
            prompt += "\n"
            
    prompt += f"Question: {question}\n\n"
    prompt += "Consult Wren, then reply with only the JSON object containing the SQL that answers this question."
    return prompt
