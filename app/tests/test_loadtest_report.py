"""HTML-Bericht über Lasttest-Läufe (scripts/loadtest_report.py), Spec: docs/specs/lasttest.md, 6.

Die Tests lesen den Bericht wie ein Mensch: sichtbarer Text und Tooltips (<title> in den SVGs) je
Abschnitt. Die Abschnitte tragen feste ids, damit ein Test weiß, in welcher Grafik er liest.
"""
from __future__ import annotations

import importlib
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load():
    # Der Bericht importiert loadtest_eval wie loadtest.py, also aus seinem eigenen Verzeichnis.
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module("loadtest_report")


report = _load()

GIB = 2 ** 30
T0 = datetime(2026, 10, 7, 18, 0, tzinfo=UTC)


class Page(HTMLParser):
    """Text und Tooltips des Berichts, getrennt nach <section id=…>."""

    def __init__(self, html: str):
        super().__init__()
        self.html = html
        self.tags: list[tuple[str, dict]] = []
        self._texts: dict[str | None, list[str]] = defaultdict(list)
        self._titles: dict[str | None, list[str]] = defaultdict(list)
        self._rows: dict[str | None, list[list[str]]] = defaultdict(list)
        self._cell: list[str] | None = None
        self._section: str | None = None
        self._in: list[str] = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == "section":
            self._section = attrs.get("id")
        if tag in ("title", "style", "script"):
            self._in.append(tag)
        if tag == "tr":
            self._rows[self._section].append([])
        if tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "section":
            self._section = None
        if tag in ("td", "th") and self._cell is not None:
            self._rows[self._section][-1].append(" ".join(" ".join(self._cell).split()))
            self._cell = None
        if self._in and self._in[-1] == tag:
            self._in.pop()

    def handle_data(self, data):
        if "style" in self._in or "script" in self._in:
            return
        target = self._titles if "title" in self._in else self._texts
        target[self._section].append(data)
        if self._cell is not None and "title" not in self._in:
            self._cell.append(data)

    def text(self, section: str | None = None) -> str:
        """Sichtbarer Text eines Abschnitts, Leerraum zusammengefasst; ohne section alles."""
        parts = self._texts[section] if section else [t for ts in self._texts.values() for t in ts]
        return " ".join(" ".join(parts).split())

    def rows(self, section: str) -> list[list[str]]:
        """Zeilen der Tabellen eines Abschnitts als Zelltexte, Kopfzeilen eingeschlossen."""
        return self._rows[section]

    def tooltips(self, section: str) -> list[str]:
        return [" ".join(t.split()) for t in self._titles[section]]


def ladder(times: dict[int, list[int]]) -> list[dict]:
    """requests.jsonl einer Treppe: je Stufe die Client-Zeiten der gezählten Anfragen in ms,
    nacheinander ab T0, alle ok. Gate 1 s, Erkennung 2 s, Laya 2,5 s, Rest 100 ms."""
    rows, t = [], 0.0
    for stage, values in times.items():
        for ms in values:
            rows.append(request(stage, t, ms))
            t += ms / 1000
    return rows


def request(stage, start_s, client_ms, *, abschnitt="treppe", beispiel="01_schadenmeldung_kfz",
            status=200, gate_note=None, fehler=None, nutzer=1) -> dict:
    klasse = "fehlgeschlagen" if status != 200 or fehler else "degradiert" if gate_note else "ok"
    return {
        "abschnitt": abschnitt, "stufe": stage, "nutzer": nutzer, "aufwaermen": False,
        "beispiel": beispiel, "zeichen": 1000,
        "start": (T0 + timedelta(seconds=start_s)).isoformat(timespec="milliseconds"),
        "client_ms": client_ms, "status": status, "klasse": klasse,
        "timing": {"gate_ms": 1000, "detect_ms": 2000, "laya_check_ms": 2500,
                   "total_ms": client_ms - 100} if status == 200 else None,
        "gate_note": gate_note, "fehler": fehler,
    }


TUNNEL = {"url": "http://127.0.0.1:50000", "vm": True,
          "tunnel": {"host": "felix@dev-vm", "jump": None, "ziel": "127.0.0.1:8080"}}
