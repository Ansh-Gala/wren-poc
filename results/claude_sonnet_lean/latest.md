# Wren + Claude Code text-to-SQL benchmark

Generated 2026-09-05T17:16:10+00:00  
Configuration(s): D  
Privacy mode(s): strict

```
========================================
WREN + CLAUDE BENCHMARK
========================================

Total questions:        65

SQL generated:          65 / 65
SQL executable:         65 / 65
Correct results:        47 / 65

SQL generation:         100.00%
Execution success:      100.00%
Result accuracy:        72.31%
```

## Accuracy by category

| Category | Questions | SQL | Ran | Correct | Accuracy | |
|---|---:|---:|---:|---:|---:|---|
| BO Aggregation | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| BO Filter | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| BU Aggregation | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Basic List | 3 | 3 | 3 | 0 | 0.0% | `........................` |
| Business Unit Filter | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Clarification | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Combined Filter | 4 | 4 | 4 | 3 | 75.0% | `##################......` |
| Combined Filter + Sort | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Count | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| Dynamic Attribute Aggregation | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Dynamic Attribute Filter | 4 | 4 | 4 | 3 | 75.0% | `##################......` |
| Dynamic Attribute Sort | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| Filter + Limit | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Filter + Sort | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| Golden Regression | 3 | 3 | 3 | 3 | 100.0% | `########################` |
| Limit | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| MY_TASK | 7 | 7 | 7 | 3 | 42.9% | `##########..............` |
| MY_TASK + Workflow | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| MY_TASK Aggregation | 4 | 4 | 4 | 3 | 75.0% | `##################......` |
| Natural Language Variation | 6 | 6 | 6 | 6 | 100.0% | `########################` |
| Sort | 3 | 3 | 3 | 0 | 0.0% | `........................` |
| Sort + Limit | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| Task Aggregation | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| Task Count | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Task Filter | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| Task Filter + Limit | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Task List | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Task Status Aggregation | 2 | 2 | 2 | 1 | 50.0% | `############............` |
| Unsupported | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| Unsupported / Clarification | 1 | 1 | 1 | 1 | 100.0% | `########################` |

## Failure categories

| Category | Count | Basis |
|---|---:|---|
| HALLUCINATED_SCHEMA | 18 | deterministic |

**Deterministic** categories are read from facts: a process that timed out, a tool that returned an error, a gate that refused the statement, or a SQLSTATE PostgreSQL itself returned.

**Heuristic** categories are inferred by diffing the generated SQL against the expected SQL. There are many correct ways to write a query, so a structural difference is not proof of the cause. Treat these as triage hints, not findings; `RESULT_MISMATCH` is the honest default when nothing else was confident.

## Failures

### T01 (Basic List) - HALLUCINATED_SCHEMA

**Question:** Show the AR_YD_Suiting items

**Expected SQL**

```sql
SELECT business_object_id, business_object_ref_id, business_unit,
       business_object_status, business_object_color
FROM tms_business_object_flat
WHERE business_object_type = 'AR_YD_Suiting'
```

**Generated SQL**

```sql
SELECT business_object_id, business_object_ref_id, business_unit, business_object_type, business_object_status FROM tms_business_object_flat WHERE business_object_type = 'AR_YD_Suiting'
```

### T02 (Basic List) - HALLUCINATED_SCHEMA

**Question:** List all AR_YD_Suiting items

**Expected SQL**

```sql
SELECT business_object_id, business_object_ref_id, business_unit,
       business_object_status, business_object_color
FROM tms_business_object_flat
WHERE business_object_type = 'AR_YD_Suiting'
```

**Generated SQL**

```sql
SELECT business_object_id, business_object_ref_id, business_unit, business_object_status
FROM tms_business_object_flat
WHERE business_object_type = 'AR_YD_Suiting'
```

### T05 (Basic List) - HALLUCINATED_SCHEMA

**Question:** Show me all AR_NPD_Shirting items

**Expected SQL**

```sql
SELECT business_object_id, business_object_ref_id, business_unit,
       business_object_status, business_object_color
FROM tms_business_object_flat
WHERE business_object_type = 'AR_NPD_Shirting'
```

