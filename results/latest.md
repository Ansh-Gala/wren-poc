# Wren + Claude Code text-to-SQL benchmark

Generated 2026-09-04T10:28:37+00:00  
Configuration(s): D  
Privacy mode(s): strict

```
========================================
WREN + CLAUDE BENCHMARK
========================================

Total questions:        81

SQL generated:          28 / 81
SQL executable:         28 / 81
Correct results:        27 / 81

SQL generation:         34.57%
Execution success:      34.57%
Result accuracy:        33.33%
```

## Accuracy by category

| Category | Questions | SQL | Ran | Correct | Accuracy | |
|---|---:|---:|---:|---:|---:|---|
| A | 3 | 2 | 2 | 2 | 66.7% | `################........` |
| B | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| C | 3 | 3 | 3 | 2 | 66.7% | `################........` |
| D | 3 | 3 | 3 | 3 | 100.0% | `########################` |
| E | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| F | 5 | 5 | 5 | 5 | 100.0% | `########################` |
| G | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| H | 4 | 3 | 3 | 3 | 75.0% | `##################......` |
| I | 4 | 0 | 0 | 0 | 0.0% | `........................` |
| J | 4 | 0 | 0 | 0 | 0.0% | `........................` |
| K | 4 | 0 | 0 | 0 | 0.0% | `........................` |
| L | 5 | 0 | 0 | 0 | 0.0% | `........................` |
| M | 4 | 0 | 0 | 0 | 0.0% | `........................` |
| N | 5 | 0 | 0 | 0 | 0.0% | `........................` |
| O | 4 | 0 | 0 | 0 | 0.0% | `........................` |
| P | 5 | 0 | 0 | 0 | 0.0% | `........................` |
| Q | 5 | 0 | 0 | 0 | 0.0% | `........................` |
| R | 6 | 0 | 0 | 0 | 0.0% | `........................` |
| S | 5 | 0 | 0 | 0 | 0.0% | `........................` |

## Failure categories

| Category | Count | Basis |
|---|---:|---|
| CLI_FAILURE | 53 | deterministic |
| WRONG_FILTER | 1 | heuristic |

**Deterministic** categories are read from facts: a process that timed out, a tool that returned an error, a gate that refused the statement, or a SQLSTATE PostgreSQL itself returned.

**Heuristic** categories are inferred by diffing the generated SQL against the expected SQL. There are many correct ways to write a query, so a structural difference is not proof of the cause. Treat these as triage hints, not findings; `RESULT_MISMATCH` is the honest default when nothing else was confident.

## Failures

### A01 (A) - CLI_FAILURE

**Question:** List every user with their name, email and department.

**Expected SQL**

```sql
SELECT full_name, email, department FROM users
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': "Request too large for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on output tokens per minute (OTPM): Limit 1000, Requested 1236. The request's expected output tokens exceed the enforced limit; reduce max`

### C03 (C) - WRONG_FILTER

**Question:** Show the unfinished tasks with the earliest due date first.

**Expected SQL**

```sql
SELECT name, due_date FROM tasks
WHERE status <> 'COMPLETED'
ORDER BY due_date, name
```

**Generated SQL**

```sql
SELECT t.id, t.name, t.due_date, t.status, t.priority, t.workflow_id, t.assigned_user_id
FROM tasks t
WHERE t.status <> 'COMPLETED'
ORDER BY t.due_date ASC NULLS LAST
```

### H04 (H) - CLI_FAILURE

**Question:** Show each assigned task with the department of the person assigned to it.

**Expected SQL**

```sql
SELECT t.name AS task_name, u.department
FROM tasks t
JOIN users u ON u.id = t.assigned_user_id
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199987, Requested 5095. Please try again in 36m35.424s. Need more tokens? Upgrade to Dev Tier`

### I01 (I) - CLI_FAILURE

**Question:** For every assigned task, show the task name, its workflow name and the department of the person assigned to it.

**Expected SQL**

```sql
SELECT t.name AS task_name, w.name AS workflow_name, u.department
FROM tasks t
JOIN workflows w ON w.id = t.workflow_id
JOIN users u ON u.id = t.assigned_user_id
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199981, Requested 5106. Please try again in 36m37.583999999s. Need more tokens? Upgrade to De`

