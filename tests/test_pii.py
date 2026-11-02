"""PII aliasing, one piece at a time: the vault, the text both ways, the SQL
and the detector. No model, no database and no LLM: the detector is handed a
scripted model, so every case is exact.

The design these pin: docs/pii-aliasing-design.md.
"""

from __future__ import annotations

import json
import re

import pytest

from pipeline.pii import (
    PLACEHOLDER_NOTE, AliasRefused, Anonymizer, EntityConfig, PiiGuard, PiiVault,
    VaultCorrupt, alias_pattern, mask_known, prefix_for, restore_deep, restore_sql,
    restore_text, stored_aliases,
)


class ScriptedModel:
    """Finds the strings it was given, reported the way GLiNER reports them."""

    def __init__(self, found: dict[str, tuple[str, float]] | None = None) -> None:
        self.found = found or {}
        self.calls = 0

    def extract_entities(self, text, labels, threshold=0.5, include_confidence=True,
                         include_spans=True):
        self.calls += 1
        out: dict[str, list] = {}
        for value, (label, confidence) in self.found.items():
            if confidence < threshold or label not in labels:
                continue
            for m in re.finditer(re.escape(value), text):
                out.setdefault(label, []).append(
                    {"text": value, "confidence": confidence, "start": m.start(), "end": m.end()})
        return {"entities": out}


CONFIG = EntityConfig(
    labels=("person", "email", "location", "company name"),
    label_expansions={"location": ["address", "city", "country"]},
    custom_words={"company name": ["PVH"]},
    never_mask=frozenset({"i", "me"}),
)


def anonymizer(found: dict[str, tuple[str, float]] | None = None) -> Anonymizer:
    return Anonymizer("scripted", 0.5, CONFIG, vocabulary={"department", "sla", "workflow code"},
                      model=ScriptedModel(found))


def vault_with(*pairs: tuple[str, str]) -> PiiVault:
    vault = PiiVault()
    for label, value in pairs:
        vault.alias_for(label, value)
    return vault


# ------------------------------------------------------------------ vault --

def test_one_value_keeps_one_alias_whatever_its_case_or_spacing():
    vault = PiiVault()
    assert vault.alias_for("person", "Rahul Sharma") == "PERSON_001"
    assert vault.alias_for("person", "rahul   SHARMA") == "PERSON_001"
    # Restored as first seen.
    assert vault.original("PERSON_001") == "Rahul Sharma"
    assert len(vault.new) == 1


def test_different_values_are_numbered_per_prefix():
    vault = PiiVault()
    assert vault.alias_for("person", "Rahul Sharma") == "PERSON_001"
    assert vault.alias_for("person", "Amit Rao") == "PERSON_002"
    assert vault.alias_for("email", "a@b.in") == "EMAIL_001"
    assert vault.alias_for("person", "Priya") == "PERSON_003"


def test_labels_that_share_a_prefix_share_the_alias():
    # Found as a city once and as an address later, still one place.
    vault = PiiVault()
    assert vault.alias_for("city", "Mumbai") == "LOCATION_001"
    assert vault.alias_for("address", "Mumbai") == "LOCATION_001"
    assert prefix_for("pan number") == "PAN_NUMBER"


def test_numbering_continues_from_the_stored_aliases_never_restarts():
    # Turn 5 stored PERSON_001 and PERSON_004 (002 and 003 in turns since
    # forgotten by nobody: numbers come from what is stored, not a counter).
    vault = PiiVault.from_entries([
        {"alias": "PERSON_001", "label": "person", "original": "Rahul Sharma"},
        {"alias": "PERSON_004", "label": "person", "original": "Amit Rao"},
    ])
    assert vault.alias_for("person", "Rahul Sharma") == "PERSON_001"
    assert vault.alias_for("person", "Neha Joshi") == "PERSON_005"
    # Only the new one is stored with this turn.
    assert vault.new == [{"alias": "PERSON_005", "label": "person", "original": "Neha Joshi"}]


@pytest.mark.parametrize("entries", [
    [{"alias": "PERSON_001", "label": "person", "original": "A"},
     {"alias": "PERSON_001", "label": "person", "original": "B"}],
    [{"alias": "PERSON_001", "label": "person", "original": "A"},
     {"alias": "PERSON_002", "label": "person", "original": "a"}],
    [{"alias": "PERSON_001"}],
    ["not an entry"],
])
def test_stored_aliases_that_contradict_each_other_are_refused(entries):
    with pytest.raises(VaultCorrupt):
        PiiVault.from_entries(entries)


