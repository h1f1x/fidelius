"""Kalibrierbeispiele unter examples/klassifikation (docs/specs/klassifikation.md, 3 und 9)."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

from fidelius import config
from fidelius.classification import load_rules
from fidelius.main import app

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
CALIBRATION = EXAMPLES / "klassifikation"


def test_example_picker_does_not_list_calibration_texts(monkeypatch):
    monkeypatch.setattr(config, "EXAMPLES_DIR", str(EXAMPLES))
    # Ohne Context-Manager, damit der Startup-Hook keine Modelle lädt.
    names = {e["name"] for e in TestClient(app).get("/api/examples").json()}

    assert names  # die normalen Beispielmails stehen drin
    assert not names & {p.stem for p in CALIBRATION.glob("*.txt")}


def test_every_level_of_the_example_rules_has_three_texts_with_expectation():
    rules = load_rules(str(ROOT / "klassifikation.example.yaml"))
    expected = json.loads((CALIBRATION / "expected.json").read_text(encoding="utf-8"))
    texts = {p.stem for p in CALIBRATION.glob("*.txt")}

    assert texts == set(expected)
    per_level = Counter(e["stufe"] for e in expected.values())
    assert set(per_level) == {lv.id for lv in rules.levels}
    assert min(per_level.values()) >= 3
    assert any(e.get("zugangsdaten") for e in expected.values())
