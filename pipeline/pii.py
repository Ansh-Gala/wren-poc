"""Personal data stays on this side of the LLM.

A name, email or place in a question is replaced with an alias -- PERSON_001,
EMAIL_001, LOCATION_001 -- before anything reads the question, so the whole
pipeline, the state it keeps and every prompt it builds hold aliases only. The
real values come back at three edges and nowhere else: in the SQL, just before
it runs; in the prose, just before it is shown; and in a reopened chat.

The design, the alternatives and why they lost: docs/pii-aliasing-design.md.

Four pieces:

  PiiVault     one chat's aliases. Rebuilt from the chat database every turn,
               never kept between turns, so it cannot disagree with it.
  Anonymizer   GLiNER 2.5 small, plus fixed word lists, deciding what is
               personal. Shared by every request.
  restore_sql  aliases back into string literals, and only there. Anything
               else is refused rather than guessed at.
  mask_known   the tripwire: a known value found in an outgoing prompt is
               replaced with its alias, and counted.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from sqlglot.dialects.postgres import Postgres
from sqlglot.tokens import TokenType

from config.logging import get_logger

log = get_logger("pii")

CONFIG_FILE = Path(__file__).resolve().parents[1] / "config" / "pii_entities.json"

# Several labels share a prefix, so a value keeps one alias whichever way the
# model labels it: "Mumbai" found as a city once and as an address later is
# still LOCATION_001.
PREFIXES = {
    "person": "PERSON",
    "email": "EMAIL",
    "phone number": "PHONE",
    "age": "AGE",
    "location": "LOCATION",
    "address": "LOCATION",
    "city": "LOCATION",
    "country": "LOCATION",
    "company name": "COMPANY",
    "vendor name": "VENDOR",
}
DEFAULT_PREFIXES = frozenset(PREFIXES.values())

# Every prefix an alias can have in this process: the defaults, and any a
# configured label adds. Read by redact, so that an alias -- snake_case in
# shape -- is not taken for a column name and its sentence dropped.
_known_prefixes: set[str] = set(DEFAULT_PREFIXES)

# Told to the model whenever a prompt carries an alias. In the per-turn block,
# not the system prompt: that one is compared byte for byte with the PHP port.
PLACEHOLDER_NOTE = (
    "PLACEHOLDERS\n"
    "  Words such as PERSON_001 or LOCATION_002 stand for real values the user gave,\n"
    "  which you are not shown. Wherever the real value would go, write the\n"
    "  placeholder exactly as it appears, inside a single-quoted string literal:\n"
    "  assigned_user_name = 'PERSON_001'. Never split, shorten, translate or change\n"
    "  the case of one, never use one as a column or table name, and never make up\n"
    "  a new one. Write them the same way in explanation, recap, goal and next.\n\n"
)


class PiiError(Exception):
    """A turn that cannot keep its values private, so must not run."""


class VaultCorrupt(PiiError):
    """The stored aliases contradict each other."""


class AliasRefused(PiiError):
    """SQL whose aliases cannot be restored safely. The message names aliases
    only, never a value, so it can go back to the model in a repair."""


def prefix_for(label: str) -> str:
    key = " ".join(str(label).split()).lower()
    return PREFIXES.get(key) or re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").upper() or "ENTITY"


def match_key(value: str) -> str:
    """What makes two spellings one value: case and spacing do not count."""
    return " ".join(str(value).split()).casefold()


def alias_pattern(prefixes: Iterable[str]) -> re.Pattern:
    """Aliases with these prefixes, as whole tokens.

    Only our own prefixes: a stored value such as WF_001 has the same shape as
    an alias and must not be read as one.
    """
    return _compiled(frozenset(prefixes))


@lru_cache(maxsize=64)
def _compiled(prefixes: frozenset) -> re.Pattern:
    names = sorted(prefixes, key=len, reverse=True)
    return re.compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(map(re.escape, names))
                      + r")_\d{3,}(?![A-Za-z0-9_])")


def without_aliases(text: str) -> str:
    """`text` with every alias taken out."""
    return alias_pattern(_known_prefixes).sub(" ", text)


# ------------------------------------------------------------------ vault --

class PiiVault:
    """One chat's aliases: which value each stands for, and which are new.

    Numbers come from the aliases already here -- the highest for the prefix,
    plus one -- never from a counter, so nothing can fall out of step with
    what is stored. A vault built from an empty list for a chat that has
    aliases would start again at 001; callers refuse the turn instead.
    """

    def __init__(self) -> None:
        self._by_key: dict[str, dict] = {}
        self._by_alias: dict[str, dict] = {}
        # What this turn added, in the shape stored in the turn's metadata.
        self.new: list[dict] = []

    @classmethod
    def from_entries(cls, entries: Iterable) -> "PiiVault":
        vault = cls()
        for item in entries:
            try:
                entry = {"alias": str(item["alias"]), "label": str(item["label"]),
                         "original": str(item["original"])}
            except (KeyError, TypeError):
                raise VaultCorrupt("a stored alias is malformed") from None
            vault._add(entry, new=False)
        return vault

    def _add(self, entry: dict, new: bool) -> None:
        key = match_key(entry["original"])
        known = self._by_alias.get(entry["alias"])
        if known is not None and match_key(known["original"]) != key:
            raise VaultCorrupt(f"{entry['alias']} stands for two different values")
        same = self._by_key.get(key)
        if same is not None and same["alias"] != entry["alias"]:
            raise VaultCorrupt(f"one value has two aliases: {same['alias']}, {entry['alias']}")
        if known is not None:
            return
        self._by_key[key] = entry
        self._by_alias[entry["alias"]] = entry
        if new:
            self.new.append(entry)

    def alias_for(self, label: str, value: str) -> str:
        value = str(value).strip()
        known = self._by_key.get(match_key(value))
        if known is not None:
            return known["alias"]
        prefix = prefix_for(label)
        numbers = [int(alias[len(prefix) + 1:]) for alias in self._by_alias
                   if alias.startswith(prefix + "_") and alias[len(prefix) + 1:].isdigit()]
        alias = f"{prefix}_{max(numbers, default=0) + 1:03d}"
        self._add({"alias": alias, "label": str(label), "original": value}, new=True)
        return alias

    def original(self, alias: str) -> str | None:
        entry = self._by_alias.get(alias)
        return None if entry is None else entry["original"]

    def entries(self) -> list[dict]:
        return list(self._by_alias.values())

    def prefixes(self) -> set[str]:
        return {alias.rsplit("_", 1)[0] for alias in self._by_alias}

    @property
    def empty(self) -> bool:
        return not self._by_alias


def stored_aliases(metadata_values: Iterable) -> list[dict]:
    """Every alias a chat's turns introduced, oldest first, from their
    metadata (a dict, its JSON text, or the pii.new_aliases list itself)."""
    out: list[dict] = []
    for value in metadata_values:
        if isinstance(value, str):
            try:
                value = json.loads(value or "null")
            except ValueError:
                continue
        if isinstance(value, dict):
            value = (value.get("pii") or {}).get("new_aliases")
        if isinstance(value, list):
            out.extend(item for item in value if isinstance(item, dict))
    return out


# ------------------------------------------------------- text both ways --

def restore_text(text, vault: PiiVault, prefixes: Iterable[str] = ()):
    """Real values back into prose. An alias the vault does not know stays."""
    if not isinstance(text, str) or vault.empty:
        return text
    pattern = alias_pattern(DEFAULT_PREFIXES | vault.prefixes() | set(prefixes))
    return pattern.sub(lambda m: vault.original(m.group(0)) or m.group(0), text)


# Keys of a response whose text stays as the model wrote it: the SQL is shown
# to a developer as generated, and refs and ids are not prose.
_KEEP_ALIASES = frozenset({"generated_sql", "previous_sql", "raw_output", "chart_sql",
                           "ref", "id"})


def restore_deep(value, vault: PiiVault, prefixes: Iterable[str] = ()):
    """restore_text through a response's dicts and lists."""
    if vault.empty:
        return value
    if isinstance(value, str):
        return restore_text(value, vault, prefixes)
    if isinstance(value, list):
        return [restore_deep(v, vault, prefixes) for v in value]
    if isinstance(value, dict):
        return {k: v if k in _KEEP_ALIASES else restore_deep(v, vault, prefixes)
                for k, v in value.items()}
    return value


