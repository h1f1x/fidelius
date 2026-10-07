"""Auswertung des Lasttests, Spec: docs/specs/lasttest.md, Abschnitte 1, 2 und 5.

Nur Standardbibliothek und ohne Netz: scripts/loadtest.py wertet damit nach jeder Stufe aus, der
HTML-Bericht liest damit die abgelegten Läufe. Ein Lauf liegt in loadtest-results/<name>/:

requests.jsonl, eine Zeile je Anfrage:
    abschnitt   "treppe" oder "langtext" (Wiederholung der Stufe c* mit einem Langtext-Nutzer)
    stufe       Zahl gleichzeitiger Prüfungen
    nutzer      virtueller Nutzer, ab 1
    aufwaermen  true bei der ersten Anfrage je Nutzer und Stufe; zählt nicht in die Kennzahlen
    beispiel    Dateiname aus examples/ ohne .txt, beim Langtext-Nutzer "langtext"
    zeichen     Länge des Textes
    start       Startzeit, ISO 8601 in UTC mit ms
    client_ms   im Client gemessene Dauer, auch bei Fehlern und beim Timeout (180 s)
    status      HTTP-Status, null bei Verbindungsfehler oder Timeout
    klasse      ok, degradiert oder fehlgeschlagen, siehe classify()
    timing      {gate_ms, detect_ms, laya_check_ms, total_ms} aus der Antwort, null ohne 200
    gate_note   gate.note aus der Antwort, null wenn leer
    fehler      Fehlertext (Exception, HTTP-Status mit detail), sonst null

samples.jsonl, alle 2 s eine Zeile, nur wenn die VM mitgelesen wird:
    zeit        ISO 8601 in UTC, Uhr des Skripts beim Eintreffen, also dieselbe wie bei start
    container   {app: {cpu_pct, mem_bytes}, laya: {…}} aus docker stats; cpu_pct bezogen auf
                eine CPU, 400 heißt vier CPUs voll ausgelastet; null, wenn ein Wert fehlt
    cpu_pct     {user, nice, system, idle, iowait, irq, softirq, steal} der VM in % seit der
                vorigen Zeile, aus /proc/stat; null in der ersten Zeile
    mem_total_bytes, mem_available_bytes   aus /proc/meminfo

run.json:
    zeit, ende                  Beginn und Ende des Laufs, ISO 8601 in UTC
    label                       --label oder null
    zugang                      {url, tunnel: {host, jump, ziel} oder null, vm: true/false}
    vcpu, ram_bytes, threads    nproc, MemTotal, OMP_NUM_THREADS der VM; null ohne VM
    threads_quelle              ".env" oder "standard" (nicht gesetzt, Compose nimmt 4)
    build, kalibrierung, gate_threshold   aus /api/config vor dem Start
    parameter                   {stufen, min_anfragen, min_dauer_s, client_timeout_s, langtext}
    docker_inspect_vorher, docker_inspect_nachher
                                je Dienst {id, status, restart_count, oom_killed, started_at,
                                omp_num_threads}; null ohne VM
    stufen                      [{abschnitt, stufe, start, ende, container_bruch: [Gründe]}] in
                                Laufreihenfolge; container_bruch aus container_breaks()
    abbruch                     null, oder warum der Lauf vorzeitig endete

Schnittstelle: read_run() und read_jsonl() lesen, evaluate_run() wertet einen Lauf aus,
sweet_spot(), sweet_spot_exclusion() und recommended_ram_bytes() wählen über mehrere Läufe,
timeline() legt die Messwerte der VM für den Bericht auf eine Zeitachse, concurrency() rechnet die
echte Nutzung aus dem Request-Log der App. Dazu classify(), percentile() und container_breaks(), die das Skript während
des Laufs braucht. Feldnamen der Ergebnisse sind englisch wie in log_report.py, die der Dateien
deutsch wie im Request-Log.
"""
from __future__ import annotations

import json
from bisect import bisect_left
from datetime import datetime
from pathlib import Path

