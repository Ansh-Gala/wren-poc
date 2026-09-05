# Wren + Claude Code text-to-SQL benchmark

Generated 2026-09-05T17:02:40+00:00  
Configuration(s): D  
Privacy mode(s): strict

```
========================================
WREN + CLAUDE BENCHMARK
========================================

Total questions:        65

SQL generated:          65 / 65
SQL executable:         65 / 65
Correct results:        42 / 65

SQL generation:         100.00%
Execution success:      100.00%
Result accuracy:        64.62%
```

## Accuracy by category

| Category | Questions | SQL | Ran | Correct | Accuracy | |
|---|---:|---:|---:|---:|---:|---|
| BO Aggregation | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| BO Filter | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| BU Aggregation | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Basic List | 3 | 3 | 3 | 0 | 0.0% | `........................` |
| Business Unit Filter | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Clarification | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Combined Filter | 4 | 4 | 4 | 3 | 75.0% | `##################......` |
| Combined Filter + Sort | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Count | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| Dynamic Attribute Aggregation | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Dynamic Attribute Filter | 4 | 4 | 4 | 2 | 50.0% | `############............` |
| Dynamic Attribute Sort | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| Filter + Limit | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Filter + Sort | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| Golden Regression | 3 | 3 | 3 | 3 | 100.0% | `########################` |
| Limit | 4 | 4 | 4 | 3 | 75.0% | `##################......` |
| MY_TASK | 7 | 7 | 7 | 2 | 28.6% | `#######.................` |
| MY_TASK + Workflow | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| MY_TASK Aggregation | 4 | 4 | 4 | 4 | 100.0% | `########################` |
| Natural Language Variation | 6 | 6 | 6 | 6 | 100.0% | `########################` |
| Sort | 3 | 3 | 3 | 0 | 0.0% | `........................` |
| Sort + Limit | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| Task Aggregation | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| Task Count | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Task Filter | 2 | 2 | 2 | 0 | 0.0% | `........................` |
| Task Filter + Limit | 1 | 1 | 1 | 0 | 0.0% | `........................` |
| Task List | 1 | 1 | 1 | 1 | 100.0% | `########################` |
| Task Status Aggregation | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| Unsupported | 2 | 2 | 2 | 2 | 100.0% | `########################` |
| Unsupported / Clarification | 1 | 1 | 1 | 1 | 100.0% | `########################` |

## Failure categories

| Category | Count | Basis |
|---|---:|---|
| HALLUCINATED_SCHEMA | 23 | deterministic |

**Deterministic** categories are read from facts: a process that timed out, a tool that returned an error, a gate that refused the statement, or a SQLSTATE PostgreSQL itself returned.

**Heuristic** categories are inferred by diffing the generated SQL against the expected SQL. There are many correct ways to write a query, so a structural difference is not proof of the cause. Treat these as triage hints, not findings; `RESULT_MISMATCH` is the honest default when nothing else was confident.

## Wren MCP tools used

| Tool | Calls |
|---|---:|
| `mcp__wren__describe_model` | 108 |
| `mcp__wren__dry_plan` | 99 |
| `mcp__wren__recall_queries` | 67 |
| `mcp__wren__list_models` | 65 |
| `mcp__wren__get_instructions` | 64 |
| `mcp__wren__list_stored_queries` | 2 |
| `Skill` | 1 |
| `ReportFindings` | 1 |
| `mcp__wren__list_cubes` | 1 |

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
SELECT business_object_id, business_object_ref_id, business_unit, business_object_status FROM tms_business_object_flat WHERE business_object_type = 'AR_YD_Suiting'
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__describe_model, mcp__wren__get_instructions, mcp__wren__dry_plan

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
SELECT business_object_id, business_object_ref_id, business_object_type FROM tms_business_object_flat WHERE business_object_type = 'AR_YD_Suiting'
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__describe_model, mcp__wren__get_instructions, mcp__wren__dry_plan

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
SELECT business_object_id, business_object_ref_id, business_unit, business_object_type, business_object_status FROM tms_business_object_flat WHERE business_object_type = 'AR_NPD_Shirting'
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__describe_model, mcp__wren__get_instructions, mcp__wren__dry_plan

