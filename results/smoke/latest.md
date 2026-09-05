# Wren + Claude Code text-to-SQL benchmark

Generated 2026-09-04T07:04:23+00:00  
Configuration(s): D  
Privacy mode(s): strict

```
========================================
WREN + CLAUDE BENCHMARK
========================================

Total questions:        19

SQL generated:          19 / 19
SQL executable:         19 / 19
Correct results:        6 / 19

SQL generation:         100.00%
Execution success:      100.00%
Result accuracy:        31.58%
```

## Accuracy by category

| Category | Questions | SQL | Ran | Correct | Accuracy | |
|---|---:|---:|---:|---:|---:|---|
| A | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| B | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| C | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| D | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| E | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| F | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| G | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| H | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| I | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| J | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| K | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| L | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| M | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| N | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| O | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| P | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| Q | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| R | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| S | 1 | 1 | 1 | 0 | 0.0% | `........................` |

## Failure categories

| Category | Count | Basis |
|---|---:|---|
| RESULT_MISMATCH | 5 | heuristic |
| SEMANTIC_MISUNDERSTANDING | 3 | heuristic |
| WRONG_DATE_LOGIC | 3 | heuristic |
| WRONG_JOIN | 1 | heuristic |
| WRONG_GROUPING | 1 | deterministic |

**Deterministic** categories are read from facts: a process that timed out, a tool that returned an error, a gate that refused the statement, or a SQLSTATE PostgreSQL itself returned.

**Heuristic** categories are inferred by diffing the generated SQL against the expected SQL. There are many correct ways to write a query, so a structural difference is not proof of the cause. Treat these as triage hints, not findings; `RESULT_MISMATCH` is the honest default when nothing else was confident.

## Wren MCP tools used

| Tool | Calls |
|---|---:|
| `mcp__wren__describe_model` | 27 |
| `mcp__wren__dry_plan` | 19 |
| `mcp__wren__list_models` | 18 |
| `mcp__wren__get_instructions` | 14 |
| `mcp__wren__recall_queries` | 7 |
| `mcp__wren__get_context` | 1 |

## Failures

### B03 (B) - RESULT_MISMATCH

**Question:** Which tasks are currently blocked?

**Expected SQL**

```sql
SELECT name FROM tasks WHERE status = 'BLOCKED'
```

**Generated SQL**

```sql
SELECT id, name, workflow_id, assigned_user_id, due_date FROM tasks WHERE status = 'BLOCKED'
```

**Wren tools called:** mcp__wren__get_instructions, mcp__wren__list_models, mcp__wren__describe_model, mcp__wren__dry_plan

### D04 (D) - RESULT_MISMATCH

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
SELECT id, name, status, priority, due_date FROM tasks WHERE status <> 'COMPLETED' ORDER BY due_date ASC NULLS LAST LIMIT 5
```

**Wren tools called:** mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__recall_queries, mcp__wren__describe_model, mcp__wren__dry_plan

### G03 (G) - RESULT_MISMATCH

**Question:** Which departments have more than 2 users?

**Expected SQL**

```sql
SELECT department FROM users
GROUP BY department
HAVING COUNT(*) > 2
```

**Generated SQL**

```sql
SELECT department, COUNT(*) AS user_count FROM users GROUP BY department HAVING COUNT(*) > 2
```

**Wren tools called:** mcp__wren__get_context, mcp__wren__list_models, mcp__wren__dry_plan

### J02 (J) - SEMANTIC_MISUNDERSTANDING

**Question:** List every user together with how many workflows they own, including those who own none.

**Expected SQL**

```sql
SELECT u.full_name, COUNT(w.id) AS workflow_count
FROM users u
LEFT JOIN workflows w ON w.owner_user_id = u.id
GROUP BY u.id, u.full_name
```

**Generated SQL**

```sql
SELECT users.id, users.full_name, COUNT(workflows.id) AS workflow_count FROM users LEFT JOIN workflows ON workflows.owner_user_id = users.id GROUP BY users.id, users.full_name ORDER BY users.id
```

**Wren tools called:** mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

### K01 (K) - RESULT_MISMATCH

**Question:** Which tasks have no completion date recorded?

**Expected SQL**

```sql
SELECT name FROM tasks WHERE completed_at IS NULL
```

**Generated SQL**

```sql
SELECT id, name FROM tasks WHERE completed_at IS NULL
```

**Wren tools called:** mcp__wren__describe_model, mcp__wren__get_instructions, mcp__wren__list_models, mcp__wren__dry_plan

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
SELECT id, name, status, priority, due_date FROM tasks WHERE status <> 'COMPLETED' AND due_date >= CURRENT_DATE AND due_date < CURRENT_DATE + INTERVAL '7 days' ORDER BY due_date
```

**Wren tools called:** mcp__wren__get_instructions, mcp__wren__list_models, mcp__wren__describe_model, mcp__wren__dry_plan

### M01 (M) - WRONG_DATE_LOGIC

**Question:** Label each unfinished task as 'Overdue' if its due date has passed and 'On time' otherwise.

**Expected SQL**

