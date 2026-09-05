"""Build the four knowledge configurations as separate Wren projects.

    A  raw schema only          - no descriptions, no rules, no exemplars
    B  + column descriptions
    C  + business rules
    D  + confirmed NL-SQL exemplars in query memory

Each is a self-contained Wren project directory selected at run time through
WREN_PROJECT_HOME, so a benchmark run cannot accidentally see knowledge from a
different configuration.

This module writes *semantic metadata* only. It never decides how a question
should become SQL -- that remains entirely Wren's and Claude's job.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from config.logging import get_logger
from config.settings import Settings
from wren_setup.helpers import run_wren

ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / "metadata"

log = get_logger("wren.build")

# Which knowledge each configuration receives.
CONFIG_FEATURES = {
    "A": {"descriptions": False, "rules": False, "exemplars": False},
    "B": {"descriptions": True, "rules": False, "exemplars": False},
    "C": {"descriptions": True, "rules": True, "exemplars": False},
    "D": {"descriptions": True, "rules": True, "exemplars": True},
}


def write_connection_profile(settings: Settings) -> Path:
    """Write $WREN_HOME/profiles.yml.

    Wren needs a connection profile even in strict mode: without one,
    `wren serve mcp --no-connect` exits with "'datasource' key not found in
    connection info" because it still has to know the SQL dialect. The profile
    carries the SELECT-only role, never the owner account, so a connected run
    cannot write either.
    """
    settings.wren_home.mkdir(parents=True, exist_ok=True)
    profile = {
        "active": "wren_poc",
        "profiles": {
            "wren_poc": {
                "datasource": "postgres",
                "host": settings.pg_host,
                "port": settings.pg_port,
                "database": settings.pg_database,
                "user": settings.pg_readonly_user,
                "password": settings.pg_readonly_password,
            }
        },
    }
    path = settings.wren_home / "profiles.yml"
    path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    log.info("wrote connection profile %s (role %s)", path, settings.pg_readonly_user)
    return path


def load_metadata() -> tuple[dict, dict]:
    schema = yaml.safe_load((METADATA / "schema_description.yaml").read_text(encoding="utf-8"))
    rules = yaml.safe_load((METADATA / "business_rules.yaml").read_text(encoding="utf-8"))
    return schema, rules


def _model_metadata(table: str, tdef: dict, schema_name: str, with_descriptions: bool) -> dict:
    """One models/<table>/metadata.yml document.

    Descriptions live at properties.description; configuration A leaves
    properties empty, which is what makes it a genuine schema-only baseline.
    """
    columns = []
    for col_name, col in tdef["columns"].items():
        entry = {
            "name": col_name,
            "type": col["type"],
            "is_calculated": False,
            "not_null": col_name == tdef.get("primary_key"),
            "properties": (
                {"description": " ".join(col["description"].split())}
                if with_descriptions
                else {}
            ),
        }
        if col_name == tdef.get("primary_key"):
            entry["is_primary_key"] = True
        columns.append(entry)

    return {
        "name": table,
        "table_reference": {"catalog": "", "schema": schema_name, "table": table},
        "columns": columns,
        "primary_key": tdef.get("primary_key", "id"),
        "cached": False,
        "properties": (
            {"description": " ".join(tdef["description"].split())}
            if with_descriptions
            else {}
        ),
    }


def _relationships(schema: dict, with_descriptions: bool) -> dict:
    rels = []
    for rel in schema["relationships"]:
        from_model, from_col = rel["from"].split(".")
        to_model, to_col = rel["to"].split(".")
        entry = {
            "name": rel["name"],
            "models": [from_model, to_model],
            "join_type": rel["join_type"],
            "condition": f"{from_model}.{from_col} = {to_model}.{to_col}",
        }
        if with_descriptions:
            entry["properties"] = {"description": " ".join(rel["description"].split())}
        rels.append(entry)
    return {"relationships": rels}


def _write_rules(project: Path, rules: dict, schema: dict) -> None:
    """knowledge/rules/, knowledge/glossary/ and knowledge/caveats/."""
    rules_dir = project / "knowledge" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Business rules",
        "",
        "Rules that determine how business language maps onto this schema.",
        "Apply them when interpreting a question.",
        "",
    ]
    for rule in rules["rules"]:
        lines += [
            f"## {rule['name'].replace('_', ' ')}",
            "",
            " ".join(rule["definition"].split()),
            "",
            "```sql",
            rule["sql_fragment"].strip(),
            "```",
            "",
        ]
    (rules_dir / "general.md").write_text("\n".join(lines), encoding="utf-8")

    glossary_dir = project / "knowledge" / "glossary"
    glossary_dir.mkdir(parents=True, exist_ok=True)
    gloss = ["# Terminology", ""]
    for term, meaning in schema.get("terminology", {}).items():
        gloss.append(f"- **{term}** - {' '.join(meaning.split())}")
    (glossary_dir / "terms.md").write_text("\n".join(gloss) + "\n", encoding="utf-8")

    caveats_dir = project / "knowledge" / "caveats"
    caveats_dir.mkdir(parents=True, exist_ok=True)
    cav = ["# Caveats and ambiguities", ""]
    for item in schema.get("ambiguities", []):
        cav += [f"## {item['subject']}", "", " ".join(item["note"].split()), ""]
    (caveats_dir / "ambiguities.md").write_text("\n".join(cav), encoding="utf-8")


def build_config(config_name: str, settings: Settings) -> Path:
    config_name = config_name.upper()
    features = CONFIG_FEATURES[config_name]
    schema, rules = load_metadata()
    project = settings.project_dir(config_name)

    if project.exists():
        shutil.rmtree(project)
    project.mkdir(parents=True, exist_ok=True)

    log.info("config %s: scaffolding %s", config_name, project)
    run_wren(["context", "init", "--path", str(project), "--empty", "--force"],
             settings, project)

    # `--empty` still leaves the example view behind in 0.13.4; remove it so
    # the model list is exactly our three tables.
    for stale in (project / "views" / "example_view", project / "models" / "example"):
        if stale.exists():
            shutil.rmtree(stale)

    project_yml = project / "wren_project.yml"
    doc = yaml.safe_load(project_yml.read_text(encoding="utf-8"))
    doc["name"] = f"wren_poc_{config_name.lower()}"
    doc["data_source"] = schema["data_source"]
    doc["schema"] = "public"
    project_yml.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    for table, tdef in schema["tables"].items():
        model_dir = project / "models" / table
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "metadata.yml").write_text(
            yaml.safe_dump(
                _model_metadata(table, tdef, schema["schema"], features["descriptions"]),
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )

    (project / "relationships.yml").write_text(
        yaml.safe_dump(_relationships(schema, features["descriptions"]),
                       sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    # Configurations A and B get no business rules at all: the scaffolded
    # placeholder must go, or A would ship a stray rules file.
    placeholder = project / "knowledge" / "rules" / "general.md"
    if features["rules"]:
        _write_rules(project, rules, schema)
    elif placeholder.exists():
        placeholder.unlink()

    log.info("config %s: building mdl.json", config_name)
    run_wren(["context", "build", "--path", str(project)], settings, project)
    return project


def index_schema(config_name: str, settings: Settings) -> None:
    """Build the embedding index that get_context searches.

    Without it get_context has nothing to rank against and falls back to
    returning the entire schema description (1632 tokens on 3 tables), which
    is exactly the whole-schema cost the semantic layer is meant to avoid.

    --no-seed and --no-queries keep the A/B/C/D comparison honest: only
    configuration D is supposed to carry NL-SQL exemplars, and those arrive
    through load_exemplars. Indexing must add schema knowledge, not examples.
    """
    memory_dir = settings.memory_dir(config_name)
    memory_dir.mkdir(parents=True, exist_ok=True)
    run_wren(
        ["memory", "index", "--path", str(memory_dir), "--no-seed", "--no-queries"],
        settings,
        settings.project_dir(config_name),
        timeout=900,
        WREN_MEMORY_DIR=str(memory_dir),
        WREN_MEMORY_BACKEND=settings.wren_memory_backend,
    )


def load_exemplars(config_name: str, settings: Settings) -> int:
    """Load NL-SQL pairs into this configuration's query memory."""
    memory_dir = settings.memory_dir(config_name)
    if memory_dir.exists():
        shutil.rmtree(memory_dir)
    memory_dir.mkdir(parents=True, exist_ok=True)

    pairs_file = METADATA / "question_sql_pairs.yaml"
    pairs = yaml.safe_load(pairs_file.read_text(encoding="utf-8"))["pairs"]

    # Written as knowledge/sql/*.md, which wrenai documents as the source of
    # truth for NL->SQL memory and which the grep recall backend reads
    # directly. The MCP server uses grep because lancedb recall loads
    # sentence-transformers inside the stdio server and hangs; see
    # wren_setup/mcp_config.py.
    from wren.memory.markdown import write_query_markdown  # noqa: PLC0415

    project = settings.project_dir(config_name)
    sql_dir = project / "knowledge" / "sql"
    for stale in sql_dir.glob("*.md"):
        stale.unlink()
    for pair in pairs:
        write_query_markdown(
            project,
            pair["nl"],
            pair["sql"],
            datasource=pair.get("datasource"),
            tags=list(pair.get("tags") or []),
            source="poc",
        )
    log.info("config %s: wrote %d exemplar(s) to knowledge/sql", config_name, len(pairs))
    return len(pairs)


def validate_config(config_name: str, settings: Settings, level: str = "warning") -> str:
    proc = run_wren(
        ["context", "validate", "--path", str(settings.project_dir(config_name)),
         "--level", level],
        settings,
        settings.project_dir(config_name),
        check=False,
    )
    return (proc.stdout + proc.stderr).strip()


def build_all(settings: Settings) -> dict[str, dict]:
    settings.wren_project_root.mkdir(parents=True, exist_ok=True)
    settings.wren_home.mkdir(parents=True, exist_ok=True)

    summary: dict[str, dict] = {}
    for name, features in CONFIG_FEATURES.items():
        build_config(name, settings)
        exemplars = load_exemplars(name, settings) if features["exemplars"] else 0
        index_schema(name, settings)
        summary[name] = {
            "path": str(settings.project_dir(name)),
            "descriptions": features["descriptions"],
            "rules": features["rules"],
            "exemplars": exemplars,
        }
    return summary