def mask_known(text: str, vault: PiiVault) -> tuple[str, int]:
    """Every value the vault knows, replaced in `text` by its alias.

    The tripwire before a prompt leaves: it catches a value that came back in
    by another route -- a database error quoting it, a recap written before
    aliasing. Plain matching, no model, so it only knows what it has seen.
    """
    if not text or vault.empty:
        return text, 0
    entries = sorted(vault.entries(), key=lambda e: len(e["original"]), reverse=True)
    parts = [r"\s+".join(map(re.escape, e["original"].split())) for e in entries
             if e["original"].strip()]
    if not parts:
        return text, 0
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)
    by_key = {match_key(e["original"]): e["alias"] for e in entries}
    return pattern.subn(lambda m: by_key.get(match_key(m.group(0)), m.group(0)), text)


# ------------------------------------------------------------------- SQL --

_LIKE = frozenset({TokenType.LIKE, TokenType.ILIKE})


def _like_escape(value: str) -> str:
    """A value made literal inside a LIKE pattern: PostgreSQL's default escape
    is the backslash, and standard_conforming_strings keeps it one character."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _tokens(sql: str):
    try:
        return Postgres().tokenize(sql)
    except Exception:
        raise AliasRefused("the query could not be read") from None


def restore_sql(sql: str, vault: PiiVault, prefixes: Iterable[str] = ()) -> str:
    """The query with its aliases replaced by the real values, ready to run.

    Only inside single-quoted string literals, spliced in place: the rest of
    the statement is left byte for byte as the gates passed it. Refused, never
    guessed at, when an alias is anywhere else, when the vault does not know
    it, or when the result does not tokenize exactly as the original did.
    """
    known = DEFAULT_PREFIXES | vault.prefixes() | set(prefixes)
    pattern = alias_pattern(known)
    if not pattern.search(sql):
        return sql
    tokens = _tokens(sql)
    edits: list[tuple[int, int, int, str]] = []
    for i, tok in enumerate(tokens):
        found = pattern.findall(tok.text)
        if not found:
            continue
        raw = sql[tok.start:tok.end + 1]
        if tok.token_type is not TokenType.STRING or not raw.startswith("'"):
            raise AliasRefused(f"{found[0]} must appear only inside a single-quoted string "
                               "literal, never as a name or bare word")
        unknown = [a for a in found if vault.original(a) is None]
        if unknown:
            raise AliasRefused(f"{unknown[0]} is not one of the placeholders in this "
                               "conversation; use only the ones given")
        like = i > 0 and tokens[i - 1].token_type in _LIKE
        if like and i + 1 < len(tokens) and tokens[i + 1].token_type is TokenType.ESCAPE:
            raise AliasRefused("a placeholder cannot be used in a LIKE pattern that "
                               "names its own ESCAPE character")
        value = pattern.sub(lambda m: _like_escape(vault.original(m.group(0))) if like
                            else vault.original(m.group(0)), tok.text)
        edits.append((i, tok.start, tok.end + 1, "'" + value.replace("'", "''") + "'"))

    restored = sql
    for _, start, end, literal in reversed(edits):
        restored = restored[:start] + literal + restored[end:]
    _verify(tokens, restored, edits)
    return restored


def _verify(before, restored: str, edits) -> None:
    """A value cannot change the statement's shape: same tokens, in the same
    order, each edited literal still exactly one string, still read-only."""
    from pipeline.safety import UnsafeSQLError, assert_read_only

    after = _tokens(restored)
    if [t.token_type for t in after] != [t.token_type for t in before]:
        raise AliasRefused("restoring the placeholders changed the query's structure")
    for i, _, _, literal in edits:
        tok = after[i]
        if restored[tok.start:tok.end + 1] != literal:
            raise AliasRefused("restoring the placeholders changed the query's structure")
    try:
        assert_read_only(restored)
    except UnsafeSQLError:
        raise AliasRefused("the restored query is not a single read-only query") from None


# ------------------------------------------------------------- detection --

@dataclass(frozen=True)
class EntityConfig:
    """config/pii_entities.json: the shape the GLiNER playground uses."""

    labels: tuple[str, ...]
    label_expansions: dict = field(default_factory=dict)
    custom_words: dict = field(default_factory=dict)
    never_mask: frozenset = frozenset()


def load_entity_config(path: Path = CONFIG_FILE) -> EntityConfig:
    doc = json.loads(path.read_text(encoding="utf-8"))
    clean = lambda values: [str(v).strip() for v in values if str(v).strip()]  # noqa: E731
    return EntityConfig(
        labels=tuple(clean(doc.get("default_labels", []))),
        label_expansions={str(k).strip(): clean(v)
                          for k, v in doc.get("label_expansions", {}).items() if clean(v)},
        custom_words={str(k).strip(): clean(v)
                      for k, v in doc.get("custom_words", {}).items() if clean(v)},
        never_mask=frozenset(w.casefold() for w in clean(doc.get("never_mask", []))),
    )


def schema_vocabulary() -> frozenset:
    """Words the schema owns, which are never personal data: table and column
    names, whole, spaced and in parts, their listed values and the
    terminology. "department", "SLA" and "workflow code" are the small
    model's most frequent false hits on real questions."""
    from pipeline import metadata

    doc = metadata.schema()
    words: set[str] = set()
    for table, spec in (doc.get("tables") or {}).items():
        columns = spec.get("columns") or {}
        for name in [table, *columns]:
            words.update({name.casefold(), name.replace("_", " ").casefold()})
            words.update(p.casefold() for p in name.split("_") if len(p) >= 3)
        for cspec in columns.values():
            if isinstance(cspec, dict):
                words.update(str(v).casefold() for v in cspec.get("values") or [])
    words.update(str(k).casefold() for k in doc.get("terminology") or {})
    return frozenset(words)


