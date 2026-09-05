# Wren + Claude Code text-to-SQL benchmark

Generated 2026-09-05T12:05:34+00:00  
Configuration(s): D  
Privacy mode(s): strict

```
========================================
WREN + CLAUDE BENCHMARK
========================================

Total questions:        1

SQL generated:          1 / 1
SQL executable:         1 / 1
Correct results:        1 / 1

SQL generation:         100.00%
Execution success:      100.00%
Result accuracy:        100.00%
```

## Accuracy by category

| Category | Questions | SQL | Ran | Correct | Accuracy | |
|---|---:|---:|---:|---:|---:|---|
| L | 1 | 1 | 1 | 1 | 100.0% | `########################` |

## Wren MCP tools used

| Tool | Calls |
|---|---:|
| `mcp__wren__recall_queries` | 1 |
| `mcp__wren__list_models` | 1 |
| `mcp__wren__get_instructions` | 1 |
| `mcp__wren__describe_model` | 1 |
| `mcp__wren__dry_plan` | 1 |

## Reading these numbers

- Agentic runs are not deterministic. The same question can pass in one run and fail in the next, so a single run's score carries real run-to-run variance. Repeat a run before treating a difference of a few points as meaningful.
- Result accuracy compares returned rows, never SQL text. Column order and aliases are ignored; row order is enforced only where the question asked for it.
- No database rows were sent to Claude. Generated SQL is executed here, and the results in this report never re-entered the model.

