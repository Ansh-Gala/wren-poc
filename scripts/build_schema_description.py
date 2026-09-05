"""Regenerate metadata/schema_description.yaml from the database.

    python scripts/build_schema_description.py
    python scripts/build_schema_description.py --check    # fail if stale

The hand-written file documented 7 of the 33 columns in
tms_business_object_flat. Since the prompt tells the model to use only the
columns it can see and never to invent one, an undocumented column is
unusable: asked to count rows with no workflow name, the model correctly
refused to guess and emitted `WHERE FALSE`. Under-documenting the schema is
therefore a correctness bug, not a saving.

Column names and types come from information_schema, so the file cannot drift
from the database. Descriptions come from three places, in order of trust:

  1. the existing schema_description.yaml, so hand-written wording survives
  2. TMS_Semantic_Registry_v2/table_registry.yaml, which was verified against
     this database column by column
  3. a generated fallback, flagged in the file so it is easy to find and improve

That also gives the registry a job in the pipeline rather than leaving it as
reference material that drifts.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401
import yaml

from config.logging import register_secrets
from config.settings import load_settings
from database.connection import run_readonly

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "metadata" / "schema_description.yaml"
REGISTRY = ROOT / "TMS_Semantic_Registry_v2 (1)" / "table_registry.yaml"

TABLES = [
    "tms_business_object_flat",
    "tms_business_object_attributes_flat",
    "tms_task_flat",
    "tms_user_flat",
    "tms_user_department_flat",
    "tms_role_flat",
]

PRIMARY_KEYS = {
    "tms_business_object_flat": "business_object_id",
    "tms_business_object_attributes_flat": "business_object_id",
    "tms_task_flat": "task_id",
    "tms_user_flat": "user_id",
    "tms_role_flat": "role_dept_id",
}

# Below this many distinct values a column is an enumeration, and listing the
# values is worth the tokens: without them the model has to guess which column
# a literal belongs to. Asked for "AR_NPD_YD_SHIRTING items for PVH" it read
# PVH as a buyer name -- reasonable, since PVH is an apparel group, and wrong,
# because here PVH is a business_unit. Naming the values settles it.
MAX_ENUM_VALUES = 12

SQL_TO_MDL = {
    "integer": "INTEGER", "bigint": "BIGINT", "smallint": "INTEGER",
    "character varying": "VARCHAR", "text": "VARCHAR", "boolean": "BOOLEAN",
    "double precision": "DOUBLE", "real": "REAL", "numeric": "DECIMAL",
    "timestamp with time zone": "TIMESTAMP", "timestamp without time zone": "TIMESTAMP",
    "date": "DATE",
}


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the file would change")
    args = ap.parse_args()

    settings = load_settings()
    register_secrets(settings.secrets())

    existing = _load_yaml(OUT)
    old_tables = existing.get("tables", {}) or {}
    reg_tables = (_load_yaml(REGISTRY).get("tables", {}) or {})

    res = run_readonly(settings, """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name LIKE 'tms_%'
        ORDER BY table_name, ordinal_position
    """, settings.statement_timeout_ms)
    if res.error:
        print(f"introspection failed: {res.error}")
        return 1

    live: dict[str, list[tuple[str, str]]] = {}
    for table, column, dtype in res.rows:
        live.setdefault(table, []).append((column, dtype))

    def enum_values(table: str, column: str, dtype: str) -> list[str] | None:
        """Distinct values, when there are few enough to be an enumeration."""
        if dtype not in ("character varying", "text"):
            return None
        q = (
            f'SELECT DISTINCT "{column}" FROM {table} '
            f"""WHERE "{column}" IS NOT NULL AND "{column}" <> '' """
            f"LIMIT {MAX_ENUM_VALUES + 1}"
        )
        r = run_readonly(settings, q, settings.statement_timeout_ms)
        if r.error or not r.rows or len(r.rows) > MAX_ENUM_VALUES:
            return None
        return sorted(str(row[0]) for row in r.rows)

    tables_doc: dict = {}
    generated = 0
    enumerated = [0]
    for table in TABLES:
        if table not in live:
            print(f"  skip {table}: not in database")
            continue
        old = old_tables.get(table, {}) or {}
        old_cols = old.get("columns", {}) or {}
        reg = reg_tables.get(table, {}) or {}
        reg_cols = reg.get("columns", {}) or {}

        cols: dict = {}
        for column, dtype in live[table]:
            prior = old_cols.get(column)
            if isinstance(prior, dict) and prior.get("description"):
                desc = prior["description"]
            elif reg_cols.get(column):
                desc = reg_cols[column]
            else:
                desc = f"{column.replace('_', ' ').capitalize()}."
                generated += 1
            entry_col = {"type": SQL_TO_MDL.get(dtype, "VARCHAR"), "description": desc}
            vals = enum_values(table, column, dtype)
            if vals:
                entry_col["values"] = vals
                enumerated[0] += 1
            cols[column] = entry_col

        entry: dict = {}
        entry["description"] = (
            old.get("description")
            or reg.get("description")
            or f"Flat TMS view {table}."
        )
        if table in PRIMARY_KEYS:
            entry["primary_key"] = PRIMARY_KEYS[table]
        entry["columns"] = cols
        tables_doc[table] = entry

    doc = {
        "data_source": existing.get("data_source", "postgres"),
        "catalog": existing.get("catalog", ""),
        "schema": existing.get("schema", "public"),
        "tables": tables_doc,
        "relationships": existing.get("relationships") or [
            {"name": "task_business_object",
             "from": "tms_task_flat.bo_id",
             "to": "tms_business_object_flat.business_object_id",
             "join_type": "MANY_TO_ONE",
             "description": "A task belongs to a Business Object."},
            {"name": "business_object_attributes",
             "from": "tms_business_object_attributes_flat.business_object_id",
             "to": "tms_business_object_flat.business_object_id",
             "join_type": "ONE_TO_ONE",
             "description": "Client-specific attributes for a business object."},
        ],
        "terminology": existing.get("terminology", {}),
        "ambiguities": existing.get("ambiguities", []),
    }

    header = (
        "# Generated by scripts/build_schema_description.py from the live database.\n"
        "# Column names and types come from information_schema and must not be edited\n"
        "# by hand. Descriptions ARE preserved across regeneration, so improving one\n"
        "# here is safe; run --check in CI to catch drift from the database.\n"
    )
    body = header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)

    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current.strip() != body.strip():
            print("schema_description.yaml is stale; re-run without --check")
            return 1
        print("schema_description.yaml is up to date")
        return 0

    OUT.write_text(body, encoding="utf-8")
    total = sum(len(t["columns"]) for t in tables_doc.values())
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"  {len(tables_doc)} tables, {total} columns "
          f"({generated} description(s) auto-generated, "
          f"{enumerated[0]} column(s) with enumerated values)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