### I02 (I) - CLI_FAILURE

**Question:** Show each task with the name of its workflow and the name of that workflow's owner.

**Expected SQL**

```sql
SELECT t.name AS task_name, w.name AS workflow_name, o.full_name AS owner
FROM tasks t
JOIN workflows w ON w.id = t.workflow_id
JOIN users o ON o.id = w.owner_user_id
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199975, Requested 5101. Please try again in 36m32.832s. Need more tokens? Upgrade to Dev Tier`

### I03 (I) - CLI_FAILURE

**Question:** For each blocked task, show the task name, the workflow name and the workflow owner's name.

**Expected SQL**

```sql
SELECT t.name AS task_name, w.name AS workflow_name, o.full_name AS owner
FROM tasks t
JOIN workflows w ON w.id = t.workflow_id
JOIN users o ON o.id = w.owner_user_id
WHERE t.status = 'BLOCKED'
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199969, Requested 5089. Please try again in 36m25.056s. Need more tokens? Upgrade to Dev Tier`

### I04 (I) - CLI_FAILURE

**Question:** For every assigned task show the task name, the workflow name, the assignee's name and the workflow owner's name.

**Expected SQL**

```sql
SELECT t.name AS task_name,
       w.name AS workflow_name,
       a.full_name AS assignee,
       o.full_name AS owner
FROM tasks t
JOIN workflows w ON w.id = t.workflow_id
JOIN users a ON a.id = t.assigned_user_id
JOIN users o ON o.id = w.owner_user_id
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199963, Requested 5094. Please try again in 36m24.623999999s. Need more tokens? Upgrade to De`

### J01 (J) - CLI_FAILURE

**Question:** Which users do not own any workflow?

**Expected SQL**

```sql
SELECT u.full_name
FROM users u
LEFT JOIN workflows w ON w.owner_user_id = u.id
WHERE w.id IS NULL
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199957, Requested 5089. Please try again in 36m19.871999999s. Need more tokens? Upgrade to De`

### J02 (J) - CLI_FAILURE

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
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199951, Requested 5086. Please try again in 36m15.984s. Need more tokens? Upgrade to Dev Tier`

### J03 (J) - CLI_FAILURE

**Question:** List every task with its assignee's name, including tasks that nobody is assigned to.

**Expected SQL**

```sql
SELECT t.name AS task_name, u.full_name AS assignee
FROM tasks t
LEFT JOIN users u ON u.id = t.assigned_user_id
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199945, Requested 5099. Please try again in 36m19.007999999s. Need more tokens? Upgrade to De`

### J04 (J) - CLI_FAILURE

**Question:** Which users neither own a workflow nor have any task assigned to them?

**Expected SQL**

```sql
SELECT u.full_name
FROM users u
WHERE NOT EXISTS (SELECT 1 FROM workflows w WHERE w.owner_user_id = u.id)
  AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.assigned_user_id = u.id)
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199940, Requested 5097. Please try again in 36m15.984s. Need more tokens? Upgrade to Dev Tier`

### K01 (K) - CLI_FAILURE

**Question:** Which tasks have no completion date recorded?

**Expected SQL**

```sql
SELECT name FROM tasks WHERE completed_at IS NULL
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199934, Requested 5091. Please try again in 36m10.8s. Need more tokens? Upgrade to Dev Tier t`

### K02 (K) - CLI_FAILURE

**Question:** Which tasks have a completion date recorded, and when were they completed?

**Expected SQL**

```sql
SELECT name, completed_at FROM tasks WHERE completed_at IS NOT NULL
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199927, Requested 5095. Please try again in 36m9.504s. Need more tokens? Upgrade to Dev Tier `

### K03 (K) - CLI_FAILURE

**Question:** Which tasks have nobody assigned to them?

**Expected SQL**

```sql
SELECT name FROM tasks WHERE assigned_user_id IS NULL
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199922, Requested 5091. Please try again in 36m5.616s. Need more tokens? Upgrade to Dev Tier `

### K04 (K) - CLI_FAILURE

**Question:** Which tasks have no due date set?

**Expected SQL**

```sql
SELECT name FROM tasks WHERE due_date IS NULL
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199916, Requested 5089. Please try again in 36m2.159999999s. Need more tokens? Upgrade to Dev`

### L01 (L) - CLI_FAILURE

**Question:** Which tasks are due today and not yet finished?

**Expected SQL**

```sql
SELECT name FROM tasks
WHERE due_date = CURRENT_DATE AND status <> 'COMPLETED'
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199909, Requested 5093. Please try again in 36m0.864s. Need more tokens? Upgrade to Dev Tier `

### L02 (L) - CLI_FAILURE

**Question:** For each late unfinished task, how many days past its due date is it?

**Expected SQL**

```sql
SELECT name, CURRENT_DATE - due_date AS days_overdue
FROM tasks
WHERE due_date < CURRENT_DATE AND status <> 'COMPLETED'
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199903, Requested 5097. Please try again in 36m0s. Need more tokens? Upgrade to Dev Tier toda`

### L03 (L) - CLI_FAILURE

**Question:** Which tasks were completed during the current calendar month?

**Expected SQL**

```sql
SELECT name FROM tasks
WHERE completed_at >= date_trunc('month', CURRENT_DATE)
  AND completed_at < date_trunc('month', CURRENT_DATE) + INTERVAL '1 month'
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199898, Requested 5093. Please try again in 35m56.112s. Need more tokens? Upgrade to Dev Tier`

### L04 (L) - CLI_FAILURE

**Question:** Which workflows were created in the last 30 days?

**Expected SQL**

```sql
SELECT name FROM workflows
WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199892, Requested 5093. Please try again in 35m53.52s. Need more tokens? Upgrade to Dev Tier `

### L05 (L) - CLI_FAILURE

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
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199886, Requested 5098. Please try again in 35m53.088s. Need more tokens? Upgrade to Dev Tier`

