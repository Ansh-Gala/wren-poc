# Wren + Claude Code text-to-SQL benchmark

Generated 2026-09-05T12:23:32+00:00  
Configuration(s): D  
Privacy mode(s): strict

```
========================================
WREN + CLAUDE BENCHMARK
========================================

Total questions:        20

SQL generated:          13 / 20
SQL executable:         13 / 20
Correct results:        13 / 20

SQL generation:         65.00%
Execution success:      65.00%
Result accuracy:        65.00%
```

## Accuracy by category

| Category | Questions | SQL | Ran | Correct | Accuracy | |
|---|---:|---:|---:|---:|---:|---|
| A | 2 | 1 | 1 | 1 | 50.0% | `############............` |
| B | 1 | 0 | 0 | 0 | 0.0% | `........................` |
| C | 1 | 0 | 0 | 0 | 0.0% | `........................` |
| D | 1 | 0 | 0 | 0 | 0.0% | `........................` |
| E | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| F | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| G | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| H | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| I | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| J | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| K | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| L | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| M | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| N | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| O | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| P | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Q | 1 | 0 | 0 | 0 | 0.0% | `........................` |
| R | 1 | 0 | 0 | 0 | 0.0% | `........................` |
| S | 1 | 0 | 0 | 0 | 0.0% | `........................` |

## Failure categories

| Category | Count | Basis |
|---|---:|---|
| CLI_FAILURE | 7 | deterministic |

**Deterministic** categories are read from facts: a process that timed out, a tool that returned an error, a gate that refused the statement, or a SQLSTATE PostgreSQL itself returned.

**Heuristic** categories are inferred by diffing the generated SQL against the expected SQL. There are many correct ways to write a query, so a structural difference is not proof of the cause. Treat these as triage hints, not findings; `RESULT_MISMATCH` is the honest default when nothing else was confident.

## Wren MCP tools used

| Tool | Calls |
|---|---:|
| `mcp__wren__describe_model` | 25 |
| `mcp__wren__recall_queries` | 18 |
| `mcp__wren__list_models` | 18 |
| `mcp__wren__dry_plan` | 15 |
| `mcp__wren__get_instructions` | 7 |

## Failures

### A03 (A) - CLI_FAILURE

**Question:** Show the name and status of every task.

**Expected SQL**

```sql
SELECT name, status FROM tasks
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': "Request too large for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on output tokens per minute (OTPM): Limit 1000, Requested 1049. The request's expected output tokens exceed the enforced limit; reduce max`

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models

### B03 (B) - CLI_FAILURE

**Question:** Which tasks are currently blocked?

**Expected SQL**

```sql
SELECT name FROM tasks WHERE status = 'BLOCKED'
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': "Request too large for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on output tokens per minute (OTPM): Limit 1000, Requested 1049. The request's expected output tokens exceed the enforced limit; reduce max`

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

### C04 (C) - CLI_FAILURE

**Question:** List the workflows sorted by category, and within each category by name.

**Expected SQL**

```sql
SELECT category, name FROM workflows ORDER BY category, name
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': "Request too large for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on output tokens per minute (OTPM): Limit 1000, Requested 1049. The request's expected output tokens exceed the enforced limit; reduce max`

### D04 (D) - CLI_FAILURE

**Question:** Show the 5 unfinished tasks with the earliest deadlines.

**Expected SQL**

```sql
SELECT name, due_date FROM tasks
WHERE status <> 'COMPLETED'
ORDER BY due_date
LIMIT 5
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': "Request too large for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on output tokens per minute (OTPM): Limit 1000, Requested 1049. The request's expected output tokens exceed the enforced limit; reduce max`

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions

### Q01 (Q) - CLI_FAILURE

**Question:** Which active users have more than 2 unfinished tasks?

**Expected SQL**

```sql
SELECT u.full_name
FROM users u
JOIN tasks t ON t.assigned_user_id = u.id
WHERE u.status = 'ACTIVE' AND t.status <> 'COMPLETED'
GROUP BY u.id, u.full_name
HAVING COUNT(t.id) > 2
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 194803, Requested 5576. Please try again in 2m43.728s. Need more tokens? Upgrade to Dev Tier `

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model

### R04 (R) - CLI_FAILURE

**Question:** Which workflows are healthy, meaning they have no overdue and no blocked tasks?

**Expected SQL**

```sql
SELECT w.name
FROM workflows w
WHERE NOT EXISTS (
  SELECT 1 FROM tasks t
  WHERE t.workflow_id = w.id
    AND (t.status = 'BLOCKED'
         OR (t.due_date < CURRENT_DATE AND t.status <> 'COMPLETED'))
)
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199970, Requested 5679. Please try again in 40m40.368s. Need more tokens? Upgrade to Dev Tier`

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model

### S02 (S) - CLI_FAILURE

**Question:** How much work is still outstanding in each workflow?

**Expected SQL**

```sql
SELECT w.name, COUNT(t.id) AS outstanding
FROM workflows w
LEFT JOIN tasks t
       ON t.workflow_id = w.id AND t.status <> 'COMPLETED'
GROUP BY w.id, w.name
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199964, Requested 1509. Please try again in 10m36.336s. Need more tokens? Upgrade to Dev Tier`

## Reading these numbers

- Agentic runs are not deterministic. The same question can pass in one run and fail in the next, so a single run's score carries real run-to-run variance. Repeat a run before treating a difference of a few points as meaningful.
- Result accuracy compares returned rows, never SQL text. Column order and aliases are ignored; row order is enforced only where the question asked for it.
- No database rows were sent to Claude. Generated SQL is executed here, and the results in this report never re-entered the model.

