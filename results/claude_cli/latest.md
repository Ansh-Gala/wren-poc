# Wren + Claude Code text-to-SQL benchmark

Generated 2026-09-04T11:11:22+00:00  
Configuration(s): D  
Privacy mode(s): strict

```
========================================
WREN + CLAUDE BENCHMARK
========================================

Total questions:        86

SQL generated:          86 / 86
SQL executable:         86 / 86
Correct results:        79 / 86

SQL generation:         100.00%
Execution success:      100.00%
Result accuracy:        91.86%
```

## Accuracy by category

| Category | Questions | SQL | Ran | Correct | Accuracy | |
|---|---:|---:|---:|---:|---:|---|
| A | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| B | 5 | 5 | 5 | 5 | 100.0% | `########################` |
| C | 4 | 4 | 4 | 3 | 75.0% | `##################......` |
| D | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| E | 5 | 5 | 5 | 5 | 100.0% | `########################` |
| F | 5 | 5 | 5 | 5 | 100.0% | `########################` |
| G | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| H | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| I | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| J | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| K | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| L | 5 | 5 | 5 | 4 | 80.0% | `###################.....` |
| M | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| N | 5 | 5 | 5 | 5 | 100.0% | `########################` |
| O | 4 | 4 | 4 | 3 | 75.0% | `##################......` |
| P | 5 | 5 | 5 | 2 | 40.0% | `##########..............` |
| Q | 5 | 5 | 5 | 5 | 100.0% | `########################` |
| R | 6 | 6 | 6 | 6 | 100.0% | `########################` |
| S | 5 | 5 | 5 | 4 | 80.0% | `###################.....` |

## Failure categories

| Category | Count | Basis |
|---|---:|---|
| RESULT_MISMATCH | 3 | heuristic |
| WRONG_DATE_LOGIC | 1 | heuristic |
| WRONG_NULL_HANDLING | 1 | heuristic |
| MISSING_JOIN | 1 | heuristic |
| WRONG_TABLE | 1 | deterministic |

**Deterministic** categories are read from facts: a process that timed out, a tool that returned an error, a gate that refused the statement, or a SQLSTATE PostgreSQL itself returned.

**Heuristic** categories are inferred by diffing the generated SQL against the expected SQL. There are many correct ways to write a query, so a structural difference is not proof of the cause. Treat these as triage hints, not findings; `RESULT_MISMATCH` is the honest default when nothing else was confident.

## Wren MCP tools used

| Tool | Calls |
|---|---:|
| `mcp__wren__dry_plan` | 87 |
| `mcp__wren__recall_queries` | 79 |
| `mcp__wren__list_cubes` | 15 |
| `Bash` | 1 |

## Failures

### C03 (C) - RESULT_MISMATCH

**Question:** Show the unfinished tasks with the earliest due date first.

**Expected SQL**

```sql
SELECT name, due_date FROM tasks
WHERE status <> 'COMPLETED'
ORDER BY due_date, name
```

**Generated SQL**

```sql
SELECT id, name, status, priority, due_date FROM tasks WHERE status <> 'COMPLETED' ORDER BY due_date ASC
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_cubes, mcp__wren__dry_plan

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
SELECT tasks.id, tasks.name, tasks.status, tasks.priority, tasks.due_date, tasks.assigned_user_id FROM tasks WHERE tasks.status <> 'COMPLETED' AND tasks.due_date >= CURRENT_DATE AND tasks.due_date < CURRENT_DATE + INTERVAL '7 days' ORDER BY tasks.due_date
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__dry_plan

### O03 (O) - WRONG_NULL_HANDLING

**Question:** Break the tasks down by workflow and status, showing the count for each combination.

**Expected SQL**

```sql
SELECT w.name AS workflow_name, t.status, COUNT(*) AS task_count
FROM tasks t
JOIN workflows w ON w.id = t.workflow_id
GROUP BY w.name, t.status
```

**Generated SQL**

```sql
SELECT w.name AS workflow_name, t.status AS task_status, COUNT(t.id) AS task_count FROM workflows w LEFT JOIN tasks t ON t.workflow_id = w.id GROUP BY w.name, t.status ORDER BY w.name, t.status
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__dry_plan