def test_the_same_entry_stored_twice_is_harmless():
    entry = {"alias": "PERSON_001", "label": "person", "original": "A"}
    vault = PiiVault.from_entries([entry, entry])
    assert vault.entries() == [entry]


def test_stored_aliases_are_read_from_any_shape_metadata_comes_in():
    entry = {"alias": "PERSON_001", "label": "person", "original": "A"}
    rows = [{"pii": {"new_aliases": [entry]}}, json.dumps({"pii": {"new_aliases": []}}),
            None, "not json", {"no": "pii"}, [{"alias": "EMAIL_001", "label": "email",
                                              "original": "a@b.in"}]]
    assert [e["alias"] for e in stored_aliases(rows)] == ["PERSON_001", "EMAIL_001"]


# ----------------------------------------------------------- text both ways --

def test_prose_gets_its_values_back_and_unknown_aliases_stay():
    vault = vault_with(("person", "Rahul Sharma"))
    assert restore_text("Tasks of PERSON_001 and PERSON_002.", vault) == \
        "Tasks of Rahul Sharma and PERSON_002."


def test_only_our_prefixes_count_as_aliases():
    # WF_001 has an alias's shape and is a real workflow code.
    vault = vault_with(("person", "Rahul Sharma"))
    assert restore_text("WF_001 for PERSON_001", vault) == "WF_001 for Rahul Sharma"
    assert not alias_pattern({"PERSON"}).search("XPERSON_001 PERSON_0012a")


def test_a_response_is_restored_except_its_sql():
    vault = vault_with(("person", "Rahul Sharma"))
    out = restore_deep({"explanation": "Tasks of PERSON_001",
                        "followup": {"suggestions": [{"label": "Only PERSON_001", "ref": "x"}]},
                        "generated_sql": "SELECT 1 WHERE n = 'PERSON_001'"}, vault)
    assert out["explanation"] == "Tasks of Rahul Sharma"
    assert out["followup"]["suggestions"][0]["label"] == "Only Rahul Sharma"
    assert out["generated_sql"] == "SELECT 1 WHERE n = 'PERSON_001'"


def test_the_tripwire_masks_known_values_and_counts_them():
    vault = vault_with(("person", "Rahul Sharma"), ("email", "rahul@gmail.com"))
    text = ('invalid input for "rahul  sharma"; mail RAHUL@gmail.com; '
            "Rahul Sharmas is another word")
    masked, count = mask_known(text, vault)
    assert masked == ('invalid input for "PERSON_001"; mail EMAIL_001; '
                      "Rahul Sharmas is another word")
    assert count == 2


def test_the_placeholder_note_is_sent_only_when_there_is_an_alias():
    guard = PiiGuard(anonymizer(), vault_with(("person", "Rahul Sharma")))
    assert guard.note("tasks of PERSON_001") == PLACEHOLDER_NOTE
    assert guard.note("open tasks", "") == ""


# -------------------------------------------------------------------- SQL --

V = vault_with(("person", "Rahul Sharma"), ("person", "Amit Rao"),
               ("email", "rahul_s%1@gmail.com"), ("person", "Sean O'Brien"),
               ("person", "Zoë Ångström"))
# PERSON_001 Rahul Sharma, PERSON_002 Amit Rao, EMAIL_001 rahul_s%1@gmail.com,
# PERSON_003 Sean O'Brien, PERSON_004 Zoë Ångström


