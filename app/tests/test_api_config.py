"""Tests für die Konfiguration, die das Frontend beim Start lädt."""
from __future__ import annotations

from fastapi.testclient import TestClient

from fidelius import config
from fidelius.main import app


def test_config_reports_max_text_chars(monkeypatch):
    monkeypatch.setattr(config, "MAX_TEXT_CHARS", 10000)
    # Ohne Context-Manager, damit der Startup-Hook keine Modelle lädt.
    r = TestClient(app).get("/api/config")
    assert r.status_code == 200
    assert r.json()["max_text_chars"] == 10000  # daraus rechnet das Frontend die Seiten


def test_config_reports_notice_from_file(monkeypatch, tmp_path):
    f = tmp_path / "hinweise.md"
    f.write_text("Bitte die **Betriebsvereinbarung** beachten.\n", encoding="utf-8")
    monkeypatch.setattr(config, "NOTICE_FILE", str(f))
    assert TestClient(app).get("/api/config").json()["notice"] == "Bitte die **Betriebsvereinbarung** beachten."


def test_config_reports_no_notice_without_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "NOTICE_FILE", str(tmp_path / "fehlt.md"))
    assert TestClient(app).get("/api/config").json()["notice"] is None


def test_config_reports_no_notice_for_empty_file(monkeypatch, tmp_path):
    f = tmp_path / "hinweise.md"
    f.write_text("  \n", encoding="utf-8")
    monkeypatch.setattr(config, "NOTICE_FILE", str(f))
    assert TestClient(app).get("/api/config").json()["notice"] is None