CADDY = {"url": "https://fidelius.example", "vm": True, "tunnel": None}
LOCAL = {"url": "http://localhost:8080", "vm": False, "tunnel": None}


def a_run(name, times=None, *, vcpu=8, ram_gib=16, threads=4, requests=(), samples=(),
          stufen=(), zugang=None) -> dict:
    """Ein Lauf, wie read_run() ihn liefert. ram_gib=None: ohne VM gemessen. Ohne zugang lief
    er über den SSH-Tunnel, ohne VM über --url."""
    return {
        "name": name,
        "run": {"vcpu": vcpu, "ram_bytes": ram_gib * GIB if ram_gib else None,
                "threads": threads, "zeit": T0.isoformat(timespec="milliseconds"),
                "stufen": list(stufen), "zugang": zugang or (TUNNEL if ram_gib else LOCAL)},
        "requests": ladder(times or {}) + list(requests),
        "samples": list(samples),
    }


def test_report_is_one_file_without_scripts_or_external_resources():
    html = report.render([a_run("lauf-0", {1: [6000] * 3})])

    page = Page(html)
    assert not [tag for tag, _ in page.tags if tag in ("script", "link", "img", "iframe")]
    assert not [value for _, attrs in page.tags for key, value in attrs.items()
                if key in ("src", "href") and value and "//" in value]
    assert "<style>" in html and "prefers-color-scheme: dark" in html


def test_names_from_the_results_directory_are_escaped():
    page = Page(report.render([a_run('lauf-<b>"1"</b>&', {1: [6000] * 3})]))

    assert "b" not in [tag for tag, _ in page.tags]
    assert 'lauf-<b>"1"</b>&' in page.text("kopf")
    assert 'lauf-<b>"1"</b>& · Stufe 1: p50 6,0 s, p95 6,0 s' in page.tooltips("antwortzeit")


def test_head_names_the_smallest_size_that_holds_the_target_load_as_sweet_spot():
    runs = [
        a_run("lauf-0", {1: [6000] * 3, 2: [12000] * 3, 4: [30000] * 3}, ram_gib=8),  # c* 2
        a_run("lauf-1", {1: [5000] * 3, 2: [8000] * 3, 4: [15000] * 3}, ram_gib=16),  # c* 4
        a_run("lauf-3", {4: [9000] * 3, 6: [14000] * 3}, vcpu=16, ram_gib=16),        # c* 6
    ]

    assert "Sweet Spot: 8 vCPU, 16,0 GiB RAM" in Page(report.render(runs)).text("kopf")
    assert "Sweet Spot: 8 vCPU, 8,0 GiB RAM" in Page(report.render(runs, target=2)).text("kopf")


def test_head_says_why_there_is_no_sweet_spot():
    slow = a_run("lauf-0", {1: [6000] * 3, 2: [25000] * 3})  # c* 1
    local = a_run("lokal", {1: [5000] * 3, 4: [9000] * 3}, vcpu=None, ram_gib=None, threads=None)

    assert ("Kein Sweet Spot: Keine gemessene Größe hält 4 gleichzeitige Prüfungen"
            in Page(report.render([slow, local])).text("kopf"))
    assert ("Kein Sweet Spot: Kein Lauf lief über den SSH-Tunnel auf einer VM bekannter Größe"
            in Page(report.render([local])).text("kopf"))


def test_head_names_the_runs_that_do_not_count_for_the_sweet_spot_and_why():
    tunnel = a_run("lauf-1", {1: [5000] * 3, 4: [15000] * 3})
    caddy = a_run("caddy", {4: [9000] * 3}, vcpu=4, ram_gib=8, zugang=CADDY)  # kleiner, c* 4
    local = a_run("lokal", {1: [5000] * 3, 4: [9000] * 3}, vcpu=None, ram_gib=None, threads=None)

    text = Page(report.render([tunnel, caddy, local])).text("kopf")

    assert "Sweet Spot: 8 vCPU, 16,0 GiB RAM" in text
    assert ("Nicht im Sweet Spot, weil nur Läufe über den SSH-Tunnel zählen: "
            "caddy (über --url statt SSH-Tunnel), lokal (ohne VM)") in text


