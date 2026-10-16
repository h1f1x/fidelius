"""Tests für Flag und Regeldatei der Klassifikation (docs/specs/klassifikation.md, Abschnitt 1 und 2)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fidelius import classification, config
from fidelius.main import app

EXAMPLE = Path(__file__).resolve().parents[2] / "klassifikation.example.yaml"

VALID = """\
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
zugangsdaten:
  text: Nie in ein KI-System.
"""


def _write(tmp_path, content: str) -> str:
    f = tmp_path / "klassifikation.yaml"
    f.write_text(content, encoding="utf-8")
    return str(f)


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(config, "CLASSIFICATION_ENABLED", True)


def test_load_valid_rules(tmp_path):
    rules = classification.load_rules(_write(tmp_path, VALID))
    assert [lv.id for lv in rules.levels] == ["oeffentlich", "intern", "vertraulich"]
    assert rules.approved_up_to == "intern"
    assert rules.threshold == 0.3
    assert rules.credentials_text == "Nie in ein KI-System."
    assert rules.levels[2].laya == "Geschäftsgeheimnis"


def test_threshold_and_credentials_text_are_optional(tmp_path):
    content = VALID.replace("schwelle: 0.3\n", "").split("zugangsdaten:")[0]
    rules = classification.load_rules(_write(tmp_path, content))
    assert rules.threshold == classification.DEFAULT_THRESHOLD
    assert rules.credentials_text is None


def test_rank_follows_order_in_file(tmp_path):
    rules = classification.load_rules(_write(tmp_path, VALID))
    assert rules.rank("oeffentlich") < rules.rank("intern") < rules.rank("vertraulich")
    assert rules.above_approval("vertraulich")
    assert not rules.above_approval("intern")


@pytest.mark.parametrize("content, message", [
    ("stufen: [\n  - id: a\n", "Zeile"),
    (VALID.replace("freigegeben_bis: intern", "freigegeben_bis: geheim"), "geheim"),
    (VALID.replace("id: vertraulich", "id: intern"), "doppelt"),
    (VALID.split("  - id: intern")[0], "mindestens zwei"),
    (VALID.replace("    laya: Interne Arbeitsunterlage\n", ""), "laya"),
    (VALID.replace("schwelle: 0.3", "schwelle: 2"), "schwelle"),
    ("- nur eine Liste\n", "Zuordnung"),
])
def test_invalid_rules_raise_with_reason(tmp_path, content, message):
    with pytest.raises(classification.RulesError, match=message):
        classification.load_rules(_write(tmp_path, content))


def test_example_file_in_repo_is_valid():
    rules = classification.load_rules(str(EXAMPLE))
    assert len(rules.levels) == 4
    assert rules.levels[0].id == "oeffentlich"


def test_active_rules_off_without_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CLASSIFICATION_ENABLED", False)
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", _write(tmp_path, VALID))
    assert classification.active_rules() == (None, "aus")


def test_active_rules_with_flag_and_valid_file(enabled, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", _write(tmp_path, VALID))
    rules, status = classification.active_rules()
    assert rules is not None
    assert status == "aktiv: 3 Stufen"


def test_active_rules_with_flag_but_missing_file(enabled, monkeypatch, tmp_path):
    path = str(tmp_path / "fehlt.yaml")
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", path)
    rules, status = classification.active_rules()
    assert rules is None
    assert status == f"Fehler: Regeldatei fehlt ({path})"


def test_rules_file_is_read_on_every_call(enabled, monkeypatch, tmp_path):
    path = _write(tmp_path, VALID)
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", path)
    assert classification.active_rules()[1] == "aktiv: 3 Stufen"
    _write(tmp_path, VALID.split("  - id: vertraulich")[0])
    assert classification.active_rules()[1] == "aktiv: 2 Stufen"


# ---- /api/health und /api/config ------------------------------------------------------

class _NoLaya:
    def health(self):
        return {"status": "ok"}


@pytest.fixture
def client(monkeypatch):
    from fidelius import main
    monkeypatch.setattr(main.pipeline, "laya", _NoLaya())
    return TestClient(app)


def test_health_and_config_without_flag(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CLASSIFICATION_ENABLED", False)
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", _write(tmp_path, VALID))
    assert client.get("/api/health").json()["classification"] == "aus"
    assert client.get("/api/config").json()["classification"] is None


def test_health_reports_invalid_file(client, enabled, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", _write(tmp_path, "stufen: [\n"))
    assert client.get("/api/health").json()["classification"].startswith("Fehler: ")
    assert client.get("/api/config").json()["classification"] is None


def test_config_lists_levels_without_laya_descriptions(client, enabled, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", _write(tmp_path, VALID))
    c = client.get("/api/config").json()["classification"]
    assert c["freigegeben_bis"] == "intern"
    assert c["zugangsdaten_text"] == "Nie in ein KI-System."
    assert c["levels"][0] == {"id": "oeffentlich", "name": "Öffentlich", "text": "Darf in jedes KI-System."}
    assert "laya" not in str(c)
