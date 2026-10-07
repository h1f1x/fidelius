"""Auswertung des Lasttests (scripts/loadtest_eval.py), Spec: docs/specs/lasttest.md, 2 und 7.

Ohne Netz und ohne Paket fidelius: Das Modul liegt unter scripts/ und braucht nur die
Standardbibliothek.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "loadtest_eval.py"


def _load():
    spec = importlib.util.spec_from_file_location("loadtest_eval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Wie bei einem normalen Import steht das Modul in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ev = _load()


def test_classify_sorts_responses_into_ok_degraded_and_failed():
    assert ev.classify(200, None) == "ok"
    assert ev.classify(200, "") == "ok"
    note = "Laya nicht erreichbar (HTTPStatusError); Gate übersprungen."
    assert ev.classify(200, note) == "degradiert"
    assert ev.classify(502, None) == "fehlgeschlagen"
    assert ev.classify(None, None, "ReadTimeout") == "fehlgeschlagen"
    assert ev.classify(200, None, "Antwort ist kein JSON") == "fehlgeschlagen"


def test_percentile_uses_nearest_rank_like_the_request_log_report():
    values = [50, 15, 40, 20, 35]  # Beispiel aus der Definition, absichtlich unsortiert

    assert ev.percentile(values, 30) == 20
    assert ev.percentile(values, 40) == 20
    assert ev.percentile(values, 50) == 35
    assert ev.percentile(values, 95) == 50
    assert ev.percentile([], 95) is None


T0 = datetime(2026, 10, 7, 18, 0, tzinfo=UTC)


def req(stufe=1, start_s=0.0, client_ms=6000, *, nutzer=1, aufwaermen=False, abschnitt="treppe",
        beispiel="01_schadenmeldung_kfz", status=200, gate_note=None, fehler=None,
        timing=None) -> dict:
    """Eine Zeile wie in requests.jsonl; Startzeit in Sekunden nach T0."""
    return {
        "abschnitt": abschnitt, "stufe": stufe, "nutzer": nutzer, "aufwaermen": aufwaermen,
        "beispiel": beispiel, "zeichen": 1003,
        "start": (T0 + timedelta(seconds=start_s)).isoformat(timespec="milliseconds"),
        "client_ms": client_ms, "status": status,
        "klasse": ev.classify(status, gate_note, fehler),
        "timing": timing if timing is not None or status != 200 else
        {"gate_ms": 1000, "detect_ms": 2000, "laya_check_ms": 2500, "total_ms": 5600},
        "gate_note": gate_note, "fehler": fehler,
    }


def test_stage_metrics_skip_warmup_and_count_finished_checks_per_minute():
    requests = [
        req(1, 0, 30000, aufwaermen=True),
        req(1, 30, 6000), req(1, 36, 6000), req(1, 42, 12000), req(1, 54, 6000),  # bis 60 s
    ]

    stage = ev.evaluate_run(requests)["stages"][0]

    assert stage["stage"] == 1
    assert stage["count"] == 4
    assert (stage["p50_ms"], stage["p95_ms"], stage["max_ms"]) == (6000, 12000, 12000)
    assert stage["throughput_per_min"] == 8.0  # 4 Prüfungen in 30 s


def test_failed_requests_enter_percentiles_with_their_time_but_not_throughput():
    note = "Laya nicht erreichbar (ReadTimeout); Gate übersprungen."
    requests = [
        req(1, 0, 6000), req(1, 6, 7000, gate_note=note),
        req(1, 13, 180000, status=None, fehler="Client-Timeout nach 180 s"),
        req(1, 193, 7000),  # bis 200 s
    ]

    stage = ev.evaluate_run(requests)["stages"][0]

    assert stage["classes"] == {"ok": 2, "degradiert": 1, "fehlgeschlagen": 1}
    assert stage["shares"] == {"ok": 0.5, "degradiert": 0.25, "fehlgeschlagen": 0.25}
    assert stage["p95_ms"] == 180000
    assert stage["throughput_per_min"] == 0.9  # 3 fertige Prüfungen in 200 s


def test_phase_medians_include_skipped_phases_and_rest_is_client_minus_server_time():
    def timing(gate, detect, laya, total):
        return {"gate_ms": gate, "detect_ms": detect, "laya_check_ms": laya, "total_ms": total}
    requests = [
        req(1, 0, 9000, timing=timing(1000, 3000, 4000, 8100)),
        req(1, 9, 1200, beispiel="04_terminabsprache_harmlos", timing=timing(900, 0, 0, 950)),
        req(1, 11, 6500, timing=timing(1100, 2000, 3000, 6200)),
        req(1, 18, 180000, status=None, fehler="Client-Timeout nach 180 s"),
    ]

    stage = ev.evaluate_run(requests)["stages"][0]

    assert stage["phases_ms"] == {"gate": 1000, "detect": 2000, "laya": 3000, "rest": 300}


def test_comfort_limit_is_highest_stage_with_p95_up_to_20s_below_the_first_break():
    note = "Laya nicht erreichbar (HTTPStatusError); Gate übersprungen."
    requests = [
        req(1, 0, 8000), req(1, 8, 8000),
        req(2, 20, 20000), req(2, 20, 25000, nutzer=2),
        req(4, 50, 12000), req(4, 50, 12000, nutzer=2, gate_note=note),
    ]

    result = ev.evaluate_run(requests)

    assert [(s["stage"], s["comfort"], s["breaks"]) for s in result["stages"]] == [
        (1, True, []), (2, False, []), (4, True, ["1 degradiert"])]
    assert result["c_star"] == 1
    assert result["break_stage"] == 4


def test_break_conditions_include_slow_p95_failed_warmup_and_container_restart():
    requests = [
        req(1, 0, 61000), req(1, 61, 61000),
        req(2, 200, 400, aufwaermen=True, status=502, fehler="HTTP 502"), req(2, 201, 8000),
        req(4, 300, 8000),
    ]
    stages = [{"abschnitt": "treppe", "stufe": 1, "container_bruch": []},
              {"abschnitt": "treppe", "stufe": 4, "container_bruch": ["laya: Neustart"]}]

    result = ev.evaluate_run(requests, stages)

    assert [s["breaks"] for s in result["stages"]] == [
        ["p95 über 60 s"], ["1 fehlgeschlagen (1 beim Aufwärmen)"], ["laya: Neustart"]]
    assert result["break_stage"] == 1
    assert result["c_star"] is None


def test_long_text_repetition_compares_p95_of_the_others_with_the_same_ladder_stage():
    def lang(start_s, client_ms, **kwargs):
        return req(2, start_s, client_ms, abschnitt="langtext", **kwargs)
    requests = [
        req(2, 0, 8000), req(2, 0, 10000, nutzer=2),
        lang(100, 50000, beispiel="langtext", aufwaermen=True),
        lang(150, 40000, beispiel="langtext"),
        lang(100, 20000, nutzer=2, aufwaermen=True),
        lang(120, 9000, nutzer=2), lang(129, 15000, nutzer=2), lang(144, 14000, nutzer=2),
    ]

    result = ev.evaluate_run(requests)

    longtext = result["longtext"]
    assert longtext["stage"] == 2
    assert longtext["ladder_p95_ms"] == 10000
    assert (longtext["others"]["count"], longtext["others"]["p95_ms"]) == (3, 15000)
    assert longtext["long"]["max_ms"] == 40000
    assert [s["stage"] for s in result["stages"]] == [2]  # die Wiederholung ist keine Stufe


def test_run_without_long_text_part_has_no_comparison():
    assert ev.evaluate_run([req(1, 0, 8000)])["longtext"] is None


def test_ram_peak_is_highest_memtotal_minus_memavailable_over_all_samples():
    gib = 1024 ** 3
    samples = [{"mem_total_bytes": 8 * gib, "mem_available_bytes": 2 * gib},
               {"mem_total_bytes": 8 * gib, "mem_available_bytes": gib // 2},
               {"mem_total_bytes": None, "mem_available_bytes": None}]  # ssh-Ausgabe kaputt

    assert ev.evaluate_run([], samples=samples)["ram_peak_bytes"] == 7.5 * gib
    assert ev.evaluate_run([])["ram_peak_bytes"] is None


def test_sweet_spot_is_smallest_size_by_vcpu_then_ram_that_holds_the_target_load():
    gb = 10 ** 9
    runs = [
        {"name": "lauf-0", "vcpu": 8, "ram_bytes": 8 * gb, "c_star": 2},
        {"name": "lauf-1", "vcpu": 8, "ram_bytes": 16 * gb, "c_star": 4},
        {"name": "lauf-2", "vcpu": 4, "ram_bytes": 16 * gb, "c_star": 1},
        {"name": "lauf-3", "vcpu": 16, "ram_bytes": 16 * gb, "c_star": 6},
        {"name": "lauf-4", "vcpu": 16, "ram_bytes": 16 * gb, "c_star": None},
        {"name": "lokal", "vcpu": None, "ram_bytes": None, "c_star": 8},  # ohne VM: keine Größe
    ]

    assert ev.sweet_spot(runs)["name"] == "lauf-1"  # Ziellast 4
    assert ev.sweet_spot(runs, target=2)["name"] == "lauf-0"
    assert ev.sweet_spot(runs, target=5)["name"] == "lauf-3"
    assert ev.sweet_spot(runs, target=8) is None


def log_entry(end_s: float, gesamt_ms: int, quelle="anfrage") -> dict:
    """Eine Zeile aus dem Request-Log der App, nur mit den Feldern, die hier zählen."""
    return {"zeit": (T0 + timedelta(seconds=end_s)).isoformat(timespec="seconds"),
            "gesamt_ms": gesamt_ms, "quelle": quelle, "zeichen": 1000}


def test_concurrency_counts_the_peak_during_each_check_not_all_overlapping_checks():
    entries = [
        log_entry(10, 10000),  # A läuft 0–10 s
        log_entry(2, 1000),    # B 1–2 s, in A
        log_entry(4, 1000),    # C 3–4 s, in A, aber nicht neben B
        log_entry(30, 10000),  # D 20–30 s allein
        log_entry(35, 5000),   # E 30–35 s, beginnt, als D endet
        log_entry(10, 10000, quelle="lasttest"),
        log_entry(10, 10000, quelle="kalibrierung"),
        {"zeit": "kaputt", "gesamt_ms": 100, "quelle": "anfrage"},
    ]

    result = ev.concurrency(entries)

    # Je Prüfung: A 2, B 2, C 2, D 1, E 1. Über alle Überlappungen gezählt hätte A 3.
    assert result == {"requests": 5, "max": 2, "p99": 2}


def test_concurrency_p99_ignores_a_rare_burst():
    entries = [log_entry(10 * i + 5, 5000) for i in range(200)]  # nacheinander, je 5 s
    entries.append(log_entry(10 * 50 + 5, 5000))                 # einmal zwei gleichzeitig

    result = ev.concurrency(entries)

    assert result == {"requests": 201, "max": 2, "p99": 1}


def test_concurrency_without_checks_has_no_values():
    assert ev.concurrency([log_entry(10, 1000, quelle="kalibrierung")]) == {
        "requests": 0, "max": None, "p99": None}


def test_read_run_loads_the_three_files_and_skips_broken_lines(tmp_path):
    run_dir = tmp_path / "2026-10-07-1800-8cpu-4t-probe"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({"vcpu": 8, "threads": 4}), encoding="utf-8")
    (run_dir / "requests.jsonl").write_text(
        json.dumps(req(1, 0, 6000)) + "\n{abgebrochen\n\n" + json.dumps(req(1, 6, 7000)) + "\n",
        encoding="utf-8")

    run = ev.read_run(run_dir)

    assert run["name"] == "2026-10-07-1800-8cpu-4t-probe"
    assert run["run"] == {"vcpu": 8, "threads": 4}
    assert [r["client_ms"] for r in run["requests"]] == [6000, 7000]
    assert run["samples"] == []  # ohne VM gibt es keine Messwerte


def container(restart_count=0, oom_killed=False, started_at="2026-10-07T17:00:00Z", id="a1"):
    """Ein Container wie in docker_inspect_vorher/-nachher aus run.json."""
    return {"id": id, "status": "running", "restart_count": restart_count,
            "oom_killed": oom_killed, "started_at": started_at, "omp_num_threads": "4"}


def test_container_breaks_report_restart_and_oom_kill_since_the_previous_inspect():
    before = {"app": container(), "laya": container(restart_count=2, id="b2")}
    after = {"app": container(),
             "laya": container(restart_count=3, oom_killed=True, id="b2",
                               started_at="2026-10-07T18:05:00Z")}

    assert ev.container_breaks(before, before) == []
    assert ev.container_breaks(before, after) == ["laya: RestartCount 2 → 3", "laya: OOMKilled"]


def test_container_breaks_notice_manual_restart_and_missing_container():
    before = {"app": container(), "laya": container(id="b2")}
    after = {"app": container(started_at="2026-10-07T18:05:00Z")}

    assert ev.container_breaks(before, after) == ["app: neu gestartet", "laya: fehlt"]
