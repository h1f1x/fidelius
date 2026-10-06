"""Auswertung des Request-Logs: Lesen, Zeitraum, Kennzahlen. Ohne Modelle, mit fester Uhr."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from fidelius.auswertung import auswerten

JETZT = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def test_missing_log_reports_path_and_no_entries(tmp_path):
    pfad = tmp_path / "requests.jsonl"

    a = auswerten(pfad, "30t", jetzt=JETZT)

    assert a["log"] == {"pfad": str(pfad), "vorhanden": False, "zeilen": 0, "kaputt": 0}
    assert a["kennzahlen"]["anfragen"] == 0


def eintrag(zeit="2026-10-06T10:00:00+00:00", **felder) -> dict:
    """Eine Logzeile wie aus pipeline._log_entry, harmloser Text ohne Fehler."""
    e = {
        "zeit": zeit,
        "build": {"version": "0.1.0", "number": 37, "commit": "0d15b11", "dirty": False, "time": None},
        "quelle": "anfrage", "zeichen": 1000, "gate_wert": 0.1, "schwelle": 0.5,
        "sensibel": False, "trotzdem": False, "laya_bestaetigung": True,
        "gate_ms": 100, "erkennung_ms": 0, "laya_ms": 0, "gesamt_ms": 120,
        "stellen": 0, "platzhalter": 0, "laya_abgelehnt": 0, "fehler": None,
    }
    e.update(felder)
    return e


def schreibe(pfad, *zeilen) -> None:
    pfad.write_text("".join((z if isinstance(z, str) else json.dumps(z)) + "\n" for z in zeilen),
                    encoding="utf-8")


def test_counts_requests_in_period_and_skips_broken_lines(tmp_path):
    pfad = tmp_path / "requests.jsonl"
    schreibe(pfad,
             eintrag("2026-10-06T11:00:00+00:00"),
             "{kaputt",
             eintrag("2026-10-05T13:00:00+00:00"),
             eintrag("2026-10-05T11:00:00+00:00"),  # älter als 24 h
             eintrag("2026-10-06T09:00:00+00:00", quelle="kalibrierung"),
             '{"zeit": "gestern"}')

    a = auswerten(pfad, "24h", jetzt=JETZT)

    assert a["log"] == {"pfad": str(pfad), "vorhanden": True, "zeilen": 6, "kaputt": 2}
    assert a["kennzahlen"]["anfragen"] == 2


def test_key_figures_use_nearest_rank(tmp_path):
    pfad = tmp_path / "requests.jsonl"
    fehler = "Laya nicht erreichbar (ConnectError); Gate übersprungen."
    schreibe(pfad, *[eintrag(gesamt_ms=ms, zeichen=2000, sensibel=ms <= 300,
                             fehler=fehler if ms > 800 else None)
                     for ms in (1000, 100, 900, 200, 800, 300, 700, 400, 600, 500)],
             eintrag(quelle="kalibrierung", gesamt_ms=99999, fehler="zählt nicht"))

    k = auswerten(pfad, "30t", jetzt=JETZT)["kennzahlen"]

    assert k == {"anfragen": 10, "gesamt_median_ms": 500, "gesamt_p90_ms": 900,
                 "je_1000_median_ms": 250.0, "fehler": 2, "fehlerquote": 0.2,
                 "sensibel_anteil": 0.3}


def test_line_without_numbers_counts_as_broken(tmp_path):
    pfad = tmp_path / "requests.jsonl"
    ohne = eintrag()
    del ohne["gesamt_ms"]
    schreibe(pfad, eintrag(), ohne, eintrag(zeichen="viel"), "[1, 2]")

    a = auswerten(pfad, "alles", jetzt=JETZT)

    assert a["log"]["kaputt"] == 3
    assert a["kennzahlen"]["anfragen"] == 1


def test_previous_period_for_24h_and_7_days(tmp_path):
    pfad = tmp_path / "requests.jsonl"
    schreibe(pfad,
             eintrag("2026-10-06T08:00:00+00:00", gesamt_ms=200),
             eintrag("2026-10-05T08:00:00+00:00", gesamt_ms=100),  # Vortag
             eintrag("2026-10-04T08:00:00+00:00", gesamt_ms=100))  # vor der Vorperiode

    assert auswerten(pfad, "24h", jetzt=JETZT)["vorperiode"]["anfragen"] == 1
    assert auswerten(pfad, "24h", jetzt=JETZT)["vorperiode"]["gesamt_median_ms"] == 100
    assert auswerten(pfad, "7t", jetzt=JETZT)["vorperiode"] is None  # Vorperiode leer
    assert auswerten(pfad, "30t", jetzt=JETZT)["vorperiode"] is None
    assert auswerten(pfad, "alles", jetzt=JETZT)["vorperiode"] is None


def test_phases_count_only_requests_where_they_ran(tmp_path):
    pfad = tmp_path / "requests.jsonl"
    schreibe(pfad,
             eintrag(gate_ms=100, erkennung_ms=0, laya_ms=0, gesamt_ms=120),  # harmlos
             eintrag(sensibel=True, gate_wert=0.9, gate_ms=200, erkennung_ms=300, laya_ms=400,
                     gesamt_ms=950),
             eintrag(trotzdem=True, laya_bestaetigung=False, gate_ms=50, erkennung_ms=600,
                     laya_ms=0, gesamt_ms=700),
             # Gate fehlgeschlagen: Erkennung läuft, die Laya-Bestätigung nicht
             eintrag(gate_wert=None, sensibel=True, fehler="Laya nicht erreichbar", gate_ms=10,
                     erkennung_ms=500, laya_ms=0, gesamt_ms=520))

    p = auswerten(pfad, "30t", jetzt=JETZT)["phasen"]

    assert p == {
        "gate": {"anzahl": 4, "median_ms": 50, "p90_ms": 200, "p99_ms": 200},
        "erkennung": {"anzahl": 3, "median_ms": 500, "p90_ms": 600, "p99_ms": 600},
        "laya": {"anzahl": 1, "median_ms": 400, "p90_ms": 400, "p99_ms": 400},
        "gesamt": {"anzahl": 4, "median_ms": 520, "p90_ms": 950, "p99_ms": 950},
    }
