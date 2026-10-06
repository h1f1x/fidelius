"""Tests für die Konfiguration, die das Frontend beim Start lädt."""
from __future__ import annotations

from fastapi.testclient import TestClient

from pii_app import config
from pii_app.main import app


def test_config_reports_max_text_chars(monkeypatch):
    monkeypatch.setattr(config, "MAX_TEXT_CHARS", 10000)
    # Ohne Context-Manager, damit der Startup-Hook keine Modelle lädt.
    r = TestClient(app).get("/api/config")
    assert r.status_code == 200
    assert r.json()["max_text_chars"] == 10000  # daraus rechnet das Frontend die Seiten
