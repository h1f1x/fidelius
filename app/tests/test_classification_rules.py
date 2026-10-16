"""Tests für Flag und Regeldatei der Klassifikation (docs/specs/klassifikation.md, Abschnitt 1 und 2)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fidelius import classification, config
from fidelius.main import app

from .conftest import RULES

EXAMPLE = Path(__file__).resolve().parents[2] / "klassifikation.example.yaml"

def _write(tmp_path, content: str) -> str:
    f = tmp_path / "klassifikation.yaml"
    f.write_text(content, encoding="utf-8")
    return str(f)


def test_load_valid_rules(tmp_path):
    rules = classification.load_rules(_write(tmp_path, RULES))
    assert [lv.id for lv in rules.levels] == ["oeffentlich", "intern", "vertraulich"]
    assert rules.approved_up_to == "intern"
    assert rules.threshold == 0.3
    assert rules.credentials_text == "Nie in ein KI-System."
    assert rules.levels[2].laya == "Geschäftsgeheimnis"


def test_threshold_and_credentials_text_are_optional(tmp_path):
    content = RULES.replace("schwelle: 0.3\n", "").split("zugangsdaten:")[0]
    rules = classification.load_rules(_write(tmp_path, content))
    assert rules.threshold == classification.DEFAULT_THRESHOLD
    assert rules.credentials_text is None


def test_rank_follows_order_in_file(tmp_path):
    rules = classification.load_rules(_write(tmp_path, RULES))
    assert rules.rank("oeffentlich") < rules.rank("intern") < rules.rank("vertraulich")
    assert rules.above_approval("vertraulich")
    assert not rules.above_approval("intern")


@pytest.mark.parametrize("content, message", [
    ("stufen: [\n  - id: a\n", "Zeile"),
    (RULES.replace("freigegeben_bis: intern", "freigegeben_bis: geheim"), "geheim"),
    (RULES.replace("id: vertraulich", "id: intern"), "doppelt"),
    (RULES.split("  - id: intern")[0], "mindestens zwei"),
    (RULES.replace("    laya: Interne Arbeitsunterlage\n", ""), "laya"),
    (RULES.replace("schwelle: 0.3", "schwelle: 2"), "schwelle"),
    ("- nur eine Liste\n", "Zuordnung"),
])
def test_invalid_rules_raise_with_reason(tmp_path, content, message):
    with pytest.raises(classification.RulesError, match=message):
        classification.load_rules(_write(tmp_path, content))


@pytest.mark.parametrize("content, line", [
    (RULES.replace("freigegeben_bis: intern", "freigegeben_bis: geheim"), 1),
    (RULES.replace("schwelle: 0.3", "schwelle: 2"), 2),
    (RULES.split("  - id: intern")[0], 3),  # zu wenige Stufen: Zeile von stufen
    (RULES.replace("    laya: Interne Arbeitsunterlage\n", ""), 8),  # Stufe ohne laya
    (RULES.replace("id: vertraulich", "id: intern"), 12),  # doppelte id
], ids=["freigegeben_bis", "schwelle", "zu-wenige-stufen", "ohne-laya", "doppelte-id"])
def test_semantic_errors_name_the_line(tmp_path, content, line):
    with pytest.raises(classification.RulesError, match=rf"^Zeile {line}: "):
        classification.load_rules(_write(tmp_path, content))


def test_health_names_the_line_of_a_duplicate_id(client, enabled, monkeypatch, tmp_path):
    path = _write(tmp_path, RULES.replace("id: vertraulich", "id: intern"))
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", path)
    assert client.get("/api/health").json()["classification"] == \
        "Fehler: Zeile 12: Stufe 3: id intern ist doppelt"


def test_example_file_in_repo_is_valid():
    rules = classification.load_rules(str(EXAMPLE))
    assert len(rules.levels) == 4
    assert rules.levels[0].id == "oeffentlich"


def test_active_rules_off_without_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CLASSIFICATION_ENABLED", False)
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", _write(tmp_path, RULES))
    assert classification.rules() is None
    assert classification.status() == "aus"


def test_active_rules_with_flag_and_valid_file(enabled, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", _write(tmp_path, RULES))
    assert classification.rules() is not None
    assert classification.status() == "aktiv: 3 Stufen"


def test_active_rules_with_flag_but_missing_file(enabled, monkeypatch, tmp_path):
    path = str(tmp_path / "fehlt.yaml")
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", path)
    assert classification.rules() is None
    assert classification.status() == f"Fehler: Regeldatei fehlt ({path})"


def test_rules_file_is_read_on_every_call(enabled, monkeypatch, tmp_path):
    path = _write(tmp_path, RULES)
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", path)
    assert len(classification.rules().levels) == 3
    _write(tmp_path, RULES.split("  - id: vertraulich")[0])
    assert len(classification.rules().levels) == 2


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
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", _write(tmp_path, RULES))
    assert client.get("/api/health").json()["classification"] == "aus"
    assert client.get("/api/config").json()["classification"] is None


def test_health_reports_invalid_file(client, enabled, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", _write(tmp_path, "stufen: [\n"))
    assert client.get("/api/health").json()["classification"].startswith("Fehler: ")
    assert client.get("/api/config").json()["classification"] is None


def test_config_lists_levels_without_laya_descriptions(client, enabled, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", _write(tmp_path, RULES))
    c = client.get("/api/config").json()["classification"]
    assert c["freigegeben_bis"] == "intern"
    assert c["zugangsdaten_text"] == "Nie in ein KI-System."
    assert c["levels"][0] == {"id": "oeffentlich", "name": "Öffentlich", "text": "Darf in jedes KI-System."}
    assert "laya" not in str(c)


def test_config_reports_threshold_for_expert_view(client, enabled, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", _write(tmp_path, RULES))
    assert client.get("/api/config").json()["classification"]["schwelle"] == 0.3
