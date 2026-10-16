"""Schutzstufe des Originals in /api/analyze (docs/specs/klassifikation.md, Abschnitte 4 und 6).

Fake-Laya liefert je Abschnitt feste Wahrscheinlichkeiten für die Frage `stufe`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fidelius import config, main
from fidelius.laya_client import GateResult, Section
from fidelius.main import app
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

    def __init__(self, *section_probs: tuple[int, int, dict[str, float]], reachable=True):
        self.section_probs = section_probs or ((0, len(TEXT), {"oeffentlich": 0.6, "intern": 0.25, "vertraulich": 0.15}),)
        self.reachable = reachable
        self.extras: list[dict | None] = []

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
        return GateResult(probability=0.1, sections=sections)


@pytest.fixture
def rules_file(tmp_path, monkeypatch):
    f = tmp_path / "klassifikation.yaml"
    f.write_text(RULES, encoding="utf-8")
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", str(f))
    return f


@pytest.fixture
def enabled(rules_file, monkeypatch):
    monkeypatch.setattr(config, "CLASSIFICATION_ENABLED", True)


def analyze(laya, text: str = TEXT) -> dict:
    """Über HTTP, damit auch das Fehlen des Felds in der JSON-Antwort geprüft ist."""
    main_pipeline = Pipeline(laya=laya, detectors=[], clock=lambda: 0.0)
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
