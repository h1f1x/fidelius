"""Zugangsdaten-Warnung in /api/analyze (docs/specs/klassifikation.md, Abschnitte 4, 5 und 6).

Zugangsdaten im Original lösen die Warnung aus, ob als ZUGANG-Treffer oder über die
Laya-Frage `zugang` in einem Abschnitt.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fidelius import config, main
from fidelius.laya_client import GateResult, Section
from fidelius.main import app
from fidelius.pipeline import Pipeline

from .test_classification_analyze import analyze, enabled, rules_file  # noqa: F401

APPROVED = {"oeffentlich": 0.1, "intern": 0.8, "vertraulich": 0.1}  # Stufe = freigegeben_bis


class CredentialLaya:
    """Gate harmlos, Stufe freigegeben; je Abschnitt ein fester Wert für `zugang`."""

    def __init__(self, *section_zugang: tuple[int, int, float]):
        self.section_zugang = section_zugang
        self.extras: list[dict | None] = []

    def gate(self, text: str, extra: dict[str, dict] | None = None) -> GateResult:
        self.extras.append(extra)
        parts = self.section_zugang or ((0, len(text), 0.0),)
        sections = []
        for start, end, zugang in parts:
            answers = {"pii": {"noul": 0.1}}
            if extra and "stufe" in extra:
                answers["stufe"] = {"choice": "intern", "probabilities": APPROVED}
            if extra and "zugang" in extra:
                answers["zugang"] = {"noul": zugang}
            sections.append(Section(start, end, text[start:end], answers))
        return GateResult(probability=0.1, sections=sections)


PASSWORD_TEXT = "Für den Server gilt passwort: Sommer2026! ab sofort."


def test_credential_hit_alone_warns(enabled):
    res = analyze(CredentialLaya(), PASSWORD_TEXT)
    c = res["classification"]

    assert any(e["category"] == "ZUGANG" for e in res["entities"])
    assert c["original"]["level"] == "intern"
    assert c["credentials"] is True
    assert c["warn"] is True


def test_warning_stays_when_credentials_are_replaced(enabled):
    res = analyze(CredentialLaya(), PASSWORD_TEXT)

    assert "Sommer2026!" not in res["anonymized_text"]
    assert res["classification"]["credentials"] is True


def test_warning_stays_when_credentials_category_is_deselected(enabled):
    """Abgewählt bleibt das Passwort im Text stehen, die Warnung erst recht."""
    pipeline = Pipeline(laya=CredentialLaya(), detectors=[], clock=lambda: 0.0)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(main, "pipeline", pipeline)
        r = TestClient(app).post("/api/analyze", json={"text": PASSWORD_TEXT, "categories": ["PERSON"]})
    res = r.json()

    assert "Sommer2026!" in res["anonymized_text"]
    assert res["classification"]["credentials"] is True
    assert res["classification"]["warn"] is True


PLAIN = "Die Kantine hat ein neues Menü.\n\nDer Zugang zum Lager läuft über den Hausmeister."


@pytest.mark.parametrize("zugang, warn", [(0.49, False), (0.5, True)])
def test_laya_value_at_threshold_alone_warns(enabled, monkeypatch, zugang, warn):
    monkeypatch.setattr(config, "ZUGANG_THRESHOLD", 0.5)
    res = analyze(CredentialLaya((0, 31, 0.1), (33, len(PLAIN), zugang)), PLAIN)
    c = res["classification"]

    assert not any(e["category"] == "ZUGANG" for e in res["entities"])
    assert [ch["credentials"] for ch in c["original"]["chunks"]] == [0.1, zugang]
    assert c["credentials"] is warn
    assert c["warn"] is warn
