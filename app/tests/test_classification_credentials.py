"""Zugangsdaten-Warnung in /api/analyze (docs/specs/klassifikation.md, Abschnitte 4, 5 und 6).

Zugangsdaten im Original lösen die Warnung aus, ob als ZUGANG-Treffer oder über die
Laya-Frage `zugang` in einem Abschnitt.
"""
from __future__ import annotations

import pytest

from fidelius import config

from .conftest import INTERN, Chunk, FakeLaya, analyze_http


def credential_laya(*chunks: Chunk) -> FakeLaya:
    """Gate harmlos, Stufe freigegeben; je Abschnitt ein fester Wert für `zugang`."""
    return FakeLaya(0.1, chunks=chunks or (Chunk(stufe=INTERN),))


PASSWORD_TEXT = "Für den Server gilt passwort: Sommer2026! ab sofort."


def test_credential_hit_alone_warns(enabled):
    res = analyze_http(credential_laya(), PASSWORD_TEXT)
    c = res["classification"]

    assert any(e["category"] == "ZUGANG" for e in res["entities"])
    assert c["original"]["level"] == "intern"
    assert c["credentials"] is True
    assert c["warn"] is True


def test_warning_stays_when_credentials_are_replaced(enabled):
    res = analyze_http(credential_laya(), PASSWORD_TEXT)

    assert "Sommer2026!" not in res["anonymized_text"]
    assert res["classification"]["credentials"] is True


def test_warning_stays_when_credentials_category_is_deselected(enabled):
    """Abgewählt bleibt das Passwort im Text stehen, die Warnung erst recht."""
    res = analyze_http(credential_laya(), PASSWORD_TEXT, categories=["PERSON"])

    assert "Sommer2026!" in res["anonymized_text"]
    assert res["classification"]["credentials"] is True
    assert res["classification"]["warn"] is True


PLAIN = "Die Kantine hat ein neues Menü.\n\nDer Zugang zum Lager läuft über den Hausmeister."


@pytest.mark.parametrize("zugang, warn", [(0.49, False), (0.5, True)])
def test_laya_value_at_threshold_alone_warns(enabled, monkeypatch, zugang, warn):
    monkeypatch.setattr(config, "ZUGANG_THRESHOLD", 0.5)
    res = analyze_http(credential_laya(Chunk(0, 31, INTERN, 0.1), Chunk(33, None, INTERN, zugang)), PLAIN)
    c = res["classification"]

    assert not any(e["category"] == "ZUGANG" for e in res["entities"])
    assert [ch["credentials"] for ch in c["original"]["chunks"]] == [0.1, zugang]
    assert c["credentials"] is warn
    assert c["warn"] is warn