**Generated SQL**

```sql
SELECT business_object_id, business_object_ref_id, business_unit, business_object_status FROM tms_business_object_flat WHERE business_object_type = 'AR_NPD_Shirting'
```

### T13 (Dynamic Attribute Filter) - HALLUCINATED_SCHEMA

**Question:** Show AR_NPD_YD_SALESPLAN items where season is Winter

**Expected SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, b.business_object_status,
       a.season
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a
  ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SALESPLAN'
  AND a.season = 'Winter'
```

**Generated SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, b.business_unit, b.business_object_type, a.season
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SALESPLAN' AND a.season = 'Winter'
```

### T17 (Dynamic Attribute Sort) - HALLUCINATED_SCHEMA

**Question:** Sort AR_NPD_YD_SALESPLAN items by season

**Expected SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, b.business_object_status,
       a.season
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a
  ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SALESPLAN'
ORDER BY a.season
```

**Generated SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, a.season
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SALESPLAN'
ORDER BY a.season
```

### T25 (Task Status Aggregation) - HALLUCINATED_SCHEMA

**Question:** Give me the task status breakdown for AR_YD_Suiting

**Expected SQL**

```sql
SELECT task_status, COUNT(*)
FROM tms_task_flat
WHERE business_object_type = 'AR_YD_Suiting'
GROUP BY task_status
```

**Generated SQL**

```sql
SELECT t.task_display_status, COUNT(*) AS task_count
FROM tms_task_flat t
JOIN tms_business_object_flat b ON t.bo_id = b.business_object_id
WHERE b.business_object_type = 'AR_YD_Suiting'
GROUP BY t.task_display_status
ORDER BY task_count DESC
```

### T28 (Filter + Sort) - HALLUCINATED_SCHEMA

**Question:** Show PVH items sorted by season

**Expected SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, b.business_object_status,
       a.season
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a
  ON a.business_object_id = b.business_object_id
WHERE b.business_unit = 'PVH'
ORDER BY a.season
```

**Generated SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, b.business_unit, a.season FROM tms_business_object_flat b JOIN tms_business_object_attributes_flat a ON a.business_object_id = b.business_object_id WHERE b.business_unit = 'PVH' ORDER BY a.season
```

### T37 (MY_TASK) - HALLUCINATED_SCHEMA

**Question:** Show my tasks

**Expected SQL**

```sql
SELECT task_id, task_display_name, task_status, business_object_ref_id
FROM tms_task_flat
WHERE assigned_user_id = 1
  AND task_status = 'open'
  AND display_flag = 1
```

**Generated SQL**

```sql
SELECT task_id, task_display_name, business_object_ref_id FROM tms_task_flat WHERE assigned_user_id = 1 AND task_status = 'open' AND display_flag = 1
```

### T38 (MY_TASK) - HALLUCINATED_SCHEMA

**Question:** Show tasks assigned to me

**Expected SQL**

```sql
SELECT task_id, task_display_name, task_status, business_object_ref_id
FROM tms_task_flat
WHERE assigned_user_id = 1
  AND task_status = 'open'
  AND display_flag = 1
```

**Generated SQL**

```sql
SELECT task_id, task_display_name, business_object_ref_id FROM tms_task_flat WHERE assigned_user_id = 1 AND task_status = 'open' AND display_flag = 1
```

### T39 (MY_TASK) - HALLUCINATED_SCHEMA

**Question:** What are my tasks?

**Expected SQL**

```sql
SELECT task_id, task_display_name, task_status, business_object_ref_id
FROM tms_task_flat
WHERE assigned_user_id = 1
  AND task_status = 'open'
  AND display_flag = 1
```

**Generated SQL**

```sql
SELECT task_id, task_display_name, business_object_ref_id, task_display_status
FROM tms_task_flat
WHERE assigned_user_id = 1
  AND task_status = 'open'
  AND display_flag = 1
```

### T43 (MY_TASK) - HALLUCINATED_SCHEMA

**Question:** Show my delayed tasks

**Expected SQL**