### M01 (M) - CLI_FAILURE

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
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199880, Requested 5105. Please try again in 35m53.52s. Need more tokens? Upgrade to Dev Tier `

### M02 (M) - CLI_FAILURE

**Question:** Categorise every user's workload as 'None' when they have no assigned tasks, 'Light' for 1 to 3 tasks, and 'Heavy' for 4 or more.

**Expected SQL**

```sql
SELECT u.full_name,
       CASE WHEN COUNT(t.id) = 0 THEN 'None'
            WHEN COUNT(t.id) <= 3 THEN 'Light'
            ELSE 'Heavy' END AS workload
FROM users u
LEFT JOIN tasks t ON t.assigned_user_id = u.id
GROUP BY u.id, u.full_name
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199874, Requested 5121. Please try again in 35m57.84s. Need more tokens? Upgrade to Dev Tier `

### M03 (M) - CLI_FAILURE

**Question:** Categorise each workflow as 'Empty' when it has no tasks, 'Small' for 1 to 8 tasks, and 'Large' for 9 or more.

**Expected SQL**

```sql
SELECT w.name,
       CASE WHEN COUNT(t.id) = 0 THEN 'Empty'
            WHEN COUNT(t.id) <= 8 THEN 'Small'
            ELSE 'Large' END AS size_band
FROM workflows w
LEFT JOIN tasks t ON t.workflow_id = w.id
GROUP BY w.id, w.name
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199868, Requested 5104. Please try again in 35m47.904s. Need more tokens? Upgrade to Dev Tier`

### M04 (M) - CLI_FAILURE

**Question:** Show each task with a numeric urgency score: 4 for critical, 3 for high, 2 for medium and 1 for low priority.

**Expected SQL**

```sql
SELECT name,
       CASE priority
         WHEN 'CRITICAL' THEN 4
         WHEN 'HIGH' THEN 3
         WHEN 'MEDIUM' THEN 2
         WHEN 'LOW' THEN 1
       END AS urgency
