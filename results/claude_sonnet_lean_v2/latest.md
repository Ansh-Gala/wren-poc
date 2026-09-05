# Wren + Claude Code text-to-SQL benchmark

Generated 2026-09-05T17:30:23+00:00  
Configuration(s): D  
Privacy mode(s): strict

```
========================================
WREN + CLAUDE BENCHMARK
========================================

Total questions:        65

SQL generated:          65 / 65
SQL executable:         65 / 65
Correct results:        65 / 65

SQL generation:         100.00%
Execution success:      100.00%
Result accuracy:        100.00%
```

## Accuracy by category

| Category | Questions | SQL | Ran | Correct | Accuracy | |
|---|---:|---:|---:|---:|---:|---|
| BO Aggregation | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| BO Filter | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| BU Aggregation | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Basic List | 3 | 3 | 3 | 3 | 100.0% | `########################` |
| Business Unit Filter | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Clarification | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Combined Filter | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| Combined Filter + Sort | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Count | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| Dynamic Attribute Aggregation | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Dynamic Attribute Filter | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| Dynamic Attribute Sort | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Filter + Limit | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Filter + Sort | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Golden Regression | 3 | 3 | 3 | 3 | 100.0% | `########################` |
| Limit | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| MY_TASK | 7 | 7 | 7 | 7 | 100.0% | `########################` |
| MY_TASK + Workflow | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| MY_TASK Aggregation | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| Natural Language Variation | 6 | 6 | 6 | 6 | 100.0% | `########################` |
| Sort | 3 | 3 | 3 | 3 | 100.0% | `########################` |
| Sort + Limit | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Task Aggregation | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| Task Count | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Task Filter | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| Task Filter + Limit | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Task List | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Task Status Aggregation | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| Unsupported | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| Unsupported / Clarification | 1 | 1 | 1 | 1 | 100.0% | `########################` |

## Reading these numbers

- Agentic runs are not deterministic. The same question can pass in one run and fail in the next, so a single run's score carries real run-to-run variance. Repeat a run before treating a difference of a few points as meaningful.
- Result accuracy compares returned rows, never SQL text. Column order and aliases are ignored; row order is enforced only where the question asked for it.
- No database rows were sent to Claude. Generated SQL is executed here, and the results in this report never re-entered the model.