@pytest.mark.parametrize("alias_sql,real_sql", [
    ("SELECT task_id FROM tms_task_flat WHERE assigned_user_name = 'PERSON_001'",
     "SELECT task_id FROM tms_task_flat WHERE assigned_user_name = 'Rahul Sharma'"),
    ("SELECT task_id FROM tms_task_flat WHERE assigned_user_name IN ('PERSON_001', 'PERSON_002')",
     "SELECT task_id FROM tms_task_flat WHERE assigned_user_name IN ('Rahul Sharma', 'Amit Rao')"),
    ("SELECT task_id FROM tms_task_flat WHERE assigned_user_name ILIKE '%PERSON_001%'",
     "SELECT task_id FROM tms_task_flat WHERE assigned_user_name ILIKE '%Rahul Sharma%'"),
    # The value's own _ and % are literal in a LIKE pattern; the model's are not.
    ("SELECT 1 FROM tms_user_flat WHERE user_name LIKE '%EMAIL_001'",
     "SELECT 1 FROM tms_user_flat WHERE user_name LIKE '%rahul\\_s\\%1@gmail.com'"),
    ("SELECT 1 FROM tms_user_flat WHERE user_name NOT LIKE 'EMAIL_001%'",
     "SELECT 1 FROM tms_user_flat WHERE user_name NOT LIKE 'rahul\\_s\\%1@gmail.com%'"),
    # Outside LIKE the value is as it is.
    ("SELECT 1 FROM tms_user_flat WHERE user_name = 'EMAIL_001'",
     "SELECT 1 FROM tms_user_flat WHERE user_name = 'rahul_s%1@gmail.com'"),
    ("SELECT t.task_id FROM tms_task_flat t JOIN tms_user_flat u "
     "ON u.user_id = t.assigned_user_id AND u.user_name = 'PERSON_002'",
     "SELECT t.task_id FROM tms_task_flat t JOIN tms_user_flat u "
     "ON u.user_id = t.assigned_user_id AND u.user_name = 'Amit Rao'"),
    ("SELECT task_id FROM tms_task_flat WHERE assigned_user_id IN "
     "(SELECT user_id FROM tms_user_flat WHERE user_name = 'PERSON_001')",
     "SELECT task_id FROM tms_task_flat WHERE assigned_user_id IN "
     "(SELECT user_id FROM tms_user_flat WHERE user_name = 'Rahul Sharma')"),
    ("WITH u AS (SELECT user_id FROM tms_user_flat WHERE user_name = 'PERSON_002') "
     "SELECT COUNT(*) FROM tms_task_flat t JOIN u ON u.user_id = t.assigned_user_id",
     "WITH u AS (SELECT user_id FROM tms_user_flat WHERE user_name = 'Amit Rao') "
     "SELECT COUNT(*) FROM tms_task_flat t JOIN u ON u.user_id = t.assigned_user_id"),
    ("SELECT 1 FROM tms_user_flat WHERE user_name = 'PERSON_003'",
     "SELECT 1 FROM tms_user_flat WHERE user_name = 'Sean O''Brien'"),
    ("SELECT 1 FROM tms_user_flat WHERE user_name = 'PERSON_004'",
     "SELECT 1 FROM tms_user_flat WHERE user_name = 'Zoë Ångström'"),
    ("SELECT 'Report for PERSON_001 and PERSON_002' AS t",
     "SELECT 'Report for Rahul Sharma and Amit Rao' AS t"),
    # Comments are not run; left as written.
    ("SELECT 1 FROM tms_user_flat WHERE user_name = 'PERSON_001' -- PERSON_002",
     "SELECT 1 FROM tms_user_flat WHERE user_name = 'Rahul Sharma' -- PERSON_002"),
    # A real value with an alias's shape, but not our prefix.
    ("SELECT 1 FROM tms_task_flat WHERE workflow_code = 'WF_001'",
     "SELECT 1 FROM tms_task_flat WHERE workflow_code = 'WF_001'"),
    # Layout survives byte for byte.
    ("SELECT  task_id\n  FROM tms_task_flat\n WHERE assigned_user_name='PERSON_001'\n",
     "SELECT  task_id\n  FROM tms_task_flat\n WHERE assigned_user_name='Rahul Sharma'\n"),
])
def test_aliases_go_back_into_string_literals_and_nothing_else_moves(alias_sql, real_sql):
    assert restore_sql(alias_sql, V) == real_sql


def test_sql_without_aliases_is_returned_untouched():
    sql = "SELECT COUNT(*) FROM tms_task_flat WHERE task_status = 'open'"
    assert restore_sql(sql, V) is sql