FROM tasks
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199863, Requested 5099. Please try again in 35m43.583999999s. Need more tokens? Upgrade to De`

### N01 (N) - CLI_FAILURE

**Question:** Which user has completed the most tasks?

**Expected SQL**

```sql
SELECT u.full_name
FROM users u
JOIN tasks t ON t.assigned_user_id = u.id
WHERE t.status = 'COMPLETED'
GROUP BY u.id, u.full_name
ORDER BY COUNT(t.id) DESC
LIMIT 1
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199857, Requested 5089. Please try again in 35m36.672s. Need more tokens? Upgrade to Dev Tier`

### N02 (N) - CLI_FAILURE

**Question:** Among workflows that have tasks, which one has the fewest?

**Expected SQL**

```sql
SELECT w.name
FROM workflows w
JOIN tasks t ON t.workflow_id = w.id
GROUP BY w.id, w.name
ORDER BY COUNT(t.id) ASC
LIMIT 1
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199851, Requested 5082. Please try again in 35m31.056s. Need more tokens? Upgrade to Dev Tier`

### N03 (N) - CLI_FAILURE

**Question:** Which users are assigned more tasks than Carol Chen?

**Expected SQL**

```sql
SELECT u.full_name
FROM users u
JOIN tasks t ON t.assigned_user_id = u.id
GROUP BY u.id, u.full_name
HAVING COUNT(t.id) > (
  SELECT COUNT(*) FROM tasks t2
  JOIN users u2 ON u2.id = t2.assigned_user_id
  WHERE u2.full_name = 'Carol Chen'
)
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199845, Requested 5079. Please try again in 35m27.168s. Need more tokens? Upgrade to Dev Tier`

### N04 (N) - CLI_FAILURE

**Question:** Which workflows have more tasks than the average across all workflows, counting workflows with no tasks in that average?

**Expected SQL**

```sql
SELECT w.name
FROM workflows w
LEFT JOIN tasks t ON t.workflow_id = w.id
GROUP BY w.id, w.name
HAVING COUNT(t.id) > (
  SELECT AVG(c) FROM (
    SELECT COUNT(t2.id) AS c
    FROM workflows w2
    LEFT JOIN tasks t2 ON t2.workflow_id = w2.id
    GROUP BY w2.id
  ) s
)
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199839, Requested 5102. Please try again in 35m34.512s. Need more tokens? Upgrade to Dev Tier`

### N05 (N) - CLI_FAILURE

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
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199833, Requested 5093. Please try again in 35m28.031999999s. Need more tokens? Upgrade to De`

### O01 (O) - CLI_FAILURE

**Question:** Using a common table expression, list each workflow with its task count and the name of its owner.

**Expected SQL**

```sql
WITH counts AS (
  SELECT workflow_id, COUNT(*) AS task_count
  FROM tasks GROUP BY workflow_id
)
SELECT w.name, COALESCE(c.task_count, 0) AS task_count, o.full_name AS owner
FROM workflows w
JOIN users o ON o.id = w.owner_user_id
LEFT JOIN counts c ON c.workflow_id = w.id
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199827, Requested 5103. Please try again in 35m29.759999999s. Need more tokens? Upgrade to De`

### O02 (O) - CLI_FAILURE

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
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199821, Requested 5103. Please try again in 35m27.168s. Need more tokens? Upgrade to Dev Tier`

### O03 (O) - CLI_FAILURE

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
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199815, Requested 5085. Please try again in 35m16.8s. Need more tokens? Upgrade to Dev Tier t`

### O04 (O) - CLI_FAILURE

**Question:** For each department, how many tasks in total are assigned to its members?

**Expected SQL**

```sql
SELECT u.department, COUNT(t.id) AS task_count
FROM users u
LEFT JOIN tasks t ON t.assigned_user_id = u.id
GROUP BY u.department
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199808, Requested 5084. Please try again in 35m13.344s. Need more tokens? Upgrade to Dev Tier`

### P01 (P) - CLI_FAILURE

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
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199802, Requested 5101. Please try again in 35m18.096s. Need more tokens? Upgrade to Dev Tier`

### P02 (P) - CLI_FAILURE

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
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199796, Requested 5086. Please try again in 35m9.024s. Need more tokens? Upgrade to Dev Tier `

### P03 (P) - CLI_FAILURE

**Question:** Show each task alongside the total number of tasks belonging to the same workflow.

**Expected SQL**