def _whole_words(text: str, words_by_label: dict, source: str) -> list[dict]:
    found = []
    for label, words in words_by_label.items():
        parts = [r"\s+".join(map(re.escape, w.split()))
                 for w in sorted(words, key=len, reverse=True) if w.strip()]
        if not parts:
            continue
        pattern = re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)
        for m in pattern.finditer(text):
            found.append({"text": m.group(0), "label": label, "start": m.start(),
                          "end": m.end(), "confidence": 1.0, "source": source})
    return found


_RANK = {"vault": 0, "custom": 1, "model": 2}


def _resolve_overlaps(spans: list[dict]) -> list[dict]:
    """Non-overlapping spans: known values, then fixed words, then the more
    confident model finding, then the longer one."""
    ranked = sorted(spans, key=lambda s: (_RANK[s["source"]], -s["confidence"],
                                          s["start"] - s["end"]))
    kept: list[dict] = []
    for span in ranked:
        if all(span["end"] <= k["start"] or span["start"] >= k["end"] for k in kept):
            kept.append(span)
    return sorted(kept, key=lambda s: s["start"])


class Anonymizer:
    """What in a text is personal, and its replacement by aliases.

    Three sources, in order of trust: values this chat already aliased
    (matched exactly, so a value keeps its alias even on a turn the model
    misses it), the fixed custom words, and the model. A model finding that
    is a schema word, a never-mask word or already an alias is dropped.

    Shared by every request. Inference is thread-safe (checked: identical
    output at 4, 8 and 16 threads); the semaphore only stops threads beyond
    what the CPU can use from slowing every one of them down.
    """

    def __init__(self, model_id: str, threshold: float, config: EntityConfig,
                 vocabulary: Iterable[str] = (), model=None, concurrency: int = 4) -> None:
        self.model_id = model_id
        self.threshold = threshold
        self.config = config
        self.vocabulary = frozenset(vocabulary)
        self._model = model
        self._load_lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(max(1, concurrency))
        # Model label -> the label it is reported as.
        self.query: dict[str, str] = {}
        for label in config.labels:
            for model_label in config.label_expansions.get(label, [label]):
                self.query.setdefault(model_label, label)
        self.prefixes = DEFAULT_PREFIXES | {
            prefix_for(label) for label in [*config.labels, *config.custom_words]}
        _known_prefixes.update(self.prefixes)

    def load(self) -> None:
        with self._load_lock:
            if self._model is None:
                from gliner2 import AutoExtractor

                log.info("loading %s for PII aliasing", self.model_id)
                self._model = AutoExtractor.from_pretrained(self.model_id)

    def _keep(self, text: str, pattern: re.Pattern) -> bool:
        words = text.strip()
        key = words.casefold()
        if not words or key in self.config.never_mask or pattern.fullmatch(words):
            return False
        return not (key in self.vocabulary
                    or all(w in self.vocabulary for w in key.split()))

    def spans(self, text: str, vault: PiiVault) -> list[dict]:
        pattern = alias_pattern(self.prefixes | vault.prefixes())
        protected = [(m.start(), m.end()) for m in pattern.finditer(text)]

        known: dict[str, list[str]] = {}
        for entry in vault.entries():
            known.setdefault(entry["label"], []).append(entry["original"])
        found = _whole_words(text, known, "vault")
        found += _whole_words(text, self.config.custom_words, "custom")

        if self.query and pattern.sub("", text).strip():
            self.load()
            with self._slots:
                output = self._model.extract_entities(
                    text, list(self.query), threshold=self.threshold,
                    include_confidence=True, include_spans=True)
            for model_label, items in (output.get("entities") or {}).items():
                for item in items:
                    if self._keep(item["text"], pattern):
                        found.append({"text": item["text"],
                                      "label": self.query.get(model_label, model_label),
                                      "start": item["start"], "end": item["end"],
                                      "confidence": float(item.get("confidence", 0.0)),
                                      "source": "model"})

        found = [s for s in found
                 if all(s["end"] <= a or s["start"] >= b for a, b in protected)]
        return _resolve_overlaps(found)

    def apply(self, text: str, vault: PiiVault) -> str:
        if not text or not text.strip():
            return text
        parts, pos = [], 0
        for span in self.spans(text, vault):
            parts += [text[pos:span["start"]],
                      vault.alias_for(span["label"], text[span["start"]:span["end"]])]
            pos = span["end"]
        return "".join(parts) + text[pos:]


