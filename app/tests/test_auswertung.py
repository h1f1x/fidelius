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


def test_previous_period_for_all_but_everything(tmp_path):
    pfad = tmp_path / "requests.jsonl"
    schreibe(pfad,
             eintrag("2026-10-06T08:00:00+00:00", gesamt_ms=200),
             eintrag("2026-10-05T08:00:00+00:00", gesamt_ms=100),  # Vortag
             eintrag("2026-10-04T08:00:00+00:00", gesamt_ms=100),  # vor der Vorperiode
             eintrag("2026-08-20T08:00:00+00:00", gesamt_ms=300))  # Vorperiode von 30 Tagen

    assert auswerten(pfad, "24h", jetzt=JETZT)["vorperiode"]["anfragen"] == 1
    assert auswerten(pfad, "24h", jetzt=JETZT)["vorperiode"]["gesamt_median_ms"] == 100
    assert auswerten(pfad, "7t", jetzt=JETZT)["vorperiode"] is None  # Vorperiode leer
    assert auswerten(pfad, "30t", jetzt=JETZT)["vorperiode"]["anfragen"] == 1
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


def test_histogram_is_cut_at_p99(tmp_path):
    pfad = tmp_path / "requests.jsonl"
    schreibe(pfad, *[eintrag(gesamt_ms=ms) for ms in range(1, 101)])

    h = auswerten(pfad, "30t", jetzt=JETZT)["histogramm"]

    assert h["bis_ms"] == 99
    assert h["breite_ms"] == 4.125  # 24 Balken
    assert len(h["anzahl"]) == 24
    assert h["anzahl"][0] == 4      # 1–4 ms
    assert h["anzahl"][-1] == 6     # 95–99 ms und der Ausreißer 100 ms
    assert sum(h["anzahl"]) == 100


def test_length_classes_by_pages_of_3300_chars(tmp_path):
    pfad = tmp_path / "requests.jsonl"
    schreibe(pfad,
             eintrag(zeichen=3300, gesamt_ms=100),
             eintrag(zeichen=200, gesamt_ms=300),
             eintrag(zeichen=3301, gesamt_ms=1000),
             eintrag(zeichen=60000, gesamt_ms=9000))

    k = auswerten(pfad, "30t", jetzt=JETZT)["laengenklassen"]

    assert k == [
        {"label": "≤ 1 Seite", "bis_zeichen": 3300, "anzahl": 2, "median_ms": 100, "p90_ms": 300},
        {"label": "1–3 Seiten", "bis_zeichen": 9900, "anzahl": 1, "median_ms": 1000, "p90_ms": 1000},
        {"label": "3–7 Seiten", "bis_zeichen": 23100, "anzahl": 0, "median_ms": None, "p90_ms": None},
        {"label": "7–15 Seiten", "bis_zeichen": 49500, "anzahl": 0, "median_ms": None, "p90_ms": None},
        {"label": "> 15 Seiten", "bis_zeichen": None, "anzahl": 1, "median_ms": 9000, "p90_ms": 9000},
    ]


def test_scatter_has_one_point_per_request_with_build(tmp_path):
    pfad = tmp_path / "requests.jsonl"
    schreibe(pfad,
             eintrag(zeichen=500, gesamt_ms=700),
             eintrag(zeichen=900, gesamt_ms=1100, build={"number": None, "commit": "abc1234", "dirty": True}),
             eintrag(quelle="kalibrierung"))

    s = auswerten(pfad, "30t", jetzt=JETZT)["streuung"]

    assert s == [[500, 700, "#37 · 0d15b11"], [900, 1100, "#? · abc1234*"]]


def test_usage_by_day_and_hour_in_berlin_time(tmp_path):
    pfad = tmp_path / "requests.jsonl"
    schreibe(pfad,
             eintrag("2026-10-03T12:00:00+00:00"),
             eintrag("2026-10-05T22:30:00+00:00"),  # in Berlin schon der 6., 0:30 Uhr
             eintrag("2026-10-06T10:00:00+00:00"),
             eintrag("2026-10-06T10:00:00+00:00", quelle="kalibrierung"))

    n = auswerten(pfad, "alles", jetzt=JETZT)["nutzung"]

    assert n["tage"] == [{"tag": "2026-10-03", "anzahl": 1}, {"tag": "2026-10-04", "anzahl": 0},
                         {"tag": "2026-10-05", "anzahl": 0}, {"tag": "2026-10-06", "anzahl": 2}]
    assert n["stunden"] == [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1] + [0] * 9


