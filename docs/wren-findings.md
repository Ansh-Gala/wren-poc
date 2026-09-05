# Verified Wren AI behaviour (wrenai 0.13.4, Windows)

Everything here was confirmed by running the CLI or reading the installed
package, not from documentation. Recorded because several points contradict
what the public docs imply, and the implementation depends on them.

## Which Wren MCP server this project uses

`Canner/WrenAI-mcp` is a **cloud/Enterprise** connector: it authenticates via
OAuth against `https://cloud.getwren.ai/api/mcp`. It cannot satisfy the
no-Docker or the data-privacy requirements of this POC and is **not used**.

This project uses the Apache-2.0 MCP server built into the `wrenai` PyPI
package: `pip install 'wrenai[postgres,mcp,memory]'` → `wren serve mcp`.

## Project layout created by `wren context init`

```
wren_project.yml            schema_version, catalog, schema, data_source
models/<name>/metadata.yml  one directory per model
views/<name>/metadata.yml   + sql.yml
relationships.yml           joins between models
knowledge/knowledge.yml     schema_version
knowledge/rules/            business rules for LLM query generation  (section 11)
knowledge/glossary/         terminology                              (section 10)
knowledge/caveats/          ambiguities and gotchas                  (section 10)
knowledge/metrics/          named metric definitions
knowledge/sql/              confirmed NL-SQL pairs                   (section 12)
AGENTS.md                   agent workflow guidance
```

This is richer than the flat `instructions.md` the docs describe;
`wren context instructions` reads `knowledge/rules/` and treats
`instructions.md` as legacy. The design's four knowledge configurations map
onto these directories directly.

## Descriptions live at `properties.description`

On models, columns and views:

```yaml
columns:
  - name: status
    type: VARCHAR
    properties:
      description: "Current availability of the user in the workflow system..."
```

`wren context validate --level strict` reports every column missing one. This
is what makes configuration A ("schema only") a genuine baseline: the raw model
YAML carries `properties: {}` and the database has no `COMMENT ON` statements,
so no description can leak into A by accident.

## There is no database-introspection command

`wren context import` accepts **dbt only** in 0.13.4. There is no
`introspect`/`import postgres` subcommand. Model YAML is therefore authored
from `metadata/schema_description.yaml` by `wren_setup/build.py`.

This does not conflict with the "no custom planner" rule: the build step emits
*semantic metadata*, and Wren remains solely responsible for turning a question
into SQL.

## MCP tools, and the privacy gate

`wren/mcp_server.py` registers row-returning tools behind a flag:

```python
def _register_query_tools(mcp, ctx):
    if not ctx.no_connect:
        @mcp.tool() def run_sql(...)     # returns rows
        @mcp.tool() def dry_run(...)     # returns {"ok": true}
        @mcp.tool() def query_cube(...)  # returns rows
    @mcp.tool() def dry_plan(...)        # outside the gate; no DB connection
```

With `wren serve mcp --no-connect`, `run_sql` and `query_cube` are never
registered and Wren opens no database connection at all
(`conn_required=not no_connect` in `serve_cli.py`). `dry_plan` still expands
MDL SQL into PostgreSQL dialect without touching the database.

Full tool list: `get_mdl`, `list_models`, `describe_model`, `describe_schema`,
`get_data_source`, `list_functions`, `list_cubes`, `describe_cube`,
`get_instructions`, `recall_queries`, `get_context`, `list_stored_queries`,
`list_knowledge`, `dry_plan`, and — only when connected — `dry_run`, `run_sql`,
`query_cube`. `store_query` appears only with `--allow-write`, which this
project never passes.

Resources: `wren://mdl`, `wren://instructions`, `wren://project`,
`wren://agents`, `wren://knowledge/{path}`. Prompt: `wren_workflow`.

## Windows: `PYTHONUTF8=1` is required

`wren context init` crashes on Windows with `UnicodeEncodeError` because
`context_cli.py:359` writes `AGENTS.md` without an explicit encoding, and the
template contains non-ASCII characters that cp1252 cannot encode:

```python
(project_path / "AGENTS.md").write_text(_AGENTS_MD_TEMPLATE)   # no encoding=
```

This is an upstream bug in wrenai 0.13.4, not a configuration problem. Setting
`PYTHONUTF8=1` in the environment makes Python's default encoding UTF-8 and the
command succeeds. Every `wren` subprocess this project spawns — including the
MCP server launched by Claude Code — sets it.

## Memory backend

`wren memory` is described by its own help text as "backed by LanceDB".
`WREN_MEMORY_BACKEND=grep|lancedb` selects the backend; `lancedb` silently
downgrades to `grep` when the `memory` extra is absent, so
`wren_setup/build.py` asserts the resolved backend after loading rather than
trusting the request.
