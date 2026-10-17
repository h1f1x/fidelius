"""Auswertung der Kalibrierbeispiele (scripts/run_classification.py), Spec: docs/specs/klassifikation.md, 9.

Ohne Netz und ohne Paket fidelius: Das Skript liegt unter scripts/ und braucht nur die
Standardbibliothek. Die Antworten sind gebaut wie die von POST /api/classify.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_classification.py"
LEVELS = ["oeffentlich", "intern", "vertraulich", "streng_vertraulich"]


def _load():
    spec = importlib.util.spec_from_file_location("run_classification", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rc = _load()


def answer(level: str, *credentials: float | None) -> dict:
    """Antwort von /api/classify mit einem Abschnitt je Zugangsdaten-Wert."""
    probs = {lv: (0.9 if lv == level else 0.02) for lv in LEVELS}
    chunks = [{"start": 0, "end": 600, "level": level, "probabilities": probs, "credentials": c}
              for c in (credentials or (None,))]
    return {"level": level, "chunk": {"start": 0, "end": 600}, "chunks": chunks}


def test_matrix_counts_expected_against_actual_level():
    expected = {
        "a": {"stufe": "intern"},
        "b": {"stufe": "intern"},
        "c": {"stufe": "vertraulich"},
    }
    results = {"a": answer("intern"), "b": answer("vertraulich"), "c": answer("vertraulich")}

    ev = rc.evaluate(expected, results, credentials_threshold=0.5)

    assert ev.matrix["intern"]["intern"] == 1
    assert ev.matrix["intern"]["vertraulich"] == 1
    assert ev.matrix["vertraulich"]["vertraulich"] == 1
    assert ev.matrix["vertraulich"]["intern"] == 0
    assert ev.levels_hit == 2
    assert ev.misses == [("b", "intern", "vertraulich")]


def test_credentials_count_when_one_chunk_reaches_threshold():
    expected = {
        "mit_passwort": {"stufe": "vertraulich", "zugangsdaten": True},
        "mit_token": {"stufe": "vertraulich", "zugangsdaten": True},
        "ohne": {"stufe": "intern", "zugangsdaten": False},
        "ohne_feld": {"stufe": "intern"},
    }
    results = {
        "mit_passwort": answer("vertraulich", 0.1, 0.5),   # zweiter Abschnitt genau auf der Schwelle
        "mit_token": answer("vertraulich", 0.49),          # knapp darunter: übersehen
        "ohne": answer("intern", 0.7),                     # Fehlalarm
        "ohne_feld": answer("intern", None),               # zugang nicht gefragt
    }

    ev = rc.evaluate(expected, results, credentials_threshold=0.5)

    assert (ev.credentials_hit, ev.credentials_total) == (1, 2)
    assert ev.credentials_missed == ["mit_token"]
    assert ev.credentials_false == ["ohne"]


def test_matrix_prints_rows_expected_and_columns_actual_in_rank_order():
    expected = {"a": {"stufe": "intern"}, "b": {"stufe": "intern"}, "c": {"stufe": "streng_vertraulich"}}
    results = {"a": answer("intern"), "b": answer("vertraulich"), "c": answer("streng_vertraulich")}

    lines = rc.format_matrix(rc.evaluate(expected, results, credentials_threshold=0.5)).splitlines()

    assert lines[0].split()[-4:] == LEVELS
    assert [line.split() for line in lines[1:]] == [
        ["oeffentlich", "0", "0", "0", "0"],
        ["intern", "0", "1", "1", "0"],
        ["vertraulich", "0", "0", "0", "0"],
        ["streng_vertraulich", "0", "0", "0", "1"],
    ]
    # Spalten stehen untereinander: Jede Zahl endet dort, wo ihr Stufenname im Kopf endet.
    assert {len(line) for line in lines} == {len(lines[0])}