```sql
SELECT name,
       CASE WHEN due_date < CURRENT_DATE THEN 'Overdue' ELSE 'On time' END AS label
FROM tasks
WHERE status <> 'COMPLETED'
```

**Generated SQL**

```sql
SELECT tasks.id, tasks.name, tasks.due_date, CASE WHEN tasks.due_date < CURRENT_DATE THEN 'Overdue' ELSE 'On time' END AS status_label FROM tasks WHERE tasks.status <> 'COMPLETED'
```

**Wren tools called:** mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

### N05 (N) - WRONG_JOIN

**Question:** Which users are assigned at least one critical task?

**Expected SQL**

```sql
SELECT DISTINCT u.full_name
FROM users u
WHERE EXISTS (
  SELECT 1 FROM tasks t
  WHERE t.assigned_user_id = u.id AND t.priority = 'CRITICAL'
)
```

**Generated SQL**

```sql
SELECT DISTINCT users.id, users.full_name FROM users JOIN tasks ON tasks.assigned_user_id = users.id WHERE tasks.priority = 'CRITICAL'
```

**Wren tools called:** mcp__wren__get_instructions, mcp__wren__list_models, mcp__wren__recall_queries, mcp__wren__describe_model, mcp__wren__dry_plan

### O02 (O) - WRONG_GROUPING

**Question:** Work out how many unfinished tasks each user has, then list the users with more than 2 of them.

**Expected SQL**

```sql
WITH open_counts AS (
  SELECT assigned_user_id, COUNT(*) AS open_tasks
  FROM tasks
  WHERE status <> 'COMPLETED' AND assigned_user_id IS NOT NULL
  GROUP BY assigned_user_id
)
SELECT u.full_name, oc.open_tasks
FROM open_counts oc
JOIN users u ON u.id = oc.assigned_user_id
WHERE oc.open_tasks > 2
```

**Generated SQL**

```sql
SELECT u.id, u.full_name, COUNT(t.id) AS unfinished_task_count
FROM users u
JOIN tasks t ON t.assigned_user_id = u.id
WHERE t.status <> 'COMPLETED'
GROUP BY u.id, u.full_name
HAVING COUNT(t.id) > 2
ORDER BY unfinished_task_count DESC
```

**Wren tools called:** mcp__wren__get_instructions, mcp__wren__list_models, mcp__wren__describe_model, mcp__wren__dry_plan

### P03 (P) - RESULT_MISMATCH

**Question:** Show each task alongside the total number of tasks belonging to the same workflow.

**Expected SQL**

```sql
SELECT name,
       COUNT(*) OVER (PARTITION BY workflow_id) AS workflow_task_count
FROM tasks
```

**Generated SQL**

```sql
SELECT t.id, t.name, t.workflow_id, COUNT(*) OVER (PARTITION BY t.workflow_id) AS workflow_task_count FROM tasks t
```

**Wren tools called:** mcp__wren__describe_model, mcp__wren__recall_queries, mcp__wren__dry_plan

### Q01 (Q) - SEMANTIC_MISUNDERSTANDING

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
SELECT u.full_name, COUNT(t.id) AS unfinished_task_count FROM users u JOIN tasks t ON t.assigned_user_id = u.id WHERE u.status = 'ACTIVE' AND t.status <> 'COMPLETED' GROUP BY u.id, u.full_name HAVING COUNT(t.id) > 2
```

**Wren tools called:** mcp__wren__get_instructions, mcp__wren__list_models, mcp__wren__recall_queries, mcp__wren__describe_model, mcp__wren__dry_plan

### R04 (R) - WRONG_DATE_LOGIC

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
SELECT w.id, w.name FROM workflows w WHERE NOT EXISTS (SELECT 1 FROM tasks t WHERE t.workflow_id = w.id AND t.due_date < CURRENT_DATE AND t.status <> 'COMPLETED') AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.workflow_id = w.id AND t.status = 'BLOCKED') ORDER BY w.name
```

**Wren tools called:** mcp__wren__get_instructions, mcp__wren__list_models, mcp__wren__recall_queries, mcp__wren__describe_model, mcp__wren__dry_plan

### S02 (S) - SEMANTIC_MISUNDERSTANDING

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
SELECT workflows.id AS workflow_id, workflows.name AS workflow_name, COUNT(tasks.id) FILTER (WHERE tasks.status <> 'COMPLETED') AS outstanding_tasks FROM workflows LEFT JOIN tasks ON tasks.workflow_id = workflows.id GROUP BY workflows.id, workflows.name ORDER BY outstanding_tasks DESC
```

**Wren tools called:** mcp__wren__get_instructions, mcp__wren__list_models, mcp__wren__recall_queries, mcp__wren__describe_model, mcp__wren__dry_plan

## Reading these numbers

- Agentic runs are not deterministic. The same question can pass in one run and fail in the next, so a single run's score carries real run-to-run variance. Repeat a run before treating a difference of a few points as meaningful.
- Result accuracy compares returned rows, never SQL text. Column order and aliases are ignored; row order is enforced only where the question asked for it.
- No database rows were sent to Claude. Generated SQL is executed here, and the results in this report never re-entered the model.