### P01 (P) - RESULT_MISMATCH

**Question:** Rank the workflows by how many tasks they contain, showing the rank next to the count.

**Expected SQL**

```sql
SELECT w.name,
       COUNT(t.id) AS task_count,
       RANK() OVER (ORDER BY COUNT(t.id) DESC) AS rank
FROM workflows w
LEFT JOIN tasks t ON t.workflow_id = w.id
GROUP BY w.id, w.name
ORDER BY task_count DESC, w.name
```

**Generated SQL**

```sql
SELECT w.id AS workflow_id, w.name AS workflow_name, COUNT(t.id) AS task_count, RANK() OVER (ORDER BY COUNT(t.id) DESC) AS rank FROM workflows w LEFT JOIN tasks t ON t.workflow_id = w.id GROUP BY w.id, w.name ORDER BY task_count DESC
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_cubes, mcp__wren__dry_plan

### P02 (P) - MISSING_JOIN

**Question:** Within each workflow, number the tasks in order of their due date, earliest first.

**Expected SQL**

```sql
SELECT w.name AS workflow_name,
       t.name AS task_name,
       ROW_NUMBER() OVER (PARTITION BY t.workflow_id ORDER BY t.due_date, t.id) AS seq
FROM tasks t
JOIN workflows w ON w.id = t.workflow_id
```

**Generated SQL**

```sql
SELECT tasks.id AS task_id, tasks.workflow_id, tasks.name, tasks.due_date, ROW_NUMBER() OVER (PARTITION BY tasks.workflow_id ORDER BY tasks.due_date) AS task_order FROM tasks ORDER BY tasks.workflow_id, task_order
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__dry_plan

### P05 (P) - RESULT_MISMATCH

**Question:** Show each task with its priority and the number of tasks that share that priority.

**Expected SQL**

```sql
SELECT name, priority,
       COUNT(*) OVER (PARTITION BY priority) AS same_priority_count
FROM tasks
```

**Generated SQL**

```sql
SELECT tasks.id, tasks.priority, COUNT(*) OVER (PARTITION BY tasks.priority) AS priority_count FROM tasks
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__dry_plan

### S03 (S) - WRONG_TABLE

**Question:** Which tasks need urgent attention?

**Expected SQL**

```sql
SELECT name FROM tasks
WHERE priority IN ('HIGH', 'CRITICAL')
  AND status <> 'COMPLETED'
  AND due_date < CURRENT_DATE
```

**Generated SQL**

```sql
SELECT tasks.id, tasks.name, tasks.status, tasks.priority, tasks.due_date, workflows.name AS workflow_name, users.full_name AS assignee_name
FROM tasks
JOIN workflows ON workflows.id = tasks.workflow_id
LEFT JOIN users ON users.id = tasks.assigned_user_id
WHERE tasks.status <> 'COMPLETED'
  AND (tasks.due_date < CURRENT_DATE OR tasks.priority IN ('HIGH','CRITICAL'))
ORDER BY (tasks.due_date < CURRENT_DATE) DESC,
         CASE tasks.priority WHEN 'CRITICAL' THEN 4 WHEN 'HIGH' THEN 3 WHEN 'MEDIUM' THEN 2 WHEN 'LOW' THEN 1 ELSE 0 END DESC,
         tasks.due_date ASC
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_cubes, mcp__wren__dry_plan

## Reading these numbers

- Agentic runs are not deterministic. The same question can pass in one run and fail in the next, so a single run's score carries real run-to-run variance. Repeat a run before treating a difference of a few points as meaningful.
- Result accuracy compares returned rows, never SQL text. Column order and aliases are ignored; row order is enforced only where the question asked for it.
- No database rows were sent to Claude. Generated SQL is executed here, and the results in this report never re-entered the model.

