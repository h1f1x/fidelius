"""Zugangsdaten als Kategorie ZUGANG (docs/specs/klassifikation.md, Abschnitt 5)."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from fidelius import classification, config
from fidelius.detectors.base import RawHit
from fidelius.detectors.credentials import detect_credentials
from fidelius.laya_client import LayaClient
from fidelius.main import app
from fidelius.merge import merge_hits
from fidelius.models import AnalyzeRequest, Entity, Source
from fidelius.pipeline import Pipeline

from .conftest import RULES, FakeDetector, FakeLaya

PEM = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
    "QyNTUxOQAAACDx\n"
    "-----END OPENSSH PRIVATE KEY-----"
)


def _found(text: str) -> list[str]:
    return [h.text for h in detect_credentials(text)]


@pytest.mark.parametrize("secret", [
    "sk-proj-4fQx9Lm2Rt7Vb1Nc8Zp3Wk6Yh0Jd5Gs",
    "sk-ant-api03-Qw8eRt5yUi2oPa9sDf4gHj7k",
    "ghp_1A2b3C4d5E6f7G8h9I0jK1l2M3n4O5p6Q7r8",
    "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz",
    "glpat-xY9zW8vU7tS6rQ5pO4nM",
    "xoxb-123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx",
    "AKIAIOSFODNN7EXAMPLE",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
])
def test_known_token_formats(secret):
    assert _found(f"Der Schlüssel lautet {secret} und läuft ab.") == [secret]


def test_private_key_block_spans_all_lines():
    assert _found(f"Hier der Key:\n{PEM}\nGruß") == [PEM]


@pytest.mark.parametrize("line, value", [
    ("Passwort: Sommer2026!", "Sommer2026!"),
    ("password=hunter2", "hunter2"),
    ("Kennwort = Xy7#kL9q", "Xy7#kL9q"),
    ("api_key: 9f8e7d6c5b4a", "9f8e7d6c5b4a"),
    ('client_secret="abc123def456"', "abc123def456"),
    ("TOKEN=zz99yy88", "zz99yy88"),
])
def test_keyword_with_value_marks_only_the_value(line, value):
    assert _found(f"Zugang für den Test:\n{line}\nDanke") == [value]


@pytest.mark.parametrize("text", [
    "Bitte das Passwort ändern, es ist abgelaufen.",
    "Das Passwort: bekommst du von mir per Telefon.",
    "Wir brauchen einen API-Key für den Dienst.",
    "Die Firma Skoda baut Autos.",
    "Das Token-System läuft.",
])
def test_no_false_positives_in_prose(text):
    assert _found(text) == []


def test_credential_hit_wins_category_and_is_not_cut_at_newline():
    pem_hit = detect_credentials(PEM)[0]
    other = RawHit(36, 60, PEM[36:60], "KENNUNG", "regex", "id_prefixed", 1.0)
    [e] = merge_hits([pem_hit, other], PEM)
    assert e.category == "ZUGANG"
    assert e.text == PEM


# ---- Pipeline mit und ohne Flag ------------------------------------------------------

TEXT = "Hallo Emre, das Passwort: Sommer2026! und der Key ghp_1A2b3C4d5E6f7G8h9I0jK1l2M3n4O5p6Q7r8."


def _gliner_password() -> RawHit:
    s = TEXT.index("Sommer2026!")
    return RawHit(s, s + 11, "Sommer2026!", "KENNUNG", "gliner", "password", 0.8)


def _rules_on(monkeypatch, tmp_path, on: bool):
    f = tmp_path / "klassifikation.yaml"
    f.write_text(RULES, encoding="utf-8")
    monkeypatch.setattr(config, "CLASSIFICATION_ENABLED", on)
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", str(f))


def test_flag_off_keeps_todays_behaviour(monkeypatch, tmp_path):
    _rules_on(monkeypatch, tmp_path, False)
    pipeline = Pipeline(laya=FakeLaya(), detectors=[FakeDetector(_gliner_password())])
    res = pipeline.analyze(AnalyzeRequest(text=TEXT))
    assert [e.category for e in res.entities] == ["KENNUNG"]
    assert "ghp_" in res.anonymized_text


def test_flag_on_replaces_credentials_as_zugang(monkeypatch, tmp_path):
    _rules_on(monkeypatch, tmp_path, True)
    pipeline = Pipeline(laya=FakeLaya(), detectors=[FakeDetector(_gliner_password())])
    res = pipeline.analyze(AnalyzeRequest(text=TEXT))
    assert res.anonymized_text == "Hallo Emre, das Passwort: [ZUGANG_1] und der Key [ZUGANG_2]."
    assert {e.category for e in res.entities} == {"ZUGANG"}


def test_flag_on_finds_credentials_even_if_gate_says_harmless(monkeypatch, tmp_path):
    _rules_on(monkeypatch, tmp_path, True)
    detector = FakeDetector()
    pipeline = Pipeline(laya=FakeLaya(gate_probability=0.1), detectors=[detector])
    res = pipeline.analyze(AnalyzeRequest(text=TEXT))
    assert not detector.called
    assert res.anonymized_text == "Hallo Emre, das Passwort: [ZUGANG_1] und der Key [ZUGANG_2]."


def test_categories_include_zugang_only_when_active(monkeypatch, tmp_path):
    _rules_on(monkeypatch, tmp_path, False)
    assert "ZUGANG" not in classification.categories(classification.active_rules()[0])
    _rules_on(monkeypatch, tmp_path, True)
    assert "ZUGANG" in classification.categories(classification.active_rules()[0])


# ---- UI und Laya ---------------------------------------------------------------------

def test_ui_gets_zugang_colour_and_chip_only_when_active(monkeypatch, tmp_path):
    _rules_on(monkeypatch, tmp_path, False)
    assert "ZUGANG" not in TestClient(app).get("/api/config").json()["categories"]
    _rules_on(monkeypatch, tmp_path, True)
    zugang = TestClient(app).get("/api/config").json()["categories"]["ZUGANG"]
    assert zugang["label"]
    assert zugang["color"] not in {c["color"] for c in config.CATEGORIES.values()}


def test_laya_does_not_confirm_zugang_hits():
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        states = json.loads(request.content)["states"]
        asked.extend(s["candidate"] for s in states)
        ans = {"kind": {"choice": "NICHT_SENSIBEL", "probabilities": {"NICHT_SENSIBEL": 0.99}}}
        return httpx.Response(200, json={"results": [{"answers": ans} for _ in states]})

    laya = LayaClient()
    laya.client = httpx.Client(base_url="http://laya", transport=httpx.MockTransport(handler))
    person = Entity(id=1, start=5, end=11, text="Yilmaz", category="PERSON",
                    sources=[Source(name="gliner", label="person", score=0.9)])
    secret = Entity(id=2, start=22, end=33, text="Sommer2026!", category="ZUGANG",
                    sources=[Source(name="gliner", label="password", score=0.8)])

    out = laya.classify("Herr Yilmaz, Passwort Sommer2026!", [person, secret])

    assert asked == ["Yilmaz"]
    assert out[1] == secret