### T07 (BO Filter) - HALLUCINATED_SCHEMA

**Question:** Show AR_YD_Suiting items with status Active

**Expected SQL**

```sql
SELECT business_object_id, business_object_ref_id, business_unit,
       business_object_status
FROM tms_business_object_flat
WHERE business_object_type = 'AR_YD_Suiting'
  AND business_object_status = 'Active'
```

**Generated SQL**

```sql
SELECT business_object_id, business_object_ref_id, business_object_type, business_object_status FROM tms_business_object_flat WHERE business_object_type = 'AR_YD_Suiting' AND business_object_status = 'Active'
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

### T15 (Dynamic Attribute Filter) - HALLUCINATED_SCHEMA

**Question:** Show AR_NPD_YD_SHIRTING items where category is Shirting

**Expected SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, b.business_object_status,
       a.category
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a
  ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SHIRTING'
  AND a.category = 'Shirting'
```

**Generated SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, b.business_object_type, a.category
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SHIRTING' AND a.category = 'Shirting'
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__describe_model, mcp__wren__get_instructions, mcp__wren__dry_plan

### T16 (Dynamic Attribute Filter) - HALLUCINATED_SCHEMA

**Question:** Show AR_YD_Suiting items where category is Suiting

**Expected SQL**

```sql
SELECT b.business_object_id, b.business_object_ref_id, b.business_object_status,
       a.category
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a
  ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_YD_Suiting'
  AND a.category = 'Suiting'
```

**Generated SQL**

```sql
SELECT b.business_object_ref_id, b.business_object_type, a.category FROM tms_business_object_flat b JOIN tms_business_object_attributes_flat a ON a.business_object_id = b.business_object_id WHERE b.business_object_type = 'AR_YD_Suiting' AND a.category = 'Suiting'
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__describe_model, mcp__wren__get_instructions, mcp__wren__dry_plan

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
SELECT bo.business_object_id, bo.business_object_ref_id, attr.season FROM tms_business_object_flat bo JOIN tms_business_object_attributes_flat attr ON attr.business_object_id = bo.business_object_id WHERE bo.business_object_type = 'AR_NPD_YD_SALESPLAN' ORDER BY attr.season
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

### T19 (Task Filter) - HALLUCINATED_SCHEMA

**Question:** Show open tasks in AR_YD_Suiting

**Expected SQL**

```sql
SELECT task_id, task_display_name, assigned_user_name
FROM tms_task_flat
WHERE business_object_type = 'AR_YD_Suiting'
  AND task_status = 'open'
```

**Generated SQL**

```sql
SELECT task_id, task_display_name, business_object_ref_id, business_object_type, task_status FROM tms_task_flat WHERE business_object_type = 'AR_YD_Suiting' AND task_status = 'open'
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

### T20 (Task Filter) - HALLUCINATED_SCHEMA

**Question:** Show closed tasks in AR_YD_Suiting

**Expected SQL**

```sql
SELECT task_id, task_display_name, assigned_user_name
FROM tms_task_flat
WHERE business_object_type = 'AR_YD_Suiting'
  AND task_status = 'closed'
```

**Generated SQL**

