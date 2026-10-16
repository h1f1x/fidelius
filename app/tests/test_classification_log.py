"""Klassifikation im Request-Log (docs/specs/klassifikation.md, Abschnitt 8)."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from fidelius import config
from fidelius.classification import load_rules
from fidelius.log_report import report
from fidelius.main import app
from fidelius.models import AnalyzeRequest
from fidelius.pipeline import Pipeline
from tests.test_classification_analyze import (  # noqa: F401  (Fixtures)
    PERSON_TEXT, TEXT, VERTRAULICH, ClassifyingLaya, Clock, enabled, person_detector, rules_file,
)
from tests.test_log_report import NOW, entry, write_log

CLASSIFICATION_FIELDS = {"stufe_original", "stufe_anonymisiert", "zugangsdaten", "gewarnt",
                         "klassifikation_ms"}
BASE_FIELDS = {"zeit", "build", "quelle", "zeichen", "gate_wert", "schwelle", "sensibel",
               "trotzdem", "laya_bestaetigung", "gate_ms", "erkennung_ms", "laya_ms", "gesamt_ms",
               "stellen", "platzhalter", "laya_abgelehnt", "fehler"}


def logged(tmp_path, laya, text=TEXT, detectors=(), clock=lambda: 0.0) -> dict:
    log_path = tmp_path / "requests.jsonl"
    Pipeline(laya=laya, detectors=list(detectors), clock=clock,
             log_path=log_path).analyze(AnalyzeRequest(text=text))
    [line] = log_path.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


def test_log_holds_both_levels_warning_and_second_pass_duration(enabled, tmp_path):
    clock = Clock()

    class SlowLaya(ClassifyingLaya):
        def ask(self, text, questions):
            clock.now += 0.25
            return super().ask(text, questions)

    laya = SlowLaya((0, len(PERSON_TEXT), VERTRAULICH), gate_probability=0.9)

    line = logged(tmp_path, laya, PERSON_TEXT, detectors=[person_detector], clock=clock)

    assert {k: line[k] for k in CLASSIFICATION_FIELDS} == {
        "stufe_original": "vertraulich", "stufe_anonymisiert": "oeffentlich",
        "zugangsdaten": False, "gewarnt": True, "klassifikation_ms": 250,
    }


def test_without_flag_the_fields_are_missing(rules_file, tmp_path):
    line = logged(tmp_path, ClassifyingLaya())

    assert not CLASSIFICATION_FIELDS & set(line)


def test_unreachable_laya_logs_no_level(enabled, tmp_path):
    line = logged(tmp_path, ClassifyingLaya(reachable=False))

    assert line["stufe_original"] is None
    assert line["stufe_anonymisiert"] is None
    assert line["gewarnt"] is False


def test_log_has_neither_text_nor_probabilities_nor_section_bounds(enabled, tmp_path):
    laya = ClassifyingLaya((0, len(PERSON_TEXT), VERTRAULICH), gate_probability=0.9)

    line = logged(tmp_path, laya, PERSON_TEXT, detectors=[person_detector])

    # Gegenüber Flag aus kommen genau die fünf Felder hinzu, alle als Einzelwert.
    assert set(line) - BASE_FIELDS == CLASSIFICATION_FIELDS
    assert all(isinstance(line[k], str | bool | int) for k in CLASSIFICATION_FIELDS)
    for leak in ("Kardiologie", "Yilmaz", "PERSON_1"):
        assert leak not in json.dumps(line)


# ---- Auswertung (/api/report, Feld classification) --------------------------------------

def classified(original, anonymized=None, warned=False, credentials=False, **fields) -> dict:
    return entry(stufe_original=original, stufe_anonymisiert=anonymized, gewarnt=warned,
                 zugangsdaten=credentials, klassifikation_ms=40, **fields)


def test_report_counts_only_entries_with_classification(rules_file, tmp_path):
    path = tmp_path / "requests.jsonl"
    write_log(path,
              entry(),  # älterer Eintrag oder Flag aus
              classified("vertraulich", "oeffentlich", warned=True),
              classified("vertraulich", "intern", warned=True, credentials=True),
              classified("intern", "intern"),
              classified("oeffentlich"),
              classified(None))  # Laya nicht erreichbar

    c = report(path, "30d", now=NOW, rules=load_rules(rules_file))["classification"]

    assert c["requests"] == 5
    assert c["levels"] == [
        {"level": "oeffentlich", "name": "Öffentlich", "original": 1, "anonymized": 1},
        {"level": "intern", "name": "Intern", "original": 1, "anonymized": 2},
        {"level": "vertraulich", "name": "Vertraulich", "original": 2, "anonymized": 0},
    ]
    assert c["no_level"] == 1
    assert c["lowered"] == 2
    assert c["lowered_share"] == 0.6667  # von drei Einträgen mit beiden Stufen
    assert c["warned"] == 2
    assert c["warned_share"] == 0.4
    assert c["credentials"] == 1


def test_report_with_old_entries_only_has_empty_classification(tmp_path):
    path = tmp_path / "requests.jsonl"
    write_log(path, entry(), entry())

    c = report(path, "30d", now=NOW)["classification"]

    assert c == {"requests": 0, "levels": [], "no_level": 0, "lowered": None,
                 "lowered_share": None, "warned": 0, "warned_share": None, "credentials": 0}


def test_report_without_rules_cannot_tell_lowered(tmp_path):
    path = tmp_path / "requests.jsonl"
    write_log(path, classified("vertraulich", "oeffentlich"), classified("intern", "intern"))

    c = report(path, "30d", now=NOW)["classification"]

    assert [lv["level"] for lv in c["levels"]] == ["vertraulich", "oeffentlich", "intern"]
    assert c["levels"][0]["name"] == "vertraulich"
    assert c["lowered"] is None


def test_api_report_orders_levels_by_active_rules(enabled, tmp_path, monkeypatch):
    path = tmp_path / "requests.jsonl"
    write_log(path, classified("vertraulich", "oeffentlich", time=datetime.now(UTC).isoformat()))
    monkeypatch.setattr(config, "REQUEST_LOG", str(path))

    c = TestClient(app).get("/api/report").json()["classification"]

    assert [lv["name"] for lv in c["levels"]] == ["Öffentlich", "Intern", "Vertraulich"]
    assert c["lowered"] == 1
