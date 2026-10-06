"""Auswertung des Request-Logs: Lesen, Zeitraum, Kennzahlen. Ohne Modelle, mit fester Uhr."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from fidelius.log_report import report

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def test_missing_log_reports_path_and_no_entries(tmp_path):
    path = tmp_path / "requests.jsonl"

    result = report(path, "30d", now=NOW)

    assert result["log"] == {"path": str(path), "present": False, "lines": 0, "broken": 0}
    assert result["metrics"]["requests"] == 0


def entry(time="2026-10-06T10:00:00+00:00", **fields) -> dict:
    """Eine Logzeile wie aus pipeline._log_entry, harmloser Text ohne Fehler."""
    line = {
        "zeit": time,
        "build": {"version": "0.1.0", "number": 37, "commit": "0d15b11", "dirty": False, "time": None},
        "quelle": "anfrage", "zeichen": 1000, "gate_wert": 0.1, "schwelle": 0.5,
        "sensibel": False, "trotzdem": False, "laya_bestaetigung": True,
        "gate_ms": 100, "erkennung_ms": 0, "laya_ms": 0, "gesamt_ms": 120,
        "stellen": 0, "platzhalter": 0, "laya_abgelehnt": 0, "fehler": None,
    }
    line.update(fields)
    return line


def write_log(path, *lines) -> None:
    path.write_text("".join((line if isinstance(line, str) else json.dumps(line)) + "\n"
                            for line in lines), encoding="utf-8")


def test_counts_requests_in_period_and_skips_broken_lines(tmp_path):
    path = tmp_path / "requests.jsonl"
    write_log(path,
              entry("2026-10-06T11:00:00+00:00"),
              "{kaputt",
              entry("2026-10-05T13:00:00+00:00"),
              entry("2026-10-05T11:00:00+00:00"),  # älter als 24 h
              entry("2026-10-06T09:00:00+00:00", quelle="kalibrierung"),
              '{"zeit": "gestern"}')

    result = report(path, "24h", now=NOW)

    assert result["log"] == {"path": str(path), "present": True, "lines": 6, "broken": 2}
    assert result["metrics"]["requests"] == 2


def test_key_figures_use_nearest_rank(tmp_path):
    path = tmp_path / "requests.jsonl"
    error = "Laya nicht erreichbar (ConnectError); Gate übersprungen."
    write_log(path, *[entry(gesamt_ms=ms, zeichen=2000, sensibel=ms <= 300,
                            fehler=error if ms > 800 else None)
                      for ms in (1000, 100, 900, 200, 800, 300, 700, 400, 600, 500)],
              entry(quelle="kalibrierung", gesamt_ms=99999, fehler="zählt nicht"))

    metrics = report(path, "30d", now=NOW)["metrics"]

    assert metrics == {"requests": 10, "total_median_ms": 500, "total_p90_ms": 900,
                       "per_1000_median_ms": 250.0, "error_count": 2, "error_rate": 0.2,
                       "sensitive_share": 0.3}


def test_line_without_numbers_counts_as_broken(tmp_path):
    path = tmp_path / "requests.jsonl"
    without_total = entry()
    del without_total["gesamt_ms"]
    write_log(path, entry(), without_total, entry(zeichen="viel"), "[1, 2]")

    result = report(path, "all", now=NOW)

    assert result["log"]["broken"] == 3
    assert result["metrics"]["requests"] == 1


def test_previous_period_for_all_but_everything(tmp_path):
    path = tmp_path / "requests.jsonl"
    write_log(path,
              entry("2026-10-06T08:00:00+00:00", gesamt_ms=200),
              entry("2026-10-05T08:00:00+00:00", gesamt_ms=100),  # Vortag
              entry("2026-10-04T08:00:00+00:00", gesamt_ms=100),  # vor der Vorperiode
              entry("2026-08-20T08:00:00+00:00", gesamt_ms=300))  # Vorperiode von 30 Tagen

    assert report(path, "24h", now=NOW)["previous"]["requests"] == 1
    assert report(path, "24h", now=NOW)["previous"]["total_median_ms"] == 100
    assert report(path, "7d", now=NOW)["previous"] is None  # Vorperiode leer
    assert report(path, "30d", now=NOW)["previous"]["requests"] == 1
    assert report(path, "all", now=NOW)["previous"] is None


def test_phases_count_only_requests_where_they_ran(tmp_path):
    path = tmp_path / "requests.jsonl"
    write_log(path,
              entry(gate_ms=100, erkennung_ms=0, laya_ms=0, gesamt_ms=120),  # harmlos
              entry(sensibel=True, gate_wert=0.9, gate_ms=200, erkennung_ms=300, laya_ms=400,
                    gesamt_ms=950),
              entry(trotzdem=True, laya_bestaetigung=False, gate_ms=50, erkennung_ms=600,
                    laya_ms=0, gesamt_ms=700),
              # Gate fehlgeschlagen: Erkennung läuft, die Laya-Bestätigung nicht
              entry(gate_wert=None, sensibel=True, fehler="Laya nicht erreichbar", gate_ms=10,
                    erkennung_ms=500, laya_ms=0, gesamt_ms=520))

    phases = report(path, "30d", now=NOW)["phases"]

    assert phases == {
        "gate": {"count": 4, "median_ms": 50, "p90_ms": 200, "p99_ms": 200},
        "detection": {"count": 3, "median_ms": 500, "p90_ms": 600, "p99_ms": 600},
        "laya": {"count": 1, "median_ms": 400, "p90_ms": 400, "p99_ms": 400},
        "total": {"count": 4, "median_ms": 520, "p90_ms": 950, "p99_ms": 950},
    }


def test_histogram_is_cut_at_p99(tmp_path):
    path = tmp_path / "requests.jsonl"
    write_log(path, *[entry(gesamt_ms=ms) for ms in range(1, 101)])

    histogram = report(path, "30d", now=NOW)["histogram"]

    assert histogram["max_ms"] == 99
    assert histogram["width_ms"] == 4.125  # 24 Balken
    assert len(histogram["counts"]) == 24
    assert histogram["counts"][0] == 4      # 1–4 ms
    assert histogram["counts"][-1] == 6     # 95–99 ms und der Ausreißer 100 ms
    assert sum(histogram["counts"]) == 100


def test_length_classes_by_pages_of_3300_chars(tmp_path):
    path = tmp_path / "requests.jsonl"
    write_log(path,
              entry(zeichen=3300, gesamt_ms=100),
              entry(zeichen=200, gesamt_ms=300),
              entry(zeichen=3301, gesamt_ms=1000),
              entry(zeichen=60000, gesamt_ms=9000))

    result = report(path, "30d", now=NOW)

    assert result["page_chars"] == 3300
    assert result["length_classes"] == [
        {"label": "≤ 1 Seite", "max_chars": 3300, "count": 2, "median_ms": 100, "p90_ms": 300},
        {"label": "1–3 Seiten", "max_chars": 9900, "count": 1, "median_ms": 1000, "p90_ms": 1000},
        {"label": "3–7 Seiten", "max_chars": 23100, "count": 0, "median_ms": None, "p90_ms": None},
        {"label": "7–15 Seiten", "max_chars": 49500, "count": 0, "median_ms": None, "p90_ms": None},
        {"label": "> 15 Seiten", "max_chars": None, "count": 1, "median_ms": 9000, "p90_ms": 9000},
    ]


def test_scatter_has_one_point_per_request_with_build(tmp_path):
    path = tmp_path / "requests.jsonl"
    write_log(path,
              entry(zeichen=500, gesamt_ms=700),
              entry(zeichen=900, gesamt_ms=1100, build={"number": None, "commit": "abc1234", "dirty": True}),
              entry(quelle="kalibrierung"))

    scatter = report(path, "30d", now=NOW)["scatter"]

    assert scatter == [[500, 700, "#37 · 0d15b11"], [900, 1100, "#? · abc1234*"]]


def test_usage_by_day_and_hour_in_berlin_time(tmp_path):
    path = tmp_path / "requests.jsonl"
    write_log(path,
              entry("2026-10-03T12:00:00+00:00"),
              entry("2026-10-05T22:30:00+00:00"),  # in Berlin schon der 6., 0:30 Uhr
              entry("2026-10-06T10:00:00+00:00"),
              entry("2026-10-06T10:00:00+00:00", quelle="kalibrierung"))

    usage = report(path, "all", now=NOW)["usage"]

    assert usage["days"] == [{"day": "2026-10-03", "count": 1}, {"day": "2026-10-04", "count": 0},
                             {"day": "2026-10-05", "count": 0}, {"day": "2026-10-06", "count": 2}]
    assert usage["hours"] == [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1] + [0] * 9


def test_usage_uses_winter_time_and_covers_whole_period(tmp_path):
    path = tmp_path / "requests.jsonl"
    now = datetime(2026, 1, 20, 12, 0, tzinfo=UTC)
    write_log(path, entry("2026-01-15T23:30:00+00:00"))  # Berlin: 16.01., 0:30 Uhr

    usage = report(path, "7d", now=now)["usage"]

    assert [d["day"] for d in usage["days"]] == [f"2026-01-{d}" for d in range(13, 21)]
    assert {"day": "2026-01-16", "count": 1} in usage["days"]
    assert usage["hours"][0] == 1


def build(number, commit="c0ffee0", dirty=False) -> dict:
    return {"version": "0.1.0", "number": number, "commit": commit, "dirty": dirty, "time": None}


def test_builds_compare_per_1000_chars_with_predecessor(tmp_path):
    path = tmp_path / "requests.jsonl"
    write_log(path,
              entry("2026-10-01T08:00:00+00:00", build=build(36), zeichen=1000, gesamt_ms=2000),
              entry("2026-10-01T09:00:00+00:00", build=build(36), zeichen=1000, gesamt_ms=1000),
              entry("2026-10-02T08:00:00+00:00", build=build(36), quelle="kalibrierung"),
              entry("2026-10-03T08:00:00+00:00", build=build(37), zeichen=2000, gesamt_ms=1500),
              entry("2026-10-04T08:00:00+00:00", build=build(38, dirty=True), quelle="kalibrierung"),
              entry("2026-10-05T08:00:00+00:00", build=build(39), zeichen=1000, gesamt_ms=900))

    builds = report(path, "30d", now=NOW)["builds"]

    assert builds[0] == {"name": "#36 · c0ffee0", "number": 36, "commit": "c0ffee0", "dirty": False,
                         "first": "2026-10-01T10:00:00+02:00", "last": "2026-10-02T10:00:00+02:00",
                         "requests": 2, "median_ms": 1000, "p90_ms": 2000,
                         "per_1000_median_ms": 1000.0, "change_vs_previous": None}
    assert [b["name"] for b in builds] == ["#36 · c0ffee0", "#37 · c0ffee0", "#38 · c0ffee0*",
                                           "#39 · c0ffee0"]
    # #38 hat keine Anfragen
    assert [b["change_vs_previous"] for b in builds] == [None, -0.25, None, 0.2]


def test_calibration_table_by_build_and_text_length(tmp_path):
    path = tmp_path / "requests.jsonl"
    calibration = {"quelle": "kalibrierung"}
    write_log(path,
              *[entry(build=build(36), zeichen=515, gesamt_ms=ms, **calibration)
                for ms in (100, 300, 200)],
              entry(build=build(36), zeichen=7839, gesamt_ms=900, **calibration),
              entry(build=build(37), zeichen=1000, gesamt_ms=5000),  # Anfrage, keine Kalibrierung
              entry(build=build(38), zeichen=515, gesamt_ms=150, **calibration),
              entry(build=build(38), zeichen=1383, gesamt_ms=400, **calibration))

    result = report(path, "30d", now=NOW)["calibration"]

    assert result == {"texts": [515, 1383, 7839], "rows": [
        {"build": "#36 · c0ffee0", "runs": 4, "median_ms": [200, None, 900]},
        {"build": "#38 · c0ffee0", "runs": 2, "median_ms": [150, 400, None]},
    ]}


def test_errors_grouped_by_text_with_last_occurrence(tmp_path):
    path = tmp_path / "requests.jsonl"
    unreachable = "Laya nicht erreichbar (ConnectError); Gate übersprungen."
    timeout = " Laya-Bestätigung fehlgeschlagen (ReadTimeout)."
    write_log(path,
              entry("2026-10-02T08:00:00+00:00", fehler=timeout),
              entry("2026-10-03T08:00:00+00:00", fehler=unreachable),
              entry("2026-10-04T08:00:00+00:00", fehler=unreachable, gesamt_ms=30),
              entry("2026-10-01T08:00:00+00:00", fehler=unreachable),
              entry("2026-10-05T08:00:00+00:00", fehler=unreachable, quelle="kalibrierung"))

    result = report(path, "30d", now=NOW)

    assert result["errors"] == [
        {"text": unreachable, "count": 3, "last": "2026-10-04T10:00:00+02:00"},
        {"text": timeout.strip(), "count": 1, "last": "2026-10-02T10:00:00+02:00"},
    ]
    assert result["phases"]["total"]["count"] == 4  # Fehlschläge sind erlebte Laufzeit


def test_predecessor_comes_from_whole_log(tmp_path):
    path = tmp_path / "requests.jsonl"
    write_log(path,
              entry("2026-09-10T08:00:00+00:00", build=build(35), zeichen=1000, gesamt_ms=800),
              entry("2026-09-20T08:00:00+00:00", build=build(36), zeichen=1000, gesamt_ms=2000),
              entry("2026-09-21T08:00:00+00:00", build=build(36), zeichen=1000, gesamt_ms=2000),
              entry("2026-10-01T08:00:00+00:00", build=build(36), zeichen=1000, gesamt_ms=1000),
              entry("2026-10-03T08:00:00+00:00", build=build(37), zeichen=1000, gesamt_ms=1500))

    builds = report(path, "7d", now=NOW)["builds"]

    # #36 vergleicht mit #35 außerhalb des Zeitraums, #37 mit dem Wert von #36 über das ganze
    # Log (2.000 ms je 1.000 Zeichen), nicht nur mit dem im Zeitraum (1.000 ms).
    assert [b["name"] for b in builds] == ["#36 · c0ffee0", "#37 · c0ffee0"]
    assert [b["per_1000_median_ms"] for b in builds] == [1000.0, 1500.0]
    assert [b["change_vs_previous"] for b in builds] == [0.25, -0.25]
