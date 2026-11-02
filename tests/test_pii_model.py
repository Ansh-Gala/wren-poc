"""The real detector: GLiNER 2.5 small, loaded on this machine.

Marked integration: it loads a 0.3 GB model, downloaded on the first run and
cached after. Skipped when gliner2 is not installed or the model cannot load.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from pipeline.pii import Anonymizer, PiiVault, load_entity_config, schema_vocabulary

pytestmark = pytest.mark.integration
pytest.importorskip("gliner2")


@pytest.fixture(scope="module")
def real() -> Anonymizer:
    from config.settings import load_settings

    settings = load_settings()
    detector = Anonymizer(settings.pii_model, settings.pii_threshold,
                          load_entity_config(), schema_vocabulary())
    try:
        detector.load()
    except Exception as exc:          # offline with an empty cache, say
        pytest.skip(f"{settings.pii_model} could not load: {exc}")
    return detector


def test_the_question_from_the_brief(real):
    vault = PiiVault()
    out = real.apply("Show me all tasks assigned to Rahul Sharma from Mumbai and check "
                     "his email rahul@gmail.com.", vault)
    for value in ("Rahul Sharma", "Mumbai", "rahul@gmail.com"):
        assert value not in out
    assert "PERSON_001" in out and "EMAIL_001" in out


def test_schema_words_and_pronouns_are_left_alone(real):
    text = "Which department wise SLA report did I share with the workflow code team?"
    out = real.apply(text, PiiVault())
    for word in ("department", "SLA", " I ", "workflow code"):
        assert word in out


def test_detection_from_many_threads_matches_one_at_a_time(real):
    texts = ["How many open tasks does Priya Nair in Pune have?",
             "Email anita.desai@acme.co.in about the Bengaluru issues raised by Karan Mehta.",
             "my closed tasks",
             "Show tasks of Sunrise Retail Pvt Ltd created last week."] * 3
    serial = [real.apply(t, PiiVault()) for t in texts]
    with ThreadPoolExecutor(4) as pool:
        parallel = list(pool.map(lambda t: real.apply(t, PiiVault()), texts))
    assert parallel == serial
