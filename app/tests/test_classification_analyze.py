"""Schutzstufe des Originals in /api/analyze (docs/specs/klassifikation.md, Abschnitte 4 und 6).

Fake-Laya liefert je Abschnitt feste Wahrscheinlichkeiten für die Frage `stufe`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fidelius import config, main
from fidelius.detectors.base import RawHit
from fidelius.laya_client import GateResult, Section
from fidelius.main import app
from fidelius.models import Entity
from fidelius.pipeline import Pipeline

RULES = """\
freigegeben_bis: intern
schwelle: 0.3
stufen:
  - id: oeffentlich
    name: Öffentlich
    laya: Veröffentlichte Information
    text: Darf in jedes KI-System.
  - id: intern
    name: Intern
    laya: Interne Arbeitsunterlage
    text: Nur in freigegebene KI-Systeme.
  - id: vertraulich
    name: Vertraulich
    laya: Geschäftsgeheimnis
    text: Nur mit Freigabe.
"""

TEXT = "Die Kantine bietet ab Montag ein neues Menü an."


class ClassifyingLaya:
    """Gate harmlos; je Abschnitt eine Antwort auf `stufe`, wenn die Frage gestellt wurde."""

    def __init__(self, *section_probs: tuple[int, int, dict[str, float]], reachable=True,
                 gate_probability=0.1, anonymized_probs: dict[str, float] | None = None,
                 ask_reachable=True):
        self.section_probs = section_probs or ((0, len(TEXT), {"oeffentlich": 0.6, "intern": 0.25, "vertraulich": 0.15}),)
        self.reachable = reachable
        self.gate_probability = gate_probability
        self.anonymized_probs = anonymized_probs or {"oeffentlich": 0.7, "intern": 0.2, "vertraulich": 0.1}
        self.ask_reachable = ask_reachable
        self.extras: list[dict | None] = []
        self.asked: list[tuple[str, dict]] = []  # zweiter Durchlauf: (Text, Fragen)

    def gate(self, text: str, extra: dict[str, dict] | None = None) -> GateResult:
        self.extras.append(extra)
        if not self.reachable:
            raise ConnectionError("Laya ist weg")
        sections = []
        for start, end, probs in self.section_probs:
            answers = {"pii": {"noul": 0.1}}
            if extra and "stufe" in extra:
                answers["stufe"] = {"choice": max(probs, key=probs.get), "probabilities": probs}
            sections.append(Section(start, end, text[start:end], answers))
        return GateResult(probability=self.gate_probability, sections=sections)

    def ask(self, text: str, questions: dict[str, dict]) -> list[Section]:
        self.asked.append((text, questions))
        if not self.ask_reachable:
            raise TimeoutError("Laya antwortet nicht")
        probs = self.anonymized_probs
        return [Section(0, len(text), text,
                        {"stufe": {"choice": max(probs, key=probs.get), "probabilities": probs}})]

    def classify(self, text: str, entities: list[Entity]) -> list[Entity]:
        return entities


@pytest.fixture
def rules_file(tmp_path, monkeypatch):
    f = tmp_path / "klassifikation.yaml"
    f.write_text(RULES, encoding="utf-8")
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", str(f))
    return f


@pytest.fixture
def enabled(rules_file, monkeypatch):
    monkeypatch.setattr(config, "CLASSIFICATION_ENABLED", True)


def analyze(laya, text: str = TEXT, detectors=(), clock=lambda: 0.0) -> dict:
    """Über HTTP, damit auch das Fehlen des Felds in der JSON-Antwort geprüft ist."""
    main_pipeline = Pipeline(laya=laya, detectors=list(detectors), clock=clock)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(main, "pipeline", main_pipeline)
        r = TestClient(app).post("/api/analyze", json={"text": text})
    assert r.status_code == 200
    return r.json()


def test_most_probable_level_when_none_above_threshold_is_higher(enabled):
    res = analyze(ClassifyingLaya())

    original = res["classification"]["original"]
    assert original["level"] == "oeffentlich"


def test_highest_level_at_threshold_wins_over_most_probable(enabled):
    probs = {"oeffentlich": 0.4, "intern": 0.25, "vertraulich": 0.35}
    res = analyze(ClassifyingLaya((0, len(TEXT), probs)))

    assert res["classification"]["original"]["level"] == "vertraulich"


TWO_PARAS = "Die Kantine hat ein neues Menü.\n\nDer Umsatz im dritten Quartal sank um 12 Prozent."


def test_text_level_is_highest_over_sections_with_triggering_chunk(enabled):
    laya = ClassifyingLaya(
        (0, 31, {"oeffentlich": 0.7, "intern": 0.2, "vertraulich": 0.1}),
        (33, len(TWO_PARAS), {"oeffentlich": 0.1, "intern": 0.5, "vertraulich": 0.4}),
    )
    original = analyze(laya, TWO_PARAS)["classification"]["original"]

    assert original["level"] == "vertraulich"
    assert original["chunk"] == {"start": 33, "end": len(TWO_PARAS)}
    assert [c["level"] for c in original["chunks"]] == ["oeffentlich", "vertraulich"]
    assert original["chunks"][1]["probabilities"] == {"oeffentlich": 0.1, "intern": 0.5, "vertraulich": 0.4}


@pytest.mark.parametrize("probs, warn", [
    ({"oeffentlich": 0.1, "intern": 0.8, "vertraulich": 0.1}, False),  # intern = freigegeben_bis
    ({"oeffentlich": 0.1, "intern": 0.5, "vertraulich": 0.4}, True),
])
def test_warns_only_above_approval(enabled, probs, warn):
    c = analyze(ClassifyingLaya((0, len(TEXT), probs)))["classification"]

    assert c["warn"] is warn
    assert c["credentials"] is False
    assert c["anonymized"] is None
    assert c["note"] is None


def test_level_questions_run_in_the_single_gate_batch(enabled):
    laya = ClassifyingLaya()
    analyze(laya)

    assert laya.extras == [{"stufe": {
        "type": "choice",
        "instructions": "Welcher Schutzstufe gehört dieser Text an?",
        "criteria": {"oeffentlich": "Veröffentlichte Information", "intern": "Interne Arbeitsunterlage",
                     "vertraulich": "Geschäftsgeheimnis"},
    }}]


def test_unreachable_laya_answers_200_with_note_and_no_level(enabled):
    c = analyze(ClassifyingLaya(reachable=False))["classification"]

    assert c["original"] is None
    assert c["warn"] is False
    assert c["note"] == "Laya nicht erreichbar (ConnectionError); keine Schutzstufe."


def test_without_flag_no_classification_and_no_extra_questions(rules_file, monkeypatch):
    monkeypatch.setattr(config, "CLASSIFICATION_ENABLED", False)
    laya = ClassifyingLaya()

    res = analyze(laya)

    assert "classification" not in res
    assert laya.extras == [None]


def test_flag_with_missing_file_behaves_like_flag_off(enabled, rules_file):
    rules_file.unlink()
    laya = ClassifyingLaya()

    res = analyze(laya)

    assert "classification" not in res
    assert laya.extras == [None]


# ---- Zweiter Durchlauf: Schutzstufe des anonymisierten Texts (#12) ----------------------

PERSON_TEXT = "Herr Emre Yilmaz hat einen Termin in der Kardiologie."
PERSON_ANON = "Herr [PERSON_1] hat einen Termin in der Kardiologie."
VERTRAULICH = {"oeffentlich": 0.1, "intern": 0.3, "vertraulich": 0.6}


def person_detector(text: str) -> list[RawHit]:
    return [RawHit(5, 16, "Emre Yilmaz", "PERSON", "gliner", "person", 0.9)]


def test_anonymized_text_gets_its_own_level_from_a_second_pass(enabled):
    laya = ClassifyingLaya((0, len(PERSON_TEXT), VERTRAULICH), gate_probability=0.9)

    c = analyze(laya, PERSON_TEXT, detectors=[person_detector])["classification"]

    assert c["original"]["level"] == "vertraulich"
    assert c["anonymized"]["level"] == "oeffentlich"
    assert c["anonymized"]["chunk"] == {"start": 0, "end": len(PERSON_ANON)}
    asked_text, asked_questions = laya.asked[0]
    assert asked_text == PERSON_ANON
    assert list(asked_questions) == ["stufe"]  # keine Gate-Fragen im zweiten Durchlauf


def test_unchanged_text_gets_no_second_pass(enabled):
    laya = ClassifyingLaya(gate_probability=0.1)  # harmlos: keine Erkennung, Text bleibt gleich

    res = analyze(laya, detectors=[person_detector])

    assert res["anonymized_text"] == TEXT
    assert laya.asked == []
    assert res["classification"]["anonymized"] is None
    assert res["timing"]["classification_ms"] == 0


@pytest.mark.parametrize("original, anonymized, warn", [
    ({"oeffentlich": 0.1, "intern": 0.8, "vertraulich": 0.1}, {"oeffentlich": 0.8, "intern": 0.1, "vertraulich": 0.1}, False),
    (VERTRAULICH, {"oeffentlich": 0.8, "intern": 0.1, "vertraulich": 0.1}, True),  # Original zählt mit
    ({"oeffentlich": 0.1, "intern": 0.8, "vertraulich": 0.1}, VERTRAULICH, True),
])
def test_warns_when_either_level_is_above_approval(enabled, original, anonymized, warn):
    laya = ClassifyingLaya((0, len(PERSON_TEXT), original), gate_probability=0.9,
                           anonymized_probs=anonymized)

    c = analyze(laya, PERSON_TEXT, detectors=[person_detector])["classification"]

    assert c["warn"] is warn


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_second_pass_duration_shows_in_timing(enabled):
    clock = Clock()

    class SlowLaya(ClassifyingLaya):
        def ask(self, text, questions):
            clock.now += 0.25
            return super().ask(text, questions)

    laya = SlowLaya((0, len(PERSON_TEXT), VERTRAULICH), gate_probability=0.9)

    timing = analyze(laya, PERSON_TEXT, detectors=[person_detector], clock=clock)["timing"]

    assert timing["classification_ms"] == 250
    assert timing["total_ms"] == 250


def test_failing_second_pass_keeps_original_level_with_note(enabled):
    laya = ClassifyingLaya((0, len(PERSON_TEXT), VERTRAULICH), gate_probability=0.9,
                           ask_reachable=False)

    c = analyze(laya, PERSON_TEXT, detectors=[person_detector])["classification"]

    assert c["original"]["level"] == "vertraulich"
    assert c["anonymized"] is None
    assert c["warn"] is True
    assert c["note"] == "Laya nicht erreichbar (TimeoutError); keine Schutzstufe für den anonymisierten Text."