```sql
SELECT task_id, task_display_name, business_object_ref_id
FROM tms_task_flat
WHERE business_object_type = 'AR_YD_Suiting' AND task_status = 'closed'
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

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

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__list_stored_queries, mcp__wren__dry_plan

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
SELECT task_id, task_display_name, business_object_ref_id
FROM tms_task_flat
WHERE assigned_user_id = 1
  AND task_status = 'open'
  AND display_flag = 1
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

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
SELECT task_id, task_display_name, task_status FROM tms_task_flat WHERE assigned_user_id = 1 AND task_status = 'open' AND display_flag = 1
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

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
SELECT task_id, task_display_name, business_object_ref_id
FROM tms_task_flat
WHERE assigned_user_id = 1
  AND task_status = 'open'
  AND display_flag = 1
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

### T40 (MY_TASK) - HALLUCINATED_SCHEMA

**Question:** Which tasks are assigned to me?

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
SELECT task_id, task_display_name, business_object_ref_id
FROM tms_task_flat
WHERE assigned_user_id = 1
  AND task_status = 'open'
  AND display_flag = 1
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

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
SELECT task_id, task_display_name, business_object_ref_id FROM tms_task_flat WHERE assigned_user_id = 1 AND task_status = 'open' AND display_flag = 1 AND task_sla_status = 'Delayed'
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

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
SELECT task_id, task_display_name, business_object_ref_id FROM tms_task_flat WHERE assigned_user_id = 1 AND task_status = 'open' AND display_flag = 1 AND business_object_type = 'AR_YD_Suiting'
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

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
SELECT bof.business_object_id, bof.business_object_ref_id, bof.business_unit, boa.category FROM tms_business_object_flat bof JOIN tms_business_object_attributes_flat boa ON boa.business_object_id = bof.business_object_id WHERE bof.business_unit = 'PVH' AND boa.category = 'Prints'
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__describe_model, mcp__wren__get_instructions, mcp__wren__dry_plan

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
SELECT bo.business_object_ref_id, attr.season
FROM tms_business_object_flat bo
JOIN tms_business_object_attributes_flat attr ON attr.business_object_id = bo.business_object_id
WHERE bo.business_object_type = 'AR_NPD_YD_SALESPLAN'
ORDER BY attr.season
LIMIT 5
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__describe_model, mcp__wren__get_instructions, mcp__wren__dry_plan

### T72 (Limit) - HALLUCINATED_SCHEMA

**Question:** Give me 3 AR_YD_Suiting items

**Expected SQL**

```sql
SELECT business_object_id, business_object_ref_id, business_unit,
       business_object_status
FROM tms_business_object_flat
WHERE business_object_type = 'AR_YD_Suiting'
LIMIT 3
```

**Generated SQL**

```sql
SELECT business_object_id, business_object_ref_id, business_object_type FROM tms_business_object_flat WHERE business_object_type = 'AR_YD_Suiting' LIMIT 3
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__describe_model, mcp__wren__dry_plan

### T74 (Task Filter + Limit) - HALLUCINATED_SCHEMA

**Question:** Show 5 open tasks

**Expected SQL**

```sql
SELECT task_id, task_display_name, assigned_user_name, business_object_ref_id
FROM tms_task_flat
WHERE task_status = 'open'
LIMIT 5
```

**Generated SQL**

```sql
SELECT task_id, task_display_name, business_object_ref_id FROM tms_task_flat WHERE task_status = 'open' LIMIT 5
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

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
SELECT bo.business_object_ref_id, attr.category FROM tms_business_object_flat bo JOIN tms_business_object_attributes_flat attr ON attr.business_object_id = bo.business_object_id WHERE bo.business_object_type = 'AR_NPD_YD_SHIRTING' ORDER BY attr.category
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__get_instructions, mcp__wren__describe_model, mcp__wren__dry_plan

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
SELECT b.business_object_id, b.business_object_ref_id, a.season FROM tms_business_object_flat b JOIN tms_business_object_attributes_flat a ON a.business_object_id = b.business_object_id WHERE b.business_object_type = 'AR_NPD_YD_SALESPLAN' ORDER BY a.season ASC
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__describe_model, mcp__wren__get_instructions, mcp__wren__dry_plan

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
SELECT b.business_object_id, b.business_object_ref_id, b.business_object_type, a.season
FROM tms_business_object_flat b
JOIN tms_business_object_attributes_flat a ON a.business_object_id = b.business_object_id
WHERE b.business_object_type = 'AR_NPD_YD_SALESPLAN'
ORDER BY a.season DESC
```

**Wren tools called:** mcp__wren__recall_queries, mcp__wren__list_models, mcp__wren__describe_model, mcp__wren__get_instructions, mcp__wren__dry_plan

## Reading these numbers

- Agentic runs are not deterministic. The same question can pass in one run and fail in the next, so a single run's score carries real run-to-run variance. Repeat a run before treating a difference of a few points as meaningful.
- Result accuracy compares returned rows, never SQL text. Column order and aliases are ignored; row order is enforced only where the question asked for it.
- No database rows were sent to Claude. Generated SQL is executed here, and the results in this report never re-entered the model.