def test_usage_uses_winter_time_and_covers_whole_period(tmp_path):
    pfad = tmp_path / "requests.jsonl"
    jetzt = datetime(2026, 1, 20, 12, 0, tzinfo=UTC)
    schreibe(pfad, eintrag("2026-01-15T23:30:00+00:00"))  # Berlin: 16.01., 0:30 Uhr

    n = auswerten(pfad, "7t", jetzt=jetzt)["nutzung"]

    assert [t["tag"] for t in n["tage"]] == [f"2026-01-{d}" for d in range(13, 21)]
    assert {"tag": "2026-01-16", "anzahl": 1} in n["tage"]
    assert n["stunden"][0] == 1


def build(nummer, commit="c0ffee0", dirty=False) -> dict:
    return {"version": "0.1.0", "number": nummer, "commit": commit, "dirty": dirty, "time": None}


def test_builds_compare_per_1000_chars_with_predecessor(tmp_path):
    pfad = tmp_path / "requests.jsonl"
    schreibe(pfad,
             eintrag("2026-10-01T08:00:00+00:00", build=build(36), zeichen=1000, gesamt_ms=2000),
             eintrag("2026-10-01T09:00:00+00:00", build=build(36), zeichen=1000, gesamt_ms=1000),
             eintrag("2026-10-02T08:00:00+00:00", build=build(36), quelle="kalibrierung"),
             eintrag("2026-10-03T08:00:00+00:00", build=build(37), zeichen=2000, gesamt_ms=1500),
             eintrag("2026-10-04T08:00:00+00:00", build=build(38, dirty=True), quelle="kalibrierung"),
             eintrag("2026-10-05T08:00:00+00:00", build=build(39), zeichen=1000, gesamt_ms=900))

    b = auswerten(pfad, "30t", jetzt=JETZT)["builds"]

    assert b[0] == {"name": "#36 · c0ffee0", "nummer": 36, "commit": "c0ffee0", "dirty": False,
                    "erste": "2026-10-01T10:00:00+02:00", "letzte": "2026-10-02T10:00:00+02:00",
                    "anfragen": 2, "median_ms": 1000, "p90_ms": 2000, "je_1000_median_ms": 1000.0,
                    "abweichung_vorgaenger": None}
    assert [x["name"] for x in b] == ["#36 · c0ffee0", "#37 · c0ffee0", "#38 · c0ffee0*",
                                      "#39 · c0ffee0"]
    assert [x["abweichung_vorgaenger"] for x in b] == [None, -0.25, None, 0.2]  # #38 hat keine Anfragen


def test_calibration_table_by_build_and_text_length(tmp_path):
    pfad = tmp_path / "requests.jsonl"
    kalib = {"quelle": "kalibrierung"}
    schreibe(pfad,
             *[eintrag(build=build(36), zeichen=515, gesamt_ms=ms, **kalib) for ms in (100, 300, 200)],
             eintrag(build=build(36), zeichen=7839, gesamt_ms=900, **kalib),
             eintrag(build=build(37), zeichen=1000, gesamt_ms=5000),  # Anfrage, keine Kalibrierung
             eintrag(build=build(38), zeichen=515, gesamt_ms=150, **kalib),
             eintrag(build=build(38), zeichen=1383, gesamt_ms=400, **kalib))

    k = auswerten(pfad, "30t", jetzt=JETZT)["kalibrierung"]

    assert k == {"texte": [515, 1383, 7839], "zeilen": [
        {"build": "#36 · c0ffee0", "laeufe": 4, "median_ms": [200, None, 900]},
        {"build": "#38 · c0ffee0", "laeufe": 2, "median_ms": [150, 400, None]},
    ]}


def test_errors_grouped_by_text_with_last_occurrence(tmp_path):
    pfad = tmp_path / "requests.jsonl"
    weg = "Laya nicht erreichbar (ConnectError); Gate übersprungen."
    zeit = " Laya-Bestätigung fehlgeschlagen (ReadTimeout)."
    schreibe(pfad,
             eintrag("2026-10-02T08:00:00+00:00", fehler=zeit),
             eintrag("2026-10-03T08:00:00+00:00", fehler=weg),
             eintrag("2026-10-04T08:00:00+00:00", fehler=weg, gesamt_ms=30),
             eintrag("2026-10-01T08:00:00+00:00", fehler=weg),
             eintrag("2026-10-05T08:00:00+00:00", fehler=weg, quelle="kalibrierung"))

    a = auswerten(pfad, "30t", jetzt=JETZT)

    assert a["fehler"] == [
        {"text": weg, "anzahl": 3, "zuletzt": "2026-10-04T10:00:00+02:00"},
        {"text": zeit.strip(), "anzahl": 1, "zuletzt": "2026-10-02T10:00:00+02:00"},
    ]
    assert a["phasen"]["gesamt"]["anzahl"] == 4  # Fehlschläge sind erlebte Laufzeit