def test_run_table_shows_size_limits_throughput_and_worst_case_per_run():
    vm = a_run("lauf-1", {1: [6000] * 3, 2: [8000] * 3, 4: [12000] * 3,
                          10: [50000, 55000, 70000]},
               samples=[{"mem_total_bytes": 16 * GIB, "mem_available_bytes": 10 * GIB}])
    local = a_run("lokal", {1: [5000] * 3}, vcpu=None, ram_gib=None, threads=None)

    rows = Page(report.render([vm, local])).rows("kopf")

    assert rows == [
        ["Lauf", "vCPU", "RAM", "Threads", "c*", "Bruchstufe", "Durchsatz bei c* (Prüf./min)",
         "p95 bei Stufe 10", "RAM-Spitze"],
        ["lauf-1", "8", "16,0 GiB", "4", "4", "10", "5,0", "70,0 s", "6,0 GiB"],
        ["lokal", "–", "–", "–", "1", "keine", "12,0", "–", "–"],
    ]


def test_head_recommends_the_highest_ram_peak_of_all_runs_plus_a_quarter():
    def used(gib):
        return [{"mem_total_bytes": 16 * GIB, "mem_available_bytes": (16 - gib) * GIB}]
    runs = [a_run("lauf-0", {1: [6000] * 3}, samples=used(6)),
            a_run("lauf-1", {1: [6000] * 3}, samples=used(8)),
            a_run("lokal", {1: [6000] * 3}, vcpu=None, ram_gib=None, threads=None)]

    assert ("Empfohlener RAM 10,0 GiB höchste RAM-Spitze 8,0 GiB + 25 %"
            in Page(report.render(runs)).text("kopf"))
    assert ("Empfohlener RAM – keine Messwerte der VM"
            in Page(report.render(runs[2:])).text("kopf"))


def log_entry(end_s: float, gesamt_ms: int, quelle="anfrage") -> dict:
    """Eine Zeile aus dem Request-Log der App, nur mit den Feldern, die hier zählen."""
    return {"zeit": (T0 + timedelta(seconds=end_s)).isoformat(timespec="seconds"),
            "gesamt_ms": gesamt_ms, "quelle": quelle, "zeichen": 1000}


def test_head_compares_real_concurrency_from_the_request_log_with_the_target_load():
    runs = [a_run("lauf-0", {1: [6000] * 3})]
    log = [log_entry(10, 10000), log_entry(5, 2000), log_entry(30, 5000),
           log_entry(10, 10000, quelle="lasttest")]

    assert ("Echte Nutzung, gleichzeitig höchstens 2 p99 2 bei 3 Prüfungen, Ziellast 4 reicht"
            in Page(report.render(runs, request_log=log)).text("kopf"))
    assert ("p99 2 bei 3 Prüfungen, über der Ziellast 1"
            in Page(report.render(runs, target=1, request_log=log)).text("kopf"))
    assert ("Echte Nutzung, gleichzeitig – keine echten Prüfungen im Request-Log"
            in Page(report.render(runs, request_log=log[3:])).text("kopf"))
    assert "Echte Nutzung" not in Page(report.render(runs)).text("kopf")


def test_response_time_chart_shows_p50_and_p95_per_stage_and_run_against_both_limits():
    runs = [a_run("lauf-0", {1: [6000, 6000, 8000], 2: [10000, 12000, 14000]}),
            a_run("lauf-1", {1: [5000] * 3})]

    page = Page(report.render(runs))

    assert page.tooltips("antwortzeit") == [
        "lauf-0 · Stufe 1: p50 6,0 s, p95 8,0 s",
        "lauf-0 · Stufe 2: p50 12,0 s, p95 14,0 s",
        "lauf-1 · Stufe 1: p50 5,0 s, p95 5,0 s",
    ]
    text = page.text("antwortzeit")
    assert "Komfortgrenze 20 s" in text and "Bruchgrenze 60 s" in text
    assert "lauf-0" in text and "lauf-1" in text  # Legende


