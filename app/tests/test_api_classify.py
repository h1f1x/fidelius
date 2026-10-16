"""„Neu bewerten“ über POST /api/classify (docs/specs/klassifikation.md, Abschnitt 6).

Fake-Laya beantwortet nur `ask` mit festen Wahrscheinlichkeiten für `stufe`; das Gate darf
der Endpunkt nicht aufrufen.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fidelius import config, main
from fidelius.laya_client import Section
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

TEXT = "Das Angebot an <ORGANISATION_1> liegt bei 2,4 Mio. Euro, bitte nicht weitergeben."


class AskingLaya:
    """Zwei Abschnitte: der erste harmlos, der zweite vertraulich."""

    def __init__(self, reachable=True):
        self.reachable = reachable
        self.asked: list[tuple[str, dict]] = []

    def ask(self, text: str, questions: dict[str, dict]) -> list[Section]:
        self.asked.append((text, questions))
        if not self.reachable:
            raise ConnectionError("Laya ist weg")
        cut = 30
        probs = [{"oeffentlich": 0.7, "intern": 0.2, "vertraulich": 0.1},
                 {"oeffentlich": 0.1, "intern": 0.3, "vertraulich": 0.6}]
        return [Section(s, e, text[s:e], {"stufe": {"choice": max(p, key=p.get), "probabilities": p}})
                for (s, e), p in zip(((0, cut), (cut, len(text))), probs)]

    def gate(self, *args, **kwargs):
        raise AssertionError("/api/classify darf kein Gate aufrufen")

    def classify(self, *args, **kwargs):
        raise AssertionError("/api/classify darf keine Treffer prüfen")


@pytest.fixture
def rules_file(tmp_path, monkeypatch):
    f = tmp_path / "klassifikation.yaml"
    f.write_text(RULES, encoding="utf-8")
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", str(f))
    return f


@pytest.fixture
def enabled(rules_file, monkeypatch):
    monkeypatch.setattr(config, "CLASSIFICATION_ENABLED", True)


@pytest.fixture
def log_path(tmp_path):
    return tmp_path / "requests.jsonl"


def post(laya, payload, log_path=None, **kwargs):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(main, "pipeline", Pipeline(laya=laya, detectors=[], log_path=log_path))
        return TestClient(app).post("/api/classify", json=payload, **kwargs)


def test_returns_level_of_the_given_text_with_triggering_chunk(enabled):
    laya = AskingLaya()
    r = post(laya, {"text": TEXT})
    assert r.status_code == 200
    body = r.json()
    assert body["level"] == "vertraulich"
    assert body["chunk"] == {"start": 30, "end": len(TEXT)}
    assert [c["level"] for c in body["chunks"]] == ["oeffentlich", "vertraulich"]
    assert laya.asked[0][0] == TEXT
    assert "stufe" in laya.asked[0][1]


def test_flag_off_answers_404(rules_file, monkeypatch):
    monkeypatch.setattr(config, "CLASSIFICATION_ENABLED", False)
    laya = AskingLaya()
    assert post(laya, {"text": TEXT}).status_code == 404
    assert laya.asked == []


def test_invalid_rules_file_answers_404(enabled, rules_file):
    rules_file.write_text("stufen: []\n", encoding="utf-8")
    laya = AskingLaya()
    assert post(laya, {"text": TEXT}).status_code == 404
    assert laya.asked == []


def test_text_longer_than_for_analyze_is_rejected(enabled, monkeypatch):
    monkeypatch.setattr(config, "MAX_TEXT_CHARS", 20)
    laya = AskingLaya()
    r = post(laya, {"text": TEXT})
    assert r.status_code == 413
    assert "höchstens 20" in r.json()["detail"]
    assert laya.asked == []


def test_body_larger_than_for_analyze_is_rejected(enabled, monkeypatch):
    monkeypatch.setattr(config, "MAX_BODY_BYTES", 50)
    laya = AskingLaya()
    r = post(laya, {"text": TEXT})
    assert r.status_code == 413
    assert laya.asked == []


def test_empty_text_is_rejected_like_in_analyze(enabled):
    laya = AskingLaya()
    assert post(laya, {"text": "  \n"}).status_code == 400
    assert laya.asked == []


def test_unreachable_laya_answers_503_with_reason(enabled):
    r = post(AskingLaya(reachable=False), {"text": TEXT})
    assert r.status_code == 503
    assert "Laya nicht erreichbar" in r.json()["detail"]


def test_writes_no_request_log_entry(enabled, log_path):
    assert post(AskingLaya(), {"text": TEXT}, log_path=log_path).status_code == 200
    assert not log_path.exists() or log_path.read_text(encoding="utf-8") == ""
