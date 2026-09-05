# Wren + Claude Code text-to-SQL benchmark

Generated 2026-09-05T12:11:06+00:00  
Configuration(s): D  
Privacy mode(s): strict

```
========================================
WREN + CLAUDE BENCHMARK
========================================

Total questions:        20

SQL generated:          20 / 20
SQL executable:         20 / 20
Correct results:        19 / 20

SQL generation:         100.00%
Execution success:      100.00%
Result accuracy:        95.00%
```

## Accuracy by category

| Category | Questions | SQL | Ran | Correct | Accuracy | |
|---|---:|---:|---:|---:|---:|---|
| A | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| B | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| C | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| D | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| E | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| F | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| G | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| H | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| I | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| J | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| K | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| L | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| M | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| N | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| O | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| P | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Q | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| R | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| S | 1 | 1 | 1 | 1 | 100.0% | `########################` |

## Failure categories

| Category | Count | Basis |
|---|---:|---|
| WRONG_DATE_LOGIC | 1 | heuristic |

**Deterministic** categories are read from facts: a process that timed out, a tool that returned an error, a gate that refused the statement, or a SQLSTATE PostgreSQL itself returned.

**Heuristic** categories are inferred by diffing the generated SQL against the expected SQL. There are many correct ways to write a query, so a structural difference is not proof of the cause. Treat these as triage hints, not findings; `RESULT_MISMATCH` is the honest default when nothing else was confident.

## Wren MCP tools used

| Tool | Calls |
|---|---:|
| `mcp__wren__dry_plan` | 22 |
| `mcp__wren__recall_queries` | 20 |
| `mcp__wren__list_models` | 20 |
| `mcp__wren__describe_model` | 11 |
| `mcp__wren__get_instructions` | 10 |

## Failures

### L05 (L) - WRONG_DATE_LOGIC

**Question:** Which unfinished tasks are due within the next 7 days, including today?

**Expected SQL**

```sql
SELECT name FROM tasks
WHERE status <> 'COMPLETED'
  AND due_date >= CURRENT_DATE
  AND due_date <= CURRENT_DATE + INTERVAL '7 days'
```

**Generated SQL**

```sql
SELECT id, name, status, priority, due_date, assigned_user_id
FROM tasks
WHERE status <> 'COMPLETED'
  AND due_date >= CURRENT_DATE
  AND due_date < CURRENT_DATE + INTERVAL '7 days'
ORDER BY due_date
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

## Reading these numbers

- Agentic runs are not deterministic. The same question can pass in one run and fail in the next, so a single run's score carries real run-to-run variance. Repeat a run before treating a difference of a few points as meaningful.
- Result accuracy compares returned rows, never SQL text. Column order and aliases are ignored; row order is enforced only where the question asked for it.
- No database rows were sent to Claude. Generated SQL is executed here, and the results in this report never re-entered the model.

