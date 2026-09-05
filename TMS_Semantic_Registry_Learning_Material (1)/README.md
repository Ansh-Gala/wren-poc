# TMS Semantic Registry – AI Learning Material

## Purpose
This package is a semantic learning layer for an AI agent that needs to answer natural-language questions about TMS data and generate safe SQL against the TMS flat tables.

## Canonical entities
- Business Object: Initiative = Order = BO = Business Object
- Task: TMS task / work item / ticket
- User: TMS user / employee
- Role: TMS role / organizational role

## Canonical flat tables
- `tms_business_object_flat`: one row per Business Object / Initiative / Order / BO
- `tms_task_flat`: one row per task
- `tms_user_flat`: one row per user
- `tms_role_flat`: one row per role/department mapping

## How to use this package
1. Load `semantic_glossary.yaml` as the business vocabulary.
2. Load `table_registry.yaml` as the table/column semantic registry.
3. Load `business_rules.yaml` as governed business definitions.
4. Load `query_examples.yaml` as few-shot examples.
5. Use `synonyms.yaml` for entity and field synonym resolution.
6. Use `guardrails.yaml` before allowing an AI-generated query to execute.

## Important
This package is based on the TMS structure and queries discussed so far. Where the exact source schema/business meaning was not fully established, the material marks the item as `needs_validation` rather than inventing a definition.
