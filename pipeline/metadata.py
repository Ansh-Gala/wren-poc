"""The metadata/*.yaml files, plus what a site adds to them.

The five files in metadata/ are the common ones. They stay byte-identical to
the Drupal module's copies, and the parity harness compares the prompt built
from them byte for byte.

A site adds what is its own -- today the Arvind site's Initiative attributes
-- from metadata/site/. The Drupal site module does the same through
hook_vf_sql_chatbot_schema_alter(), _rules_alter() and
_column_hierarchy_alter(); the merges below are those three hooks.

The site files count only after enable_site_metadata(). The server and the
suite runners call it at startup. The parity harness does not, so it compares
the common files only, as check.php does with no module handler.

Ported from the Drupal module's Metadata service.
"""

from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path

import yaml

META_DIR = Path(__file__).resolve().parents[1] / "metadata"
SITE_DIR = META_DIR / "site"

_site_dir: Path | None = None


def enable_site_metadata(directory: Path = SITE_DIR) -> None:
    """Merge a site's metadata into every later read.

    Call it at startup, before the first question. Every reader caches what
    it derives from these documents, so a reader that has already run would
    keep answering from the common files alone.
    """
    global _site_dir
    _site_dir = Path(directory)
    _parsed.cache_clear()


def document(name: str) -> dict:
    """One common metadata file, parsed. A missing file reads as empty."""
    path = META_DIR / name
    return copy.deepcopy(_parsed(path)) if path.is_file() else {}


def schema() -> dict:
    """schema_description.yaml, plus the site's tables and relationships."""
    doc = document("schema_description.yaml")
    if _site_dir is not None:
        site = _site("attributes_schema_description.yaml")
        doc["tables"] = {**(doc.get("tables") or {}), **(site.get("tables") or {})}
        doc["relationships"] = [*(doc.get("relationships") or []),
                                *(site.get("relationships") or [])]
    return doc


def rules() -> dict:
    """business_rules.yaml, plus the site's rules."""
    doc = document("business_rules.yaml")
    if _site_dir is not None:
        site = _site("attributes_business_rules.yaml")
        doc["rules"] = [*(doc.get("rules") or []), *(site.get("rules") or [])]
    return doc


def column_hierarchy() -> dict:
    """column_hierarchy.yaml, plus the site's tables."""
    doc = document("column_hierarchy.yaml")
    if _site_dir is not None:
        site = _site("attributes_column_hierarchy.yaml")
        doc["tables"] = {**(doc.get("tables") or {}), **(site.get("tables") or {})}
    return doc


def pairs() -> dict:
    """question_sql_pairs.yaml. A site adds no examples."""
    return document("question_sql_pairs.yaml")


def _site(name: str) -> dict:
    """One of the site's files. Missing is an error, as it is in Drupal: a
    site that says it has metadata and has none should not answer quietly
    from the common files."""
    return copy.deepcopy(_parsed(_site_dir / name))


@lru_cache(maxsize=None)
def _parsed(path: Path) -> dict:
    """A YAML file, parsed once. Callers get copies, never this object."""
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
