"""A site's metadata, merged the way the Drupal site module merges it."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from pipeline import metadata

_ROOT = Path(__file__).resolve().parents[1]
_COMMON = ("business_rules.yaml", "schema_description.yaml", "question_sql_pairs.yaml",
           "column_hierarchy.yaml", "entity_gazetteer.yaml")
_SITE = ("attributes_schema_description.yaml", "attributes_business_rules.yaml",
         "attributes_column_hierarchy.yaml")


@pytest.fixture(autouse=True)
def common_files_only(monkeypatch):
    """Every test starts with no site enabled, and leaves none behind."""
    monkeypatch.setattr(metadata, "_site_dir", None)
    metadata._parsed.cache_clear()
    yield
    metadata._parsed.cache_clear()


def _yaml(name: str) -> dict:
    return yaml.safe_load((_ROOT / "metadata" / name).read_text(encoding="utf-8")) or {}


def _site(tmp_path: Path, **docs: dict) -> Path:
    """A site folder holding the three files, empty unless given."""
    for name in _SITE:
        key = name.removesuffix(".yaml")
        (tmp_path / name).write_text(yaml.safe_dump(docs.get(key, {})), encoding="utf-8")
    return tmp_path


def test_without_a_site_the_common_files_are_read_as_they_are():
    assert metadata.schema() == _yaml("schema_description.yaml")
    assert metadata.rules() == _yaml("business_rules.yaml")
    assert metadata.column_hierarchy() == _yaml("column_hierarchy.yaml")
    assert metadata.pairs() == _yaml("question_sql_pairs.yaml")


def test_the_attributes_table_arrives_only_with_the_site():
    assert "tms_initiative_attributes_flat" not in metadata.schema()["tables"]

    metadata.enable_site_metadata()

    tables = list(metadata.schema()["tables"])
    assert tables[-1] == "tms_initiative_attributes_flat"
    assert tables[:-1] == list(_yaml("schema_description.yaml")["tables"]), (
        "the common tables keep their order; the site's come after them")
    assert "tms_initiative_attributes_flat" in metadata.column_hierarchy()["tables"]


def test_a_site_table_with_a_common_name_replaces_it_in_place(tmp_path):
    """PHP array_merge on string keys: the later value wins, the first place stays."""
    common = list(_yaml("schema_description.yaml")["tables"])
    replaced = common[1]
    metadata.enable_site_metadata(_site(tmp_path, attributes_schema_description={
        "tables": {replaced: {"description": "the site's own"}, "site_only": {}},
    }))

    tables = metadata.schema()["tables"]
    assert list(tables) == common + ["site_only"]
    assert tables[replaced] == {"description": "the site's own"}


def test_relationships_and_rules_are_appended(tmp_path):
    metadata.enable_site_metadata(_site(
        tmp_path,
        attributes_schema_description={"relationships": [{"name": "site_join"}]},
        attributes_business_rules={"rules": [{"name": "site_rule"}]},
    ))

    relationships = metadata.schema()["relationships"]
    rules = metadata.rules()["rules"]
    assert relationships[:-1] == _yaml("schema_description.yaml")["relationships"]
    assert relationships[-1] == {"name": "site_join"}
    assert rules[:-1] == _yaml("business_rules.yaml")["rules"]
    assert rules[-1] == {"name": "site_rule"}


def test_a_site_adds_no_examples():
    metadata.enable_site_metadata()
    assert metadata.pairs() == _yaml("question_sql_pairs.yaml")


def test_a_missing_site_file_is_an_error(tmp_path):
    """Drupal fatals on it. Answering from the common files alone would be
    a quieter way to be wrong."""
    metadata.enable_site_metadata(tmp_path)
    with pytest.raises(FileNotFoundError):
        metadata.schema()


def test_callers_get_copies():
    metadata.schema()["tables"].clear()
    assert metadata.schema()["tables"], "one caller's change must not reach the next"


def _drupal_metadata() -> tuple[Path, Path] | None:
    """The module's metadata/ and the site module's, or None on a machine
    without Drupal (VF_MODULE_ROOT overrides the default path)."""
    env = os.environ.get("VF_MODULE_ROOT")
    module = Path(env) if env else Path(
        "C:/xampp/htdocs/dev-arvind-retail-chatbot/web/modules/custom/vf_sql_chatbot")
    site = (module.parents[2] / "sites" / "site-arvind-retail" / "modules" / "custom"
            / "vf_arvind_retail_chatbot")
    if not (module / "metadata").is_dir() or not (site / "metadata").is_dir():
        return None
    return module / "metadata", site / "metadata"


@pytest.mark.parametrize("name", _COMMON)
def test_the_common_files_are_byte_identical_to_drupal(name):
    found = _drupal_metadata()
    if found is None:
        pytest.skip("Drupal module not present; set VF_MODULE_ROOT to check")
    ours, theirs = _ROOT / "metadata" / name, found[0] / name
    assert ours.read_bytes() == theirs.read_bytes(), (
        f"{name} has drifted from Drupal; copy it across, do not retype it")


@pytest.mark.parametrize("name", _SITE)
def test_the_site_files_are_byte_identical_to_drupal(name):
    found = _drupal_metadata()
    if found is None:
        pytest.skip("Drupal site module not present; set VF_MODULE_ROOT to check")
    ours, theirs = _ROOT / "metadata" / "site" / name, found[1] / name
    assert ours.read_bytes() == theirs.read_bytes(), (
        f"site/{name} has drifted from the Drupal site module; copy it across")