```sql
SELECT task_id, task_display_name, task_sla_status, business_object_ref_id
FROM tms_task_flat
WHERE assigned_user_id = 1
  AND task_sla_status = 'Delayed'
```

**Generated SQL**

```sql
SELECT task_id, task_display_name, business_object_ref_id, task_sla_status
FROM tms_task_flat
WHERE assigned_user_id = 1
  AND task_status = 'open'
  AND display_flag = 1
  AND task_sla_status = 'Delayed'
```

### T44 (MY_TASK + Workflow) - HALLUCINATED_SCHEMA

**Question:** Show my tasks in AR_YD_Suiting

**Expected SQL**

```sql
SELECT task_id, task_display_name, task_status, business_object_ref_id
FROM tms_task_flat
WHERE assigned_user_id = 1
  AND business_object_type = 'AR_YD_Suiting'
  AND task_status = 'open'
  AND display_flag = 1
```

**Generated SQL**

```sql
SELECT t.task_id, t.task_display_name, t.business_object_ref_id
FROM tms_task_flat t
WHERE t.assigned_user_id = 1
  AND t.task_status = 'open'
  AND t.display_flag = 1
  AND t.business_object_type = 'AR_YD_Suiting'
```

### T48 (MY_TASK Aggregation) - HALLUCINATED_SCHEMA

**Question:** Give me my task status breakdown

**Expected SQL**

```sql
SELECT task_status, COUNT(*)
FROM tms_task_flat
WHERE assigned_user_id = 1
GROUP BY task_status
```

**Generated SQL**

```sql
SELECT task_display_status, COUNT(*) AS task_count
FROM tms_task_flat
WHERE assigned_user_id = 1
  AND task_status = 'open'
  AND display_flag = 1
GROUP BY task_display_status
```

### T68 (Combined Filter) - HALLUCINATED_SCHEMA

**Question:** Show PVH items with category Prints

**Expected SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, b.business_object_status,
       a.category
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a
  ON a.business_object_id = b.business_object_id
WHERE b.business_unit = 'PVH'
  AND a.category = 'Prints'
```

**Generated SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, b.business_unit, b.business_object_type, a.category
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a ON a.business_object_id = b.business_object_id
WHERE b.business_unit = 'PVH' AND a.category = 'Prints'
```

### T70 (Sort + Limit) - HALLUCINATED_SCHEMA

**Question:** Show the first 5 AR_NPD_YD_SALESPLAN items sorted by season

**Expected SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, b.business_object_status,
       a.season
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a
  ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SALESPLAN'
ORDER BY a.season
LIMIT 5
```

**Generated SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, a.season
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SALESPLAN'
ORDER BY a.season
LIMIT 5
```

### T75 (Sort) - HALLUCINATED_SCHEMA

**Question:** Sort AR_NPD_YD_SHIRTING items by category

**Expected SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, b.business_object_status,
       a.category
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a
  ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SHIRTING'
ORDER BY a.category
```

**Generated SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, a.category
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SHIRTING'
ORDER BY a.category
```

### T76 (Sort) - HALLUCINATED_SCHEMA

**Question:** Show AR_NPD_YD_SALESPLAN items in ascending season order

**Expected SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, b.business_object_status,
       a.season
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a
  ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SALESPLAN'
ORDER BY a.season ASC
```

**Generated SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, a.season
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SALESPLAN'
ORDER BY a.season ASC
```

### T77 (Sort) - HALLUCINATED_SCHEMA

**Question:** Show AR_NPD_YD_SALESPLAN items in descending season order

**Expected SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, b.business_object_status,
       a.season
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a
  ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SALESPLAN'
ORDER BY a.season DESC
```

**Generated SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, a.season
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SALESPLAN'
ORDER BY a.season DESC
```

## Reading these numbers

- Agentic runs are not deterministic. The same question can pass in one run and fail in the next, so a single run's score carries real run-to-run variance. Repeat a run before treating a difference of a few points as meaningful.
- Result accuracy compares returned rows, never SQL text. Column order and aliases are ignored; row order is enforced only where the question asked for it.
- No database rows were sent to Claude. Generated SQL is executed here, and the results in this report never re-entered the model.