@pytest.mark.parametrize("alias_sql,reason", [
    ('SELECT user_name AS "PERSON_001" FROM tms_user_flat', "string literal"),
    ("SELECT 1 FROM tms_user_flat WHERE user_name = PERSON_001", "string literal"),
    ("SELECT 1 FROM tms_user_flat WHERE user_name = E'PERSON_001'", "string literal"),
    ("SELECT 1 FROM tms_user_flat WHERE user_name = $$PERSON_001$$", "string literal"),
    ("SELECT 1 FROM tms_user_flat WHERE user_name = 'PERSON_009'", "not one of"),
    ("SELECT 1 FROM tms_user_flat WHERE user_name LIKE '%PERSON_001!%' ESCAPE '!'", "ESCAPE"),
])
def test_an_alias_anywhere_else_is_refused_not_guessed_at(alias_sql, reason):
    with pytest.raises(AliasRefused, match=reason) as caught:
        restore_sql(alias_sql, V)
    # The message goes back to the model in a repair: aliases only, no value.
    assert "Rahul" not in str(caught.value)


@pytest.mark.parametrize("original", [
    "x' OR '1'='1",
    "a\\'; SELECT pg_sleep(10); --",
])
def test_a_hostile_value_stays_one_literal(original):
    vault = vault_with(("person", original))
    sql = "SELECT 1 FROM tms_user_flat WHERE user_name = 'PERSON_001'"
    restored = restore_sql(sql, vault)
    assert restored == ("SELECT 1 FROM tms_user_flat WHERE user_name = '"
                        + original.replace("'", "''") + "'")


def test_a_value_naming_a_write_is_refused_by_the_read_only_gate():
    # Quoted correctly it would be harmless, but the read-only gate's keyword
    # check reads inside literals too. Refused is the safe way to be wrong.
    vault = vault_with(("person", "a'; DROP TABLE tms_user_flat; --"))
    with pytest.raises(AliasRefused, match="read-only"):
        restore_sql("SELECT 1 FROM tms_user_flat WHERE user_name = 'PERSON_001'", vault)


# -------------------------------------------------------------- detection --

def test_the_question_from_the_brief():
    a = anonymizer({"Rahul Sharma": ("person", 0.99), "Mumbai": ("city", 0.97),
                    "rahul@gmail.com": ("email", 0.98)})
    vault = PiiVault()
    out = a.apply("Show me all tasks assigned to Rahul Sharma from Mumbai and check "
                  "his email rahul@gmail.com.", vault)
    assert out == ("Show me all tasks assigned to PERSON_001 from LOCATION_001 and "
                   "check his email EMAIL_001.")
    assert {e["alias"]: e["original"] for e in vault.new} == {
        "PERSON_001": "Rahul Sharma", "LOCATION_001": "Mumbai", "EMAIL_001": "rahul@gmail.com"}


def test_schema_words_never_mask_words_and_low_confidence_are_dropped():
    a = anonymizer({"department": ("company name", 0.9), "SLA": ("company name", 0.7),
                    "workflow code": ("company name", 0.6), "I": ("person", 0.8),
                    "Priya": ("person", 0.4)})
    text = "Which department wise SLA report did I share with the workflow code team, Priya?"
    assert a.apply(text, PiiVault()) == text


def test_a_custom_word_is_found_without_the_model():
    a = anonymizer()
    assert a.apply("Show PVH tasks", PiiVault()) == "Show COMPANY_001 tasks"


def test_a_value_the_chat_already_aliased_is_found_even_when_the_model_misses_it():
    vault = vault_with(("person", "Rahul Sharma"))
    a = anonymizer({})            # finds nothing at all this time
    assert a.apply("and rahul sharma's closed ones", vault) == "and PERSON_001's closed ones"
    assert vault.new == [vault.entries()[0]]     # nothing new beyond the seed


def test_aliases_pass_through_and_applying_twice_changes_nothing():
    a = anonymizer({"Rahul Sharma": ("person", 0.99), "PERSON_001": ("person", 0.9)})
    vault = PiiVault()
    once = a.apply("tasks of Rahul Sharma", vault)
    assert once == "tasks of PERSON_001"
    assert a.apply(once, vault) == once
    assert [e["alias"] for e in vault.entries()] == ["PERSON_001"]


def test_a_custom_word_beats_an_overlapping_model_finding():
    a = anonymizer({"PVH Retail": ("person", 0.95)})
    assert a.apply("Show PVH Retail tasks", PiiVault()) == "Show COMPANY_001 Retail tasks"


def test_the_model_is_not_asked_about_text_that_is_only_aliases():
    a = anonymizer({})
    vault = vault_with(("person", "Rahul Sharma"))
    a.apply("PERSON_001", vault)
    a.apply("   ", vault)
    assert a._model.calls == 0
