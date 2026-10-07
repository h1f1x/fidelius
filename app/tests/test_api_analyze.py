"""POST /api/analyze über HTTP, mit Fake-Laya statt Modellen; das Log lesen wir über die API."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from fidelius import config, main
from fidelius.main import app
from fidelius.pipeline import Pipeline

BODY = {"text": "Herr Emre Yilmaz wohnt in Berlin.", "gate_threshold": 0.5, "force": False,
        "use_laya_check": True}


class HarmlessLaya:
    """Stuft jeden Text als harmlos ein, dann laufen weder Erkenner noch Bestätigung."""

    def gate(self, text: str) -> float:
        return 0.1


@pytest.fixture
def client(tmp_path, monkeypatch):
    log_path = tmp_path / "requests.jsonl"
    monkeypatch.setattr(config, "REQUEST_LOG", str(log_path))
    # Feste Uhr: Alle Dauern sind 0, damit sich Antworten vergleichen lassen.
    monkeypatch.setattr(main, "pipeline", Pipeline(laya=HarmlessLaya(), detectors=[],
                                                   clock=lambda: 0.0, log_path=log_path))
    # Ohne Context-Manager, damit der Startup-Hook keine Modelle lädt.
    return TestClient(app)


def logged_sources(client: TestClient) -> list[str]:
    response = client.get("/api/request-log")
    return [json.loads(line)["quelle"] for line in response.text.splitlines()]


def test_load_test_header_marks_log_entry(client):
    response = client.post("/api/analyze", json=BODY, headers={"X-Fidelius-Quelle": "lasttest"})

    assert response.status_code == 200
    assert logged_sources(client) == ["lasttest"]


def test_without_header_entry_is_a_request(client):
    client.post("/api/analyze", json=BODY)

    assert logged_sources(client) == ["anfrage"]


def test_load_test_header_leaves_response_unchanged(client):
    marked = client.post("/api/analyze", json=BODY, headers={"X-Fidelius-Quelle": "lasttest"})
    plain = client.post("/api/analyze", json=BODY)

    assert marked.status_code == plain.status_code == 200
    assert marked.json() == plain.json()


@pytest.mark.parametrize("value", ["kalibrierung", "Lasttest", "lasttest-2", ""])
def test_other_header_values_are_ignored(client, value):
    response = client.post("/api/analyze", json=BODY, headers={"X-Fidelius-Quelle": value})

    assert response.status_code == 200
    assert logged_sources(client) == ["anfrage"]