```sql
SELECT name,
       COUNT(*) OVER (PARTITION BY workflow_id) AS workflow_task_count
FROM tasks
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199790, Requested 5098. Please try again in 35m11.616s. Need more tokens? Upgrade to Dev Tier`

### P04 (P) - CLI_FAILURE

**Question:** For each workflow category, which workflow contains the most tasks?

**Expected SQL**

```sql
WITH counted AS (
  SELECT w.id, w.name, w.category, COUNT(t.id) AS task_count,
         ROW_NUMBER() OVER (PARTITION BY w.category
                            ORDER BY COUNT(t.id) DESC, w.id) AS rn
  FROM workflows w
  LEFT JOIN tasks t ON t.workflow_id = w.id
  GROUP BY w.id, w.name, w.category
)
SELECT category, name, task_count FROM counted WHERE rn = 1
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199783, Requested 5081. Please try again in 35m1.248s. Need more tokens? Upgrade to Dev Tier `

### P05 (P) - CLI_FAILURE

**Question:** Show each task with its priority and the number of tasks that share that priority.

**Expected SQL**

```sql
SELECT name, priority,
       COUNT(*) OVER (PARTITION BY priority) AS same_priority_count
FROM tasks
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199777, Requested 5099. Please try again in 35m6.431999999s. Need more tokens? Upgrade to Dev`

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

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199771, Requested 5080. Please try again in 34m55.632s. Need more tokens? Upgrade to Dev Tier`

### Q02 (Q) - CLI_FAILURE

**Question:** Which workflows have at least one overdue task and an active owner?

**Expected SQL**

```sql
SELECT DISTINCT w.name
FROM workflows w
JOIN users o ON o.id = w.owner_user_id
JOIN tasks t ON t.workflow_id = w.id
WHERE o.status = 'ACTIVE'
  AND t.due_date < CURRENT_DATE
  AND t.status <> 'COMPLETED'
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199765, Requested 5082. Please try again in 34m53.904s. Need more tokens? Upgrade to Dev Tier`

### Q03 (Q) - CLI_FAILURE

**Question:** Which workflows contain more than 3 unfinished tasks of high or critical priority?

**Expected SQL**

```sql
SELECT w.name
FROM workflows w
JOIN tasks t ON t.workflow_id = w.id
WHERE t.status <> 'COMPLETED'
  AND t.priority IN ('HIGH', 'CRITICAL')
GROUP BY w.id, w.name
HAVING COUNT(t.id) > 3
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199757, Requested 5096. Please try again in 34m56.495999999s. Need more tokens? Upgrade to De`

### Q04 (Q) - CLI_FAILURE

**Question:** Which inactive users still have unfinished work assigned to them?

**Expected SQL**

```sql
SELECT DISTINCT u.full_name
FROM users u
JOIN tasks t ON t.assigned_user_id = u.id
WHERE u.status = 'INACTIVE' AND t.status <> 'COMPLETED'
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199751, Requested 5094. Please try again in 34m53.04s. Need more tokens? Upgrade to Dev Tier `

### Q05 (Q) - CLI_FAILURE

**Question:** Which active workflows contain blocked tasks that are assigned to active users?

**Expected SQL**

```sql
SELECT DISTINCT w.name
FROM workflows w
JOIN tasks t ON t.workflow_id = w.id
JOIN users a ON a.id = t.assigned_user_id
WHERE w.status = 'ACTIVE'
  AND t.status = 'BLOCKED'
  AND a.status = 'ACTIVE'
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199745, Requested 5343. Please try again in 36m38.016s. Need more tokens? Upgrade to Dev Tier`

### R01 (R) - CLI_FAILURE

**Question:** Show the active workflows that currently have overdue work.

**Expected SQL**

```sql
SELECT DISTINCT w.name
FROM workflows w
JOIN tasks t ON t.workflow_id = w.id
WHERE w.status = 'ACTIVE'
  AND t.due_date < CURRENT_DATE
  AND t.status <> 'COMPLETED'
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199739, Requested 5091. Please try again in 34m46.56s. Need more tokens? Upgrade to Dev Tier `

### R02 (R) - CLI_FAILURE

**Question:** Which users are overloaded?

**Expected SQL**

```sql
SELECT u.full_name
FROM users u
JOIN tasks t ON t.assigned_user_id = u.id
WHERE t.status <> 'COMPLETED'
GROUP BY u.id, u.full_name
HAVING COUNT(t.id) > (
  SELECT AVG(c) FROM (
    SELECT COUNT(*) AS c FROM tasks
    WHERE status <> 'COMPLETED' AND assigned_user_id IS NOT NULL
    GROUP BY assigned_user_id
  ) s
)
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199733, Requested 5074. Please try again in 34m36.624s. Need more tokens? Upgrade to Dev Tier`

### R03 (R) - CLI_FAILURE

**Question:** Which workflow owners have unfinished high-priority work inside their workflows?

**Expected SQL**

```sql
SELECT DISTINCT o.full_name
FROM workflows w
JOIN users o ON o.id = w.owner_user_id
JOIN tasks t ON t.workflow_id = w.id
WHERE t.status <> 'COMPLETED'
  AND t.priority IN ('HIGH', 'CRITICAL')
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199727, Requested 5094. Please try again in 34m42.672s. Need more tokens? Upgrade to Dev Tier`

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

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199722, Requested 5096. Please try again in 34m41.376s. Need more tokens? Upgrade to Dev Tier`

