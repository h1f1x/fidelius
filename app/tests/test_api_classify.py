"""„Neu bewerten“ über POST /api/classify (docs/specs/klassifikation.md, Abschnitt 6).

Fake-Laya beantwortet `ask` mit festen Wahrscheinlichkeiten für `stufe`; Gate und
Treffer-Bestätigung darf der Endpunkt nicht aufrufen.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fidelius import config, main
from fidelius.main import app
from fidelius.pipeline import Pipeline

from .conftest import OEFFENTLICH, VERTRAULICH, Chunk, FakeLaya

TEXT = "Das Angebot an <ORGANISATION_1> liegt bei 2,4 Mio. Euro, bitte nicht weitergeben."


def asking_laya(**kwargs) -> FakeLaya:
    """Zwei Abschnitte: der erste harmlos, der zweite vertraulich."""
    return FakeLaya(ask_chunks=[Chunk(0, 30, OEFFENTLICH), Chunk(30, None, VERTRAULICH)], **kwargs)


@pytest.fixture
def log_path(tmp_path):
    return tmp_path / "requests.jsonl"


def post(laya, payload, log_path=None, **kwargs):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(main, "pipeline", Pipeline(laya=laya, detectors=[], log_path=log_path))
        return TestClient(app).post("/api/classify", json=payload, **kwargs)


def test_returns_level_of_the_given_text_with_triggering_chunk(enabled):
    laya = asking_laya()
    r = post(laya, {"text": TEXT})
    assert r.status_code == 200
    assert laya.extras == []  # kein Gate
    assert not laya.classified  # keine Treffer-Bestätigung
    body = r.json()
    assert body["level"] == "vertraulich"
    assert body["chunk"] == {"start": 30, "end": len(TEXT)}
    assert [c["level"] for c in body["chunks"]] == ["oeffentlich", "vertraulich"]
    assert laya.asked[0][0] == TEXT
    assert "stufe" in laya.asked[0][1]


def test_flag_off_answers_404(rules_file, monkeypatch):
    monkeypatch.setattr(config, "CLASSIFICATION_ENABLED", False)
    laya = asking_laya()
    assert post(laya, {"text": TEXT}).status_code == 404
    assert laya.asked == []


def test_invalid_rules_file_answers_404(enabled, rules_file):
    rules_file.write_text("stufen: []\n", encoding="utf-8")
    laya = asking_laya()
    assert post(laya, {"text": TEXT}).status_code == 404
    assert laya.asked == []


def test_text_longer_than_for_analyze_is_rejected(enabled, monkeypatch):
    monkeypatch.setattr(config, "MAX_TEXT_CHARS", 20)
    laya = asking_laya()
    r = post(laya, {"text": TEXT})
    assert r.status_code == 413
    assert "höchstens 20" in r.json()["detail"]
    assert laya.asked == []


def test_body_larger_than_for_analyze_is_rejected(enabled, monkeypatch):
    monkeypatch.setattr(config, "MAX_BODY_BYTES", 50)
    laya = asking_laya()
    r = post(laya, {"text": TEXT})
    assert r.status_code == 413
    assert laya.asked == []


def test_empty_text_is_rejected_like_in_analyze(enabled):
    laya = asking_laya()
    assert post(laya, {"text": "  \n"}).status_code == 400
    assert laya.asked == []


def test_unreachable_laya_answers_503_with_reason(enabled):
    r = post(asking_laya(ask_reachable=False), {"text": TEXT})
    assert r.status_code == 503
    assert "Laya nicht erreichbar" in r.json()["detail"]


def test_writes_no_request_log_entry(enabled, log_path):
    assert post(asking_laya(), {"text": TEXT}, log_path=log_path).status_code == 200
    assert not log_path.exists() or log_path.read_text(encoding="utf-8") == ""