# Werte von "abschnitt" in requests.jsonl: die Treppe und die Wiederholung der Stufe c* mit
# einem Nutzer, der den Langtext schickt; dessen Zeilen tragen beispiel = LONG_TEXT.
LADDER_PART, LONG_TEXT_PART = "treppe", "langtext"
LONG_TEXT = "langtext"
COMFORT_P95_MS = 20_000
TARGET_LOAD = 4
BREAK_P95_MS = 60_000
RAM_HEADROOM = 0.25

# Feld "quelle" im Request-Log der App, wie Source in app/fidelius/pipeline.py.
REQUEST_SOURCE, LOAD_TEST_SOURCE = "anfrage", "lasttest"

OK, DEGRADED, FAILED = "ok", "degradiert", "fehlgeschlagen"
CLASSES = (OK, DEGRADED, FAILED)
CONTAINERS = ("app", "laya")  # Schlüssel von "container" in samples.jsonl


def read_run(directory: str | Path) -> dict:
    """Ein abgelegter Lauf: {name, run, requests, samples}. name ist der Verzeichnisname, run der
    Inhalt von run.json ({} wenn er fehlt, etwa nach einem harten Abbruch), requests und samples
    die Zeilen der beiden JSONL-Dateien."""
    directory = Path(directory)
    run_file = directory / "run.json"
    return {
        "name": directory.name,
        "run": json.loads(run_file.read_text(encoding="utf-8")) if run_file.is_file() else {},
        "requests": read_jsonl(directory / "requests.jsonl"),
        "samples": read_jsonl(directory / "samples.jsonl"),
    }


def read_jsonl(path: str | Path) -> list[dict]:
    """Alle lesbaren Zeilen einer JSONL-Datei, etwa auch des Request-Logs der App. Leere und
    kaputte Zeilen (abgebrochenes Schreiben) fallen heraus, eine fehlende Datei ergibt []."""
    path = Path(path)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def classify(status: int | None, gate_note: str | None, error: str | None = None) -> str:
    """ok: HTTP 200 ohne Hinweis im Gate. degradiert: HTTP 200, aber Laya fehlte (503 oder
    Timeout), Gate oder Bestätigung wurden übersprungen. fehlgeschlagen: alles andere, auch ein
    Verbindungsfehler, der Client-Timeout oder eine 200 ohne lesbare Antwort."""
    if status != 200 or error:
        return FAILED
    return DEGRADED if gate_note else OK


