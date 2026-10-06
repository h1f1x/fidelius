"""Endpunkte der Auswertung: Kennzahlen als JSON und das Rohlog zum Download."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from fidelius import config
from fidelius.main import app

ZEILE = {"zeit": "2026-10-06T10:00:00+00:00", "quelle": "anfrage", "zeichen": 1000,
         "gesamt_ms": 120}


def test_evaluation_for_known_period(tmp_path, monkeypatch):
    pfad = tmp_path / "requests.jsonl"
    pfad.write_text(json.dumps(ZEILE) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "REQUEST_LOG", str(pfad))

    # Ohne Context-Manager, damit der Startup-Hook keine Modelle lädt.
    r = TestClient(app).get("/api/auswertung", params={"zeitraum": "alles"})

    assert r.status_code == 200
    assert r.json()["zeitraum"] == "alles"
    assert r.json()["kennzahlen"]["anfragen"] == 1


def test_evaluation_without_log_is_no_404(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REQUEST_LOG", str(tmp_path / "fehlt.jsonl"))

    r = TestClient(app).get("/api/auswertung")

    assert r.status_code == 200
    assert r.json()["zeitraum"] == "30t"
    assert r.json()["log"]["vorhanden"] is False
    assert r.json()["log"]["pfad"] == str(tmp_path / "fehlt.jsonl")


def test_unknown_period_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REQUEST_LOG", str(tmp_path / "fehlt.jsonl"))

    r = TestClient(app).get("/api/auswertung", params={"zeitraum": "1j"})

    assert r.status_code == 400


def test_raw_log_download(tmp_path, monkeypatch):
    pfad = tmp_path / "requests.jsonl"
    pfad.write_text(json.dumps(ZEILE) + "\n{kaputt\n", encoding="utf-8")
    monkeypatch.setattr(config, "REQUEST_LOG", str(pfad))

    r = TestClient(app).get("/api/request-log")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert "attachment" in r.headers["content-disposition"]
    assert r.text == pfad.read_text(encoding="utf-8")


def test_raw_log_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REQUEST_LOG", str(tmp_path / "fehlt.jsonl"))

    assert TestClient(app).get("/api/request-log").status_code == 404


def test_evaluation_page_is_served_as_html():
    r = TestClient(app).get("/auswertung")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<title>Auswertung Request-Log</title>" in r.text
    assert '<script src="/static/auswertung.js' in r.text


def test_main_page_links_to_evaluation_in_expert_mode():
    r = TestClient(app).get("/")

    assert '<a href="/auswertung" class="infolink expert-only"' in r.text