def test_throughput_chart_shows_finished_checks_per_minute_per_stage_and_run():
    runs = [a_run("lauf-0", {1: [6000] * 3, 2: [12000] * 3})]  # 3 in 18 s, dann 3 in 36 s

    assert Page(report.render(runs)).tooltips("durchsatz") == [
        "lauf-0 · Stufe 1: 10,0 Prüfungen/min",
        "lauf-0 · Stufe 2: 5,0 Prüfungen/min",
    ]


def test_phase_chart_splits_each_stage_of_each_run_into_gate_detection_laya_and_rest():
    runs = [a_run("lauf-0", {1: [6000] * 3, 2: [9000] * 3}), a_run("lauf-1", {1: [5000] * 3})]

    assert Page(report.render(runs)).tooltips("phasen") == [
        "lauf-0 · Stufe 1: Gate 1,0 s, Erkennung 2,0 s, Laya 2,5 s, Rest 100 ms",
        "lauf-0 · Stufe 2: Gate 1,0 s, Erkennung 2,0 s, Laya 2,5 s, Rest 100 ms",
        "lauf-1 · Stufe 1: Gate 1,0 s, Erkennung 2,0 s, Laya 2,5 s, Rest 100 ms",
    ]


def test_class_chart_shows_ok_degraded_and_failed_per_stage_and_run():
    note = "Laya nicht erreichbar (HTTPStatusError); Gate übersprungen."
    stage_4 = [request(4, 100, 8000), request(4, 108, 8000), request(4, 116, 9000, gate_note=note),
               request(4, 125, 180000, status=None, fehler="Client-Timeout nach 180 s")]
    runs = [a_run("lauf-0", {1: [6000] * 3}, requests=stage_4)]

    assert Page(report.render(runs)).tooltips("klassen") == [
        "lauf-0 · Stufe 1: ok 3 (100 %), degradiert 0 (0 %), fehlgeschlagen 0 (0 %)",
        "lauf-0 · Stufe 4: ok 2 (50 %), degradiert 1 (25 %), fehlgeschlagen 1 (25 %)",
    ]


def test_long_text_chart_compares_p95_of_the_others_with_and_without_long_text_per_run():
    def lang(start_s, client_ms, **kwargs):
        return request(2, start_s, client_ms, abschnitt="langtext", **kwargs)
    part = [lang(100, 40000, beispiel="langtext"), lang(100, 9000, nutzer=2),
            lang(109, 15000, nutzer=2)]
    runs = [a_run("lauf-0", {1: [6000] * 3, 2: [8000, 9000, 10000]}, requests=part),
            a_run("lauf-1", {1: [6000] * 3})]

    page = Page(report.render(runs))

    assert page.tooltips("langtext") == [
        "lauf-0 · Stufe 2 ohne Langtext (Treppe): p95 10,0 s",
        "lauf-0 · Stufe 2 mit Langtext: p95 der anderen 15,0 s, Langtext selbst p50 40,0 s",
    ]
    assert "Ohne Langtext-Abschnitt: lauf-1" in page.text("langtext")