def percentile(values, p: float):
    """Nearest-Rank wie in /auswertung (app/fidelius/log_report.py): der kleinste Wert, unter oder
    auf dem mindestens p % der Werte liegen. Kopiert, weil das Skript ohne das Paket läuft."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, -(-p * len(ordered) // 100) - 1)]


def evaluate_run(requests: list[dict], stages: list[dict] = (), samples: list[dict] = ()) -> dict:
    """Wertet einen Lauf aus: requests sind die Zeilen aus requests.jsonl, stages die Liste
    "stufen" aus run.json (Neustarts und OOM-Kills je Stufe), samples die Zeilen aus
    samples.jsonl (RAM-Spitze der VM). Ergebnis:

        stages          je Stufe der Treppe, aufsteigend: {stage, comfort, breaks} und die
                        Kennzahlen aus stage_metrics(); comfort: p95 ≤ 20 s; breaks: erfüllte
                        Bruchbedingungen als Text, [] wenn keine
        c_star          höchste Stufe unterhalb der Bruchstufe mit comfort und ohne Bruch, oder None
        break_stage     erste Stufe mit einer Bruchbedingung, oder None
        longtext        None, oder {stage, ladder_p95_ms, others, long}: Kennzahlen der anderen
                        Nutzer und des Langtext-Nutzers bei der Wiederholung, daneben das p95
                        derselben Stufe aus der Treppe
        ram_peak_bytes  höchstes MemTotal − MemAvailable der VM, None ohne Messwerte
    """
    ladder: dict[int, list[dict]] = {}
    for r in requests:
        if r.get("abschnitt") == LADDER_PART:
            ladder.setdefault(r["stufe"], []).append(r)
    container = {s["stufe"]: s.get("container_bruch") or [] for s in stages
                 if s.get("abschnitt") == LADDER_PART}
    rows = []
    for stage, group in sorted(ladder.items()):
        metrics = stage_metrics(group)
        rows.append({"stage": stage, **metrics,
                     "comfort": metrics["p95_ms"] is not None
                     and metrics["p95_ms"] <= COMFORT_P95_MS,
                     "breaks": _breaks(group, metrics) + container.get(stage, [])})
    break_stage = next((s["stage"] for s in rows if s["breaks"]), None)
    c_star = max((s["stage"] for s in rows if s["comfort"] and not s["breaks"]
                  and (break_stage is None or s["stage"] < break_stage)), default=None)
    return {"stages": rows, "c_star": c_star, "break_stage": break_stage,
            "longtext": _longtext(requests, rows), "ram_peak_bytes": _ram_peak(samples)}


def _ram_peak(samples: list[dict]) -> int | None:
    """Höchste RAM-Belegung der VM über alle Messwerte."""
    return max((u for s in samples if (u := _vm_used(s)) is not None), default=None)


def _vm_used(sample: dict) -> int | None:
    """RAM-Belegung der VM, MemTotal − MemAvailable, wie in Spec Abschnitt 3."""
    total, available = sample.get("mem_total_bytes"), sample.get("mem_available_bytes")
    return None if total is None or available is None else total - available


def timeline(samples: list[dict], stages: list[dict] = (), start: str | None = None) -> dict:
    """Die Messwerte des Samplers über die Zeit, für die Grafik im Bericht. Zeiten in Sekunden
    seit start (zeit aus run.json), ohne start seit der ersten Stufe oder dem ersten Messwert:

        samples  [{t_s, cpu_pct: {app, laya}, mem_bytes: {app, laya}, vm_used_bytes, steal_pct}]
                 cpu_pct je Container wie in samples.jsonl (100 = eine CPU voll), vm_used_bytes
                 wie bei der RAM-Spitze, steal_pct der VM; None, wo ein Wert fehlt
        stages   [{part, stage, start_s, end_s}] aus "stufen" in run.json, in Laufreihenfolge;
                 end_s None, wenn die Stufe kein Ende hat (Abbruch)

    Messwerte ohne lesbare zeit fallen heraus.
    """
    times = [(t, s) for s in samples if (t := _maybe_time(s.get("zeit"))) is not None]
    origin = _maybe_time(start)
    if origin is None:
        firsts = [t for st in stages if (t := _maybe_time(st.get("start"))) is not None]
        origin = min(firsts + [t for t, _ in times], default=0.0)

    def since(t):
        return None if t is None else round(t - origin, 3)

    def per_container(sample, key):
        container = sample.get("container") or {}
        return {c: (container.get(c) or {}).get(key) for c in CONTAINERS}

    return {
        "samples": [{"t_s": since(t), "cpu_pct": per_container(s, "cpu_pct"),
                     "mem_bytes": per_container(s, "mem_bytes"), "vm_used_bytes": _vm_used(s),
                     "steal_pct": (s.get("cpu_pct") or {}).get("steal")} for t, s in times],
        "stages": [{"part": st.get("abschnitt"), "stage": st.get("stufe"),
                    "start_s": since(_maybe_time(st.get("start"))),
                    "end_s": since(_maybe_time(st.get("ende")))} for st in stages],
    }


def recommended_ram_bytes(peaks) -> int | None:
    """Empfohlener RAM nach Spec Abschnitt 3: die höchste RAM-Spitze über alle Läufe (je Lauf
    ram_peak_bytes aus evaluate_run) plus RAM_HEADROOM; None, wenn kein Lauf eine hat."""
    peak = max((p for p in peaks if p is not None), default=None)
    return None if peak is None else round(peak * (1 + RAM_HEADROOM))


def _longtext(requests: list[dict], ladder: list[dict]) -> dict | None:
    """p95 der anderen Nutzer, während einer den Langtext schickt, neben dem p95 derselben Stufe
    aus der Treppe."""
    part = [r for r in requests if r.get("abschnitt") == LONG_TEXT_PART]
    if not part:
        return None
    stage = part[0]["stufe"]
    same = next((s for s in ladder if s["stage"] == stage), None)
    return {
        "stage": stage,
        "ladder_p95_ms": same["p95_ms"] if same else None,
        "others": stage_metrics([r for r in part if r.get("beispiel") != LONG_TEXT]),
        "long": stage_metrics([r for r in part if r.get("beispiel") == LONG_TEXT]),
    }


def _breaks(requests: list[dict], metrics: dict) -> list[str]:
    """Die Bruchbedingungen, die eine Stufe erfüllt, als lesbare Gründe. Degradierte und
    fehlgeschlagene Anfragen zählen hier auch beim Aufwärmen: Ein 503 bleibt ein 503, auch wenn
    seine Zeit nicht in die Perzentile eingeht."""
    reasons = []
    for c in (DEGRADED, FAILED):
        hits = [r for r in requests if r["klasse"] == c]
        if hits:
            warmup = sum(bool(r.get("aufwaermen")) for r in hits)
            reasons.append(f"{len(hits)} {c}" + (f" ({warmup} beim Aufwärmen)" if warmup else ""))
    if metrics["p95_ms"] is not None and metrics["p95_ms"] > BREAK_P95_MS:
        reasons.append("p95 über 60 s")
    return reasons


def sweet_spot(runs: list[dict], target: int = TARGET_LOAD) -> dict | None:
    """Der Lauf mit der kleinsten Größe (erst vCPU, dann RAM), dessen c* die Ziellast hält, oder
    None. runs: je Lauf ein dict mit zugang, vcpu, ram_bytes (aus run.json) und c_star (aus
    evaluate_run). Es zählen nur Läufe, für die sweet_spot_exclusion() keinen Grund nennt. Bei
    gleicher Größe gewinnt das höhere c*, etwa wenn dieselbe VM mit verschiedenen Threads lief."""
    fitting = [r for r in runs if sweet_spot_exclusion(r) is None
               and r.get("c_star") is not None and r["c_star"] >= target]
    return min(fitting, key=lambda r: (r["vcpu"], r["ram_bytes"], -r["c_star"]), default=None)


def sweet_spot_exclusion(run: dict) -> str | None:
    """Warum ein Lauf nicht in den Sweet Spot eingeht, oder None. Nur Läufe über den SSH-Tunnel
    messen die App selbst auf einer VM bekannter Größe: Über --url misst ein Lauf auch Caddy
    oder gar keine VM. run: dict mit zugang, vcpu und ram_bytes wie in run.json."""
    access = run.get("zugang") or {}
    if not access.get("tunnel"):
        return "über --url statt SSH-Tunnel" if access.get("vm") else "ohne VM"
    if run.get("vcpu") is None or run.get("ram_bytes") is None:
        return "Größe der VM unbekannt"
    return None


def concurrency(entries) -> dict:
    """Wie viele Prüfungen in echter Nutzung gleichzeitig liefen, aus dem Request-Log der App.

    Nur Einträge mit quelle = anfrage; Zeilen ohne lesbare zeit oder gesamt_ms fallen heraus. Jede
    Prüfung belegt [zeit − gesamt_ms, zeit). Für jede Prüfung zählt die höchste Zahl gleichzeitig
    laufender Prüfungen während ihres Intervalls, sie selbst eingeschlossen; darüber Maximum und
    p99 (Nearest-Rank), nicht zeitgewichtet. Endet eine Prüfung, wenn die nächste beginnt, laufen
    sie nicht gleichzeitig: zeit ist auf die Sekunde abgeschnitten, sonst sähe jeder Nutzer, der
    gleich weitermacht, wie zwei aus."""
    intervals = []
    for e in entries:
        if not isinstance(e, dict) or e.get("quelle") != REQUEST_SOURCE:
            continue
        try:
            end = round(datetime.fromisoformat(e["zeit"]).timestamp() * 1000)
        except (KeyError, TypeError, ValueError):
            continue
        ms = e.get("gesamt_ms")
        if not isinstance(ms, int | float) or isinstance(ms, bool) or ms < 0:
            continue
        intervals.append((end - round(ms), end))
    if not intervals:
        return {"requests": 0, "max": None, "p99": None}
    # Treppenfunktion der laufenden Prüfungen; bei gleicher Zeit zählt das Ende vor dem Anfang.
    times, levels, level = [], [], 0
    for t, step in sorted([(s, 1) for s, _ in intervals] + [(e, -1) for _, e in intervals]):
        level += step
        if times and times[-1] == t:
            levels[-1] = level
        else:
            times.append(t)
            levels.append(level)
    peaks = [max(levels[bisect_left(times, s):bisect_left(times, e)], default=1)
             for s, e in intervals]
    return {"requests": len(peaks), "max": max(peaks), "p99": percentile(peaks, 99)}


def container_breaks(before: dict, after: dict) -> list[str]:
    """Bruchgründe aus zwei Ständen von docker inspect (je Dienst, wie in run.json): ein höherer
    RestartCount, ein neues OOMKilled, ein anderer Startzeitpunkt (Neustart von Hand oder nach
    OOM-Kill ohne Restart-Policy) oder ein fehlender Container."""
    reasons = []
    for service, old in before.items():
        new = after.get(service)
        if new is None or new.get("id") != old.get("id"):
            reasons.append(f"{service}: fehlt" if new is None else f"{service}: ersetzt")
            continue
        restarted = new["restart_count"] > old["restart_count"]
        if restarted:
            reasons.append(f"{service}: RestartCount {old['restart_count']} → "
                           f"{new['restart_count']}")
        if new["oom_killed"] and not old["oom_killed"]:
            reasons.append(f"{service}: OOMKilled")
        if not restarted and new["started_at"] != old["started_at"]:
            reasons.append(f"{service}: neu gestartet")
    return reasons


def stage_metrics(requests: list[dict]) -> dict:
    """Kennzahlen über die gezählten Anfragen einer Stufe; die zum Aufwärmen fallen heraus.
    Perzentile nach Nearest-Rank über alle gezählten Anfragen, fehlgeschlagene mit ihrer
    gemessenen Zeit:

        count               gezählte Anfragen
        p50_ms, p95_ms, max_ms   Client-Zeit
        throughput_per_min  fertige Prüfungen je Minute, siehe _throughput()
        classes, shares     je Klasse Anzahl und Anteil (0.25 = 25 %)
        phases_ms           {gate, detect, laya, rest}, Mediane, siehe _phases()
    """
    counted = [r for r in requests if not r.get("aufwaermen")]
    times = [r["client_ms"] for r in counted]
    classes = {c: sum(r["klasse"] == c for r in counted) for c in CLASSES}
    return {
        "count": len(counted),
        "p50_ms": percentile(times, 50),
        "p95_ms": percentile(times, 95),
        "max_ms": max(times, default=None),
        "throughput_per_min": _throughput(counted),
        "classes": classes,
        "shares": {c: round(n / len(counted), 4) if counted else None for c, n in classes.items()},
        "phases_ms": _phases(counted),
    }


def _phases(counted: list[dict]) -> dict:
    """Mediane über alle Anfragen mit Antwort. Eine Phase, die bei einer Prüfung nicht lief (die
    App liefert dann 0, etwa Erkennung und Laya beim harmlosen Beispiel, das am Gate endet),
    zählt für diese Phase nicht mit, wie in /auswertung (app/fidelius/log_report.py). Rest ist
    Client-Zeit minus total_ms, also Warten vor der App, Netz und Proxy."""
    timed = [r for r in counted if isinstance(r.get("timing"), dict)]

    def ran(key):
        return percentile([v for r in timed if (v := r["timing"][key])], 50)

    return {
        "gate": ran("gate_ms"),
        "detect": ran("detect_ms"),
        "laya": ran("laya_check_ms"),
        "rest": percentile([r["client_ms"] - r["timing"]["total_ms"] for r in timed], 50),
    }


def _throughput(counted: list[dict]) -> float | None:
    """Fertige Prüfungen (ok und degradiert) je Minute, vom ersten Start bis zum letzten Ende der
    gezählten Anfragen."""
    if not counted:
        return None
    starts = [_time(r["start"]) for r in counted]
    ends = [s + r["client_ms"] / 1000 for s, r in zip(starts, counted)]
    window = max(ends) - min(starts)
    finished = sum(r["klasse"] in (OK, DEGRADED) for r in counted)
    return round(finished / window * 60, 2) if window > 0 else None


def _time(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def _maybe_time(iso) -> float | None:
    try:
        return _time(iso)
    except (TypeError, ValueError):
        return None