_shared: Anonymizer | None = None
_shared_lock = threading.Lock()


def get_anonymizer(settings) -> Anonymizer:
    """The one Anonymizer this process uses. The model loads on first use, or
    at startup when the server calls load()."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = Anonymizer(settings.pii_model, settings.pii_threshold,
                                 load_entity_config(), schema_vocabulary(),
                                 concurrency=settings.pii_concurrency)
        return _shared


# ------------------------------------------------------------------ guard --

@dataclass
class PiiGuard:
    """One turn's aliasing: the shared Anonymizer and this chat's vault."""

    anonymizer: Anonymizer
    vault: PiiVault = field(default_factory=PiiVault)
    # Known values the tripwire caught in outgoing prompts. A count only.
    masked: int = 0

    @property
    def prefixes(self) -> set[str]:
        return set(self.anonymizer.prefixes) | self.vault.prefixes()

    def anonymize(self, text: str) -> str:
        return self.anonymizer.apply(text, self.vault)

    def alias_name(self, name: str) -> str:
        return self.vault.alias_for("person", name) if name and name.strip() else name

    def guard(self, text: str) -> str:
        masked, count = mask_known(text, self.vault)
        if count:
            log.warning("PII tripwire replaced %d known value(s) in an outgoing prompt", count)
        self.masked += count
        return masked

    def note(self, *texts: str) -> str:
        """PLACEHOLDER_NOTE when any of the texts carries an alias, else ''."""
        pattern = alias_pattern(self.prefixes)
        return PLACEHOLDER_NOTE if any(t and pattern.search(t) for t in texts) else ""

    def restore_sql(self, sql: str) -> str:
        return restore_sql(sql, self.vault, self.prefixes)

    def restore_text(self, text):
        return restore_text(text, self.vault, self.prefixes)

    def restore_deep(self, value):
        return restore_deep(value, self.vault, self.prefixes)
