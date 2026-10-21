"""product.yaml, checked, and the views of it the pipeline reads.

The file describes the product in business terms: the things people ask
about (entities), what a click on one opens, who the user is, and the
product's words. This class turns that into the lists each module needs --
subject nouns, id columns, chips never offered, link targets -- so no module
knows a product fact of its own.

Built by pipeline.metadata.profile(), which refuses a file with problems().
The file and product.schema.json are byte-identical to the Drupal module's.

Ported from the Drupal module's ProductProfile; the problems are worded the
same, so either side's check reads the same.
"""

from __future__ import annotations

import json
import re

from pipeline import metadata


def _json(value) -> str:
    return json.dumps(value, separators=(",", ":"))


class ProductProfile:

    def __init__(self, product: dict):
        self.product = product if isinstance(product, dict) else {}

    # ------------------------------------------------------------ checking --

    def problems(self) -> list[str]:
        """Everything wrong with the file, one sentence each; empty when sound.

        First its shape, against product.schema.json beside it; then, if the
        shape holds, whether its tables, columns and rules exist.
        """
        problems: list[str] = []
        schema_path = metadata.META_DIR / "product.schema.json"
        if schema_path.is_file():
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            if isinstance(schema, dict):
                self._check_shape(self.product, schema, "product.yaml", problems)
        if not problems:
            self._check_meaning(problems)
        return problems

    def _check_shape(self, value, schema: dict, path: str, problems: list[str]) -> None:
        """The JSON Schema keywords product.schema.json uses, and no others."""
        kind = schema.get("type")
        # An empty YAML collection is either: PHP cannot tell [] from {}.
        is_map = isinstance(value, dict) or value == []
        is_list = isinstance(value, list) or value == {}
        ok = {
            "object": is_map,
            "array": is_list,
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
        }
        if kind is not None and not ok.get(kind):
            noun = {"object": "a set of keys", "array": "a list"}.get(kind, f"a {kind}")
            problems.append(f"{path} must be {noun}, not {_json(value)}.")
            return
        if "enum" in schema and value not in schema["enum"]:
            problems.append(f"{path} must be one of "
                            + ", ".join(_json(v) for v in schema["enum"]) + ".")
        if "pattern" in schema and isinstance(value, str) and not re.search(schema["pattern"], value):
            problems.append(f'{path} "{value}" is not in the right form.')
        if "minLength" in schema and isinstance(value, str) and len(value.strip()) < schema["minLength"]:
            problems.append(f"{path} must not be empty.")
        if "minItems" in schema and isinstance(value, list) and len(value) < schema["minItems"]:
            problems.append(f"{path} must list at least {schema['minItems']}.")
        if kind == "array" and "items" in schema:
            for i, item in enumerate(value or []):
                self._check_shape(item, schema["items"], f"{path}[{i}]", problems)
        if kind != "object":
            return
        value = value or {}
        for key in schema.get("required", []):
            if key not in value:
                problems.append(f'{path} needs "{key}".')
        properties = schema.get("properties", {})
        others = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in properties:
                self._check_shape(item, properties[key], f"{path}.{key}", problems)
            elif others is False:
                known = (" Known keys: " + ", ".join(properties) + ".") if properties else ""
                problems.append(f'{path} has an unknown key "{key}".{known}')
            elif isinstance(others, dict):
                self._check_shape(item, others, f"{path}.{key}", problems)

    def _check_meaning(self, problems: list[str]) -> None:
        """Whether the tables, columns and rules the file names exist."""
        tables = (metadata.schema().get("tables") or {})

        def columns_of(table) -> dict:
            return ((tables.get(table) or {}).get("columns") or {})

        def column_anywhere(column) -> bool:
            return any(column in columns_of(t) for t in tables)

        from pipeline.followup import _rule_predicates
        rules = {name for name, *_ in _rule_predicates()}

        kinds, colours = [], []
        for name, entity in self.entities().items():
            at = f"entities.{name}"
            table = entity.get("table")
            if table is not None and table not in tables:
                problems.append(f'{at}.table "{table}" is not in schema_description.yaml.')
                table = None
            for key in ("id", "title", "reference", "kind", "colour"):
                if key not in entity:
                    continue
                column = entity[key]
                found = column in columns_of(table) if table is not None else column_anywhere(column)
                if not found:
                    problems.append(f'{at}.{key} "{column}" is not a column of '
                                    + (table if table is not None else "any table") + ".")
            if "kind" in entity:
                kinds.append(name)
            if "colour" in entity:
                colours.append(name)
                if "table" not in entity or "id" not in entity:
                    problems.append(f"{at}.colour needs the entity's table and id, to look the colour up.")
            if "default_rule" in entity and entity["default_rule"] not in rules:
                problems.append(f'{at}.default_rule "{entity["default_rule"]}" is not a single '
                                "table.column = 'value' rule in business_rules.yaml.")
            if "open" in entity:
                opened = entity["open"] or {}
                if len([k for k in ("url", "download", "popup") if k in opened]) != 1:
                    problems.append(f"{at}.open needs exactly one of url, download or popup.")
                if ("url" in opened or "popup" in opened) and "id" not in entity:
                    problems.append(f"{at}.open needs the entity's id, the value it opens.")
                if "popup" in opened and "param" not in opened:
                    problems.append(f"{at}.open.popup needs param, the name the popup expects the id under.")
                if "download" in opened and not column_anywhere(opened["download"]):
                    problems.append(f'{at}.open.download "{opened["download"]}" is not a column of any table.')
                if "download" in opened and "button" in opened:
                    problems.append(f"{at}.open.button works with url or popup, not download.")
        if len(kinds) > 1:
            problems.append("Only one entity may have a kind; " + " and ".join(kinds) + " do.")
        if len(colours) > 1:
            problems.append("Only one entity may have a colour; " + " and ".join(colours) + " do.")

        for column in (self.product.get("columns") or {}):
            if not column_anywhere(column):
                problems.append(f"columns.{column} is not a column of any table.")

        users = self.users()
        if users:
            for at, block in (("users", users), ("users.departments", users.get("departments"))):
                if block is None:
                    continue
                if block["table"] not in tables:
                    problems.append(f'{at}.table "{block["table"]}" is not in schema_description.yaml.')
                    continue
                for key in ("id", "user_id", "name"):
                    if key in block and block[key] not in columns_of(block["table"]):
                        problems.append(f'{at}.{key} "{block[key]}" is not a column of {block["table"]}.')

    # -------------------------------------------------------------- views --

    def entities(self) -> dict:
        """Name -> entity block, in file order."""
        entities = self.product.get("entities")
        return entities if isinstance(entities, dict) else {}

    def subject_nouns(self) -> list[str]:
        """Every word that names a subject, from every entity, in file order."""
        return [str(word) for entity in self.entities().values()
                for word in (entity.get("words") or [])]

    def identifier_columns(self) -> list[str]:
        """Every column an entity names as its id, under any of its names."""
        out = []
        for entity in self.entities().values():
            if "id" in entity:
                out.append(str(entity["id"]))
            out.extend(str(alias) for alias in (entity.get("same_id_as") or []))
        return out

    def id_endings(self) -> list[str]:
        """The endings that make any column an id column."""
        return [str(e) for e in (self.product.get("id_column_endings") or [])]

    def record_name(self, column: str) -> str | None:
        """What to call the record an id column identifies, or None if no
        entity names that column. "initiative 123" whichever of its id
        columns named it."""
        column = str(column or "").lower()
        for name, entity in self.entities().items():
            ids = ([entity["id"]] if "id" in entity else []) + list(entity.get("same_id_as") or [])
            if column in ids:
                return str(name).replace("_", " ")
        return None

    def kind_column(self) -> str:
        """The column naming an entity's type, or '' when none has one."""
        for entity in self.entities().values():
            if "kind" in entity:
                return str(entity["kind"])
        return ""

    def not_groupable(self) -> list[str]:
        """Columns never offered as a grouping: the kind, and columns marked so."""
        out = [self.kind_column()] if self.kind_column() else []
        out.extend(str(column) for column, facts in (self.product.get("columns") or {}).items()
                   if (facts or {}).get("group", True) is False)
        return out

    def sort_by(self) -> list[str]:
        """Parts of column names worth sorting by, most interesting first."""
        return [str(s) for s in ((self.product.get("suggestions") or {}).get("sort_by") or [])]

    def default_rules(self) -> list[str]:
        """The rules applied when nobody asks otherwise."""
        return [str(e["default_rule"]) for e in self.entities().values() if "default_rule" in e]

    def heading_words(self) -> dict:
        """A word inside a column name -> how a heading writes it."""
        return dict((self.product.get("headings") or {}).get("words") or {})

    def heading_phrases(self) -> dict:
        """Part of a column name -> what it is replaced with first."""
        return dict((self.product.get("headings") or {}).get("phrases") or {})

    def units(self) -> dict:
        """Column -> the unit its name does not say."""
        return {str(column): str(facts["unit"])
                for column, facts in (self.product.get("columns") or {}).items()
                if "unit" in (facts or {})}

    def never_correct(self) -> list[str]:
        """Words the spelling repair must never change."""
        return [str(w) for w in ((self.product.get("spelling") or {}).get("never_correct") or [])]

    def colours(self) -> dict:
        """Name -> {code, hex}."""
        return dict(self.product.get("colours") or {})

    def colour_record(self) -> dict | None:
        """The entity whose colour each row carries, or None.

        id_columns, ref_columns and colour_columns are found in an answer by
        name; table, id and colour are where the colour is looked up otherwise.
        """
        for entity in self.entities().values():
            if "colour" not in entity:
                continue
            return {
                "id_columns": ([entity["id"]] if "id" in entity else []) + list(entity.get("same_id_as") or []),
                "ref_columns": [entity["reference"]] if "reference" in entity else [],
                "colour_columns": [entity["colour"]],
                "table": entity.get("table"),
                "id": entity.get("id"),
                "colour": entity["colour"],
            }
        return None

    def links(self) -> list[dict]:
        """What can be opened from an answer, one per entity with `open`.

        value_columns hold what is opened (the id, or a file's address);
        label_columns the readable cell clicked instead, when projected.
        """
        out = []
        for name, entity in self.entities().items():
            opened = entity.get("open")
            if not opened:
                continue
            out.append({
                "entity": name,
                "value_columns": [opened["download"]] if "download" in opened
                else ([entity["id"]] if "id" in entity else []) + list(entity.get("same_id_as") or []),
                "label_columns": [entity["title"]] if "title" in entity else [],
                "open": opened,
            })
        return out

    def users(self) -> dict:
        """The users block: table, id, name and optionally departments; {} if none."""
        return dict(self.product.get("users") or {})

    def message(self, key: str) -> str:
        """One of the product's words in the error messages; '' when absent."""
        return str((self.product.get("messages") or {}).get(key) or "")

    def welcome(self) -> dict:
        """The line under the greeting, and the starter questions."""
        welcome = self.product.get("welcome") or {}
        return {"text": str(welcome.get("text") or ""),
                "starters": list(welcome.get("starters") or [])}

    def prompt_word(self, key: str) -> str:
        """One of the product's words in the system prompt; '' when absent."""
        return str((self.product.get("prompt") or {}).get(key) or "")
