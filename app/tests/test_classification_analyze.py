"""Schutzstufe des Originals in /api/analyze (docs/specs/klassifikation.md, Abschnitte 4 und 6).

Fake-Laya liefert je Abschnitt feste Wahrscheinlichkeiten für die Frage `stufe`.
"""
from __future__ import annotations

import pytest

from fidelius import config
from fidelius.detectors.base import RawHit

from .conftest import INTERN, OEFFENTLICH, VERTRAULICH, Chunk, FakeClock, FakeLaya, analyze_http

TEXT = "Die Kantine bietet ab Montag ein neues Menü an."
HARMLESS = 0.1  # Gate-Wert: Text harmlos, keine Erkennung


def test_most_probable_level_when_none_above_threshold_is_higher(enabled):
    laya = FakeLaya(HARMLESS, chunks=[Chunk(stufe={"oeffentlich": 0.6, "intern": 0.25, "vertraulich": 0.15})])
    res = analyze_http(laya, TEXT)

    original = res["classification"]["original"]
    assert original["level"] == "oeffentlich"


def test_highest_level_at_threshold_wins_over_most_probable(enabled):
    probs = {"oeffentlich": 0.4, "intern": 0.25, "vertraulich": 0.35}
    res = analyze_http(FakeLaya(HARMLESS, chunks=[Chunk(stufe=probs)]), TEXT)

    assert res["classification"]["original"]["level"] == "vertraulich"


TWO_PARAS = "Die Kantine hat ein neues Menü.\n\nDer Umsatz im dritten Quartal sank um 12 Prozent."


def test_text_level_is_highest_over_sections_with_triggering_chunk(enabled):
    laya = FakeLaya(HARMLESS, chunks=[
        Chunk(0, 31, {"oeffentlich": 0.7, "intern": 0.2, "vertraulich": 0.1}),
        Chunk(33, None, {"oeffentlich": 0.1, "intern": 0.5, "vertraulich": 0.4}),
    ])
    original = analyze_http(laya, TWO_PARAS)["classification"]["original"]

    assert original["level"] == "vertraulich"
    assert original["chunk"] == {"start": 33, "end": len(TWO_PARAS)}
    assert [c["level"] for c in original["chunks"]] == ["oeffentlich", "vertraulich"]
    assert original["chunks"][1]["probabilities"] == {"oeffentlich": 0.1, "intern": 0.5, "vertraulich": 0.4}


@pytest.mark.parametrize("probs, warn", [
    (INTERN, False),  # intern = freigegeben_bis
    ({"oeffentlich": 0.1, "intern": 0.5, "vertraulich": 0.4}, True),
])
def test_warns_only_above_approval(enabled, probs, warn):
    c = analyze_http(FakeLaya(HARMLESS, chunks=[Chunk(stufe=probs)]), TEXT)["classification"]

    assert c["warn"] is warn
    assert c["credentials"] is False
    assert c["anonymized"] is None
    assert c["note"] is None


def test_level_questions_run_in_the_single_gate_batch(enabled):
    laya = FakeLaya(HARMLESS)
    analyze_http(laya, TEXT)

    assert laya.extras == [{"stufe": {
        "type": "choice",
        "instructions": "Welcher Schutzstufe gehört dieser Text an?",
        "criteria": {"oeffentlich": "Veröffentlichte Information", "intern": "Interne Arbeitsunterlage",
                     "vertraulich": "Geschäftsgeheimnis"},
    }, "zugang": {
        "type": "noul",
        "instructions": "Enthält dieser Text ein Passwort, einen Token, einen API-Key, "
                        "einen privaten Schlüssel oder andere Zugangsdaten?",
    }}]


def test_unreachable_laya_answers_200_with_note_and_no_level(enabled):
    c = analyze_http(FakeLaya(HARMLESS, reachable=False), TEXT)["classification"]

    assert c["original"] is None
    assert c["warn"] is False
    assert c["note"] == "Laya nicht erreichbar (ConnectionError); keine Schutzstufe."