### R05 (R) - CLI_FAILURE

**Question:** Which departments are carrying the most unfinished work?

**Expected SQL**

```sql
SELECT u.department, COUNT(t.id) AS open_tasks
FROM users u
JOIN tasks t ON t.assigned_user_id = u.id
WHERE t.status <> 'COMPLETED'
GROUP BY u.department
ORDER BY open_tasks DESC, u.department
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199716, Requested 5090. Please try again in 34m36.192s. Need more tokens? Upgrade to Dev Tier`

### R06 (R) - CLI_FAILURE

**Question:** Who owns workflows but is not doing any of the task work themselves?

**Expected SQL**

```sql
SELECT DISTINCT o.full_name
FROM users o
WHERE EXISTS (SELECT 1 FROM workflows w WHERE w.owner_user_id = o.id)
  AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.assigned_user_id = o.id)
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199710, Requested 5179. Please try again in 35m12.048s. Need more tokens? Upgrade to Dev Tier`

### S01 (S) - CLI_FAILURE

**Question:** Which people can take on new work right now?

**Expected SQL**

```sql
SELECT full_name FROM users WHERE status = 'ACTIVE'
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199704, Requested 5091. Please try again in 34m31.44s. Need more tokens? Upgrade to Dev Tier `

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

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199698, Requested 5091. Please try again in 34m28.848s. Need more tokens? Upgrade to Dev Tier`

### S03 (S) - CLI_FAILURE

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
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199692, Requested 5171. Please try again in 35m0.815999999s. Need more tokens? Upgrade to Dev`

### S04 (S) - CLI_FAILURE

**Question:** Which processes are no longer in use?

**Expected SQL**

```sql
SELECT name FROM workflows WHERE status = 'ARCHIVED'
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199686, Requested 5077. Please try again in 34m17.616s. Need more tokens? Upgrade to Dev Tier`

### S05 (S) - CLI_FAILURE

**Question:** Show the people accountable for each process, not the people doing the work.

**Expected SQL**

```sql
SELECT w.name AS workflow_name, o.full_name AS accountable
FROM workflows w
JOIN users o ON o.id = w.owner_user_id
```

**Generated SQL**

```sql
-- no SQL was produced
```

**Error:** `Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01ky4pa3jcfcc909j91mjgvma0` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199680, Requested 5084. Please try again in 34m18.048s. Need more tokens? Upgrade to Dev Tier`

## Reading these numbers

- Agentic runs are not deterministic. The same question can pass in one run and fail in the next, so a single run's score carries real run-to-run variance. Repeat a run before treating a difference of a few points as meaningful.
- Result accuracy compares returned rows, never SQL text. Column order and aliases are ignored; row order is enforced only where the question asked for it.
- No database rows were sent to Claude. Generated SQL is executed here, and the results in this report never re-entered the model.

