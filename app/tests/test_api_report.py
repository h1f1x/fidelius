"""Endpunkte der Auswertung: Kennzahlen als JSON und das Rohlog zum Download."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from fidelius import config
from fidelius.main import app

LINE = {"zeit": "2026-10-06T10:00:00+00:00", "quelle": "anfrage", "zeichen": 1000,
        "gesamt_ms": 120}


def test_report_for_known_period(tmp_path, monkeypatch):
    path = tmp_path / "requests.jsonl"
    path.write_text(json.dumps(LINE) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "REQUEST_LOG", str(path))

    # Ohne Context-Manager, damit der Startup-Hook keine Modelle lädt.
    response = TestClient(app).get("/api/report", params={"period": "all"})

    assert response.status_code == 200
    assert response.json()["period"] == "all"
    assert response.json()["metrics"]["requests"] == 1


def test_report_without_log_is_no_404(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REQUEST_LOG", str(tmp_path / "fehlt.jsonl"))

    response = TestClient(app).get("/api/report")

    assert response.status_code == 200
    assert response.json()["period"] == "30d"
    assert response.json()["log"]["present"] is False
    assert response.json()["log"]["path"] == str(tmp_path / "fehlt.jsonl")


def test_unknown_period_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REQUEST_LOG", str(tmp_path / "fehlt.jsonl"))

    response = TestClient(app).get("/api/report", params={"period": "1y"})

    assert response.status_code == 400


def test_raw_log_download(tmp_path, monkeypatch):
    path = tmp_path / "requests.jsonl"
    path.write_text(json.dumps(LINE) + "\n{kaputt\n", encoding="utf-8")
    monkeypatch.setattr(config, "REQUEST_LOG", str(path))

    response = TestClient(app).get("/api/request-log")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert "attachment" in response.headers["content-disposition"]
    assert response.text == path.read_text(encoding="utf-8")


def test_raw_log_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REQUEST_LOG", str(tmp_path / "fehlt.jsonl"))

    assert TestClient(app).get("/api/request-log").status_code == 404


def test_report_page_is_served_as_html():
    response = TestClient(app).get("/auswertung")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Auswertung Request-Log</title>" in response.text
    assert '<script src="/static/report.js' in response.text


def test_main_page_links_to_report_in_expert_mode():
    response = TestClient(app).get("/")

    assert '<a href="/auswertung" class="infolink expert-only"' in response.text