def test_without_flag_no_classification_and_no_extra_questions(rules_file, monkeypatch):
    monkeypatch.setattr(config, "CLASSIFICATION_ENABLED", False)
    laya = FakeLaya(HARMLESS)

    res = analyze_http(laya, TEXT)

    assert "classification" not in res
    assert laya.extras == [None]


def test_flag_with_missing_file_behaves_like_flag_off(enabled, rules_file):
    rules_file.unlink()
    laya = FakeLaya(HARMLESS)

    res = analyze_http(laya, TEXT)

    assert "classification" not in res
    assert laya.extras == [None]


# ---- Zweiter Durchlauf: Schutzstufe des anonymisierten Texts (#12) ----------------------

PERSON_TEXT = "Herr Emre Yilmaz hat einen Termin in der Kardiologie."
PERSON_ANON = "Herr [PERSON_1] hat einen Termin in der Kardiologie."
SENSITIVE = 0.9  # Gate-Wert: Erkennung läuft


def person_detector(text: str) -> list[RawHit]:
    return [RawHit(5, 16, "Emre Yilmaz", "PERSON", "gliner", "person", 0.9)]


def test_anonymized_text_gets_its_own_level_from_a_second_pass(enabled):
    laya = FakeLaya(SENSITIVE, chunks=[Chunk(stufe=VERTRAULICH)])

    c = analyze_http(laya, PERSON_TEXT, detectors=[person_detector])["classification"]

    assert c["original"]["level"] == "vertraulich"
    assert c["anonymized"]["level"] == "oeffentlich"
    assert c["anonymized"]["chunk"] == {"start": 0, "end": len(PERSON_ANON)}
    asked_text, asked_questions = laya.asked[0]
    assert asked_text == PERSON_ANON
    # Dieselben Klassifikationsfragen wie beim Original (Spec 4), aber keine Gate-Fragen.
    assert list(asked_questions) == ["stufe", "zugang"]


def test_unchanged_text_gets_no_second_pass(enabled):
    laya = FakeLaya(HARMLESS)  # harmlos: keine Erkennung, Text bleibt gleich

    res = analyze_http(laya, TEXT, detectors=[person_detector])

    assert res["anonymized_text"] == TEXT
    assert laya.asked == []
    assert res["classification"]["anonymized"] is None
    assert res["timing"]["classification_ms"] == 0


@pytest.mark.parametrize("original, anonymized, warn", [
    (INTERN, OEFFENTLICH, False),
    (VERTRAULICH, OEFFENTLICH, True),  # Original zählt mit
    (INTERN, VERTRAULICH, True),
])
def test_warns_when_either_level_is_above_approval(enabled, original, anonymized, warn):
    laya = FakeLaya(SENSITIVE, chunks=[Chunk(stufe=original)], ask_chunks=[Chunk(stufe=anonymized)])

    c = analyze_http(laya, PERSON_TEXT, detectors=[person_detector])["classification"]

    assert c["warn"] is warn


def test_second_pass_duration_shows_in_timing(enabled):
    clock = FakeClock()

    class SlowLaya(FakeLaya):
        def ask(self, text, questions):
            clock.now += 0.25
            return super().ask(text, questions)

    laya = SlowLaya(SENSITIVE, chunks=[Chunk(stufe=VERTRAULICH)])

    timing = analyze_http(laya, PERSON_TEXT, detectors=[person_detector], clock=clock)["timing"]

    assert timing["classification_ms"] == 250
    assert timing["total_ms"] == 250


def test_failing_second_pass_keeps_original_level_with_note(enabled):
    laya = FakeLaya(SENSITIVE, chunks=[Chunk(stufe=VERTRAULICH)], ask_reachable=False)

    c = analyze_http(laya, PERSON_TEXT, detectors=[person_detector])["classification"]

    assert c["original"]["level"] == "vertraulich"
    assert c["anonymized"] is None
    assert c["warn"] is True
    assert c["note"] == "Laya nicht erreichbar (TimeoutError); keine Schutzstufe für den anonymisierten Text."