def at(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")


def vm_sample(seconds: float, app_cpu=350.0, steal=0.5) -> dict:
    """Eine Zeile aus samples.jsonl."""
    return {"zeit": at(seconds),
            "container": {"app": {"cpu_pct": app_cpu, "mem_bytes": 4 * GIB},
                          "laya": {"cpu_pct": 99.0, "mem_bytes": 2 * GIB}},
            "cpu_pct": {"user": 60.0, "idle": 39.5, "steal": steal},
            "mem_total_bytes": 8 * GIB, "mem_available_bytes": 2 * GIB}


def test_resource_chart_draws_cpu_ram_and_steal_per_run_with_stage_boundaries():
    stufen = [{"abschnitt": "treppe", "stufe": 1, "start": at(0), "ende": at(20)},
              {"abschnitt": "treppe", "stufe": 2, "start": at(20), "ende": at(65)},
              {"abschnitt": "langtext", "stufe": 2, "start": at(65), "ende": at(130)}]
    vm = a_run("lauf-0", {1: [6000] * 3}, ram_gib=8, stufen=stufen,
               samples=[vm_sample(s) for s in range(0, 130, 2)])
    local = a_run("lokal", {1: [6000] * 3}, vcpu=None, ram_gib=None, threads=None)

    page = Page(report.render([vm, local]))

    tips = page.tooltips("ressourcen")
    assert tips[:3] == ["lauf-0 · Stufe 1: 0:00–0:20", "lauf-0 · Stufe 2: 0:20–1:05",
                        "lauf-0 · Langtext, Stufe 2: 1:05–2:10"]
    assert {"lauf-0 · CPU app", "lauf-0 · CPU laya", "lauf-0 · RAM app", "lauf-0 · RAM laya",
            "lauf-0 · RAM VM gesamt", "lauf-0 · steal VM"} <= set(tips)
    assert "Ohne Messwerte der VM: lokal" in page.text("ressourcen")


def write_run(results: Path, name: str, times: dict[int, list[int]], **run_json) -> None:
    """Legt einen Lauf ab, wie loadtest.py es tut."""
    directory = results / name
    directory.mkdir(parents=True)
    (directory / "run.json").write_text(json.dumps(run_json), encoding="utf-8")
    (directory / "requests.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in ladder(times)), encoding="utf-8")
    (directory / "samples.jsonl").touch()


def run_names(html_file: Path) -> list[str]:
    return [row[0] for row in Page(html_file.read_text(encoding="utf-8")).rows("kopf")[1:]]


def test_cli_writes_the_report_over_all_runs_in_the_results_directory(tmp_path):
    results = tmp_path / "loadtest-results"
    write_run(results, "2026-10-08-2000-4cpu-2t", {1: [9000] * 3}, vcpu=4, ram_bytes=16 * GIB)
    write_run(results, "2026-10-07-2000-8cpu-4t", {1: [6000] * 3}, vcpu=8, ram_bytes=8 * GIB)
    (results / "notizen").mkdir()  # kein Lauf

    assert report.main(["--results", str(results)]) == 0

    assert run_names(results / "bericht.html") == ["2026-10-07-2000-8cpu-4t",
                                                   "2026-10-08-2000-4cpu-2t"]


def test_cli_selects_runs_and_takes_target_request_log_and_output_file(tmp_path):
    results = tmp_path / "loadtest-results"
    write_run(results, "2026-10-07-2000-8cpu-4t", {1: [6000] * 3, 2: [8000] * 3}, vcpu=8,
              ram_bytes=8 * GIB, zugang=TUNNEL)
    write_run(results, "2026-10-07-2100-8cpu-4t-caddy", {4: [9000] * 3})
    write_run(results, "2026-10-08-2000-4cpu-2t", {1: [9000] * 3})
    log = tmp_path / "requests.jsonl"
    log.write_text(json.dumps(log_entry(10, 10000)) + "\n{kaputt\n", encoding="utf-8")
    out = tmp_path / "bericht.html"

    assert report.main(["--results", str(results), "--runs", "*-8cpu-4t", "2026-10-08-*",
                        "--target", "2", "--request-log", str(log), "--out", str(out)]) == 0

    assert run_names(out) == ["2026-10-07-2000-8cpu-4t", "2026-10-08-2000-4cpu-2t"]
    text = Page(out.read_text(encoding="utf-8")).text("kopf")
    assert "Sweet Spot: 8 vCPU, 8,0 GiB RAM" in text
    assert "p99 1 bei 1 Prüfung, Ziellast 2 reicht" in text


def test_cli_refuses_a_selection_without_runs(tmp_path, capsys):
    results = tmp_path / "loadtest-results"
    write_run(results, "2026-10-07-2000-8cpu-4t", {1: [6000] * 3})

    assert report.main(["--results", str(results), "--runs", "2025-*"]) == 1

    assert "Keine Läufe zu 2025-*" in capsys.readouterr().err
    assert not (results / "bericht.html").exists()
