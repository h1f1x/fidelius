#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""HTML-Bericht über die Lasttest-Läufe, Spec: docs/specs/lasttest.md, Abschnitt 6.

Aufruf über make, Optionen in ARGS:
    make loadtest-report                                    # alle Läufe in loadtest-results/
    make loadtest-report ARGS="--runs '*-8cpu-*' --target 3"
    make loadtest-report ARGS="--request-log requests.jsonl"   # echte Nutzung dazu

Schreibt eine einzelne HTML-Datei ohne JavaScript und ohne Abhängigkeiten, die offline öffnet und
sich weitergeben lässt: Kopf mit Sweet Spot und einer Zeile je Lauf, darunter Antwortzeit,
Durchsatz, Zeitanteile, Klassen, Langtext und CPU/RAM/steal über die Zeit als Inline-SVG im Stil
von /auswertung. Tooltips stehen in <title>, der Dark Mode folgt dem System.

Nur Standardbibliothek. Die Zahlen rechnet loadtest_eval, hier wird nur gezeichnet.
"""
from __future__ import annotations

import argparse
import fnmatch
import math
import sys
from datetime import datetime
from html import escape
from pathlib import Path

import loadtest_eval as ev

RESULTS = Path(__file__).resolve().parent.parent / "loadtest-results"

WORST_CASE_STAGE = 10  # alle 10 Nutzer klicken im selben Moment, Spec Abschnitt 2
RESPONSE_CLIP_MS = 120_000
WIDE, PANEL = 1000, 500  # viewBox-Breiten: Grafik über die ganze Kachel, Feld in .panels
COLORS = 7  # --c1 … --c7


# Tokens und Regeln aus app/fidelius/static/style.css (Auswertung), damit der Bericht aussieht
# wie /auswertung, aber ohne die Datei offline öffnet.
CSS = """
:root { color-scheme: light dark;
  --bg: #f6f7f9; --panel: #fff; --text: #1f2933; --muted: #6b7280; --border: #d9dee5;
  --danger: #c0392b; --done: #1b8a3c;
  --c1: #1f5fbf; --c2: #e4572e; --c3: #29a36a; --c4: #a05cd6; --c5: #d08a10; --c6: #17a2b8;
  --c7: #888; --mark: #e4572e; --worse: var(--danger); --better: var(--done); }
@media (prefers-color-scheme: dark) {
  :root { --bg: #14171c; --panel: #1d2127; --text: #e6e8eb; --muted: #9aa3ad; --border: #343a43;
    --c1: #4f8df7; --c2: #f07050; --c3: #3fc283; --c4: #b884ee; --c5: #f0b850; --c6: #3cc4da;
    --c7: #9aa3ad; --mark: #f07050; --worse: #ef6b5b; --better: #3fbf6a; }
}
* { box-sizing: border-box; }
body { margin: 0; font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg); color: var(--text); }
.report { max-width: 1100px; margin: 0 auto; padding: 0 20px 20px; }
.report .top { padding: 14px 0 10px; }
.report h1 { margin: 0; font-size: 20px; }
.report .lead { margin: 0 0 12px; font-size: 17px; }
.hint { margin: 0; color: var(--muted); font-size: 12px; }
.tile .hint { margin-top: 6px; }
.report .lead + .hint { margin: -6px 0 12px; }
.report .kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px; margin-bottom: 10px; }
.report .kpi, .report .tile { background: var(--panel); border: 1px solid var(--border);
  border-radius: 8px; }
.report .kpi { padding: 12px 14px; }
.report .kpi .k { font-size: 12px; color: var(--muted); }
.report .kpi .v { font-size: 28px; font-weight: 700; }
.report .kpi .t { font-size: 12px; margin-top: 2px; color: var(--muted); }
.report .tile { padding: 12px; margin-bottom: 10px; min-width: 0; overflow-x: auto; }
.report .tile h2 { margin: 0 0 8px; font-size: 14px; }
.report .worse { color: var(--worse); }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--border); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
td [title] { text-decoration: underline dotted; cursor: help; }
i.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; }
.legendrow { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 11px; color: var(--muted);
  margin-top: 4px; }
.legendrow i { display: inline-block; width: 9px; height: 9px; border-radius: 50%;
  margin-right: 4px; vertical-align: -1px; }
.panels { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(440px, 100%), 1fr));
  gap: 6px 20px; }
.panel h3 { margin: 6px 0 2px; font-size: 12px; font-weight: 600; }
svg.chart { width: 100%; height: auto; display: block; overflow: visible; }
svg.chart text { fill: var(--muted); font: 10px system-ui, sans-serif; }
svg.chart text.mark { fill: var(--mark); }
svg.chart text.label { fill: var(--text); font-weight: 600; }
svg.chart .axis { stroke: var(--border); }
svg.chart .grid { stroke: var(--border); opacity: .6; }
svg.chart .ref { stroke: var(--mark); stroke-dasharray: 3 3; }
svg.chart .cap, svg.chart .stage { stroke: var(--muted); stroke-dasharray: 2 3; opacity: .7; }
svg.chart .line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
svg.chart .line.dashed { stroke-width: 1.5; stroke-dasharray: 5 4; }
svg.chart .line.thin { stroke-width: 1.5; }
svg.chart .dot { stroke: var(--panel); stroke-width: 2; }
svg.chart .hit, svg.chart .hit * { fill: transparent; }
svg.key { width: 18px; height: 8px; margin-right: 4px; overflow: visible; }
svg.key line { stroke: var(--muted); stroke-width: 2; }
"""


def render(runs: list[dict], target: int = ev.TARGET_LOAD,
           request_log: list[dict] | None = None, generated: datetime | None = None) -> str:
    """Der Bericht als eine HTML-Datei. runs: Läufe, wie loadtest_eval.read_run() sie liefert,
    in der Reihenfolge, in der sie Farben und Zeilen bekommen; request_log: Zeilen des
    Request-Logs der App für die echte Nutzung, oder None; generated: Zeitpunkt im Kopf."""
    rows = [_row(r) for r in runs]
    usage = "" if request_log is None else _usage_kpi(ev.concurrency(request_log), target)
    facts = [f"{len(rows)} {'Lauf' if len(rows) == 1 else 'Läufe'}",
             f"Ziellast {target} gleichzeitige Prüfungen",
             (f"Komfortgrenze p95 ≤ {_seconds(ev.COMFORT_P95_MS)}, "
              f"Bruch ab p95 > {_seconds(ev.BREAK_P95_MS)}")]
    if generated:
        facts.append(f"erzeugt {generated:%d.%m.%Y %H:%M}")
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lasttest-Bericht</title><style>{CSS}</style></head>
<body><main class="report">
<section id="kopf"><div class="top"><h1>Lasttest-Bericht</h1>
<p class="hint">{" · ".join(facts)}</p></div>
{_sweet_spot(rows, target)}
<div class="kpis">{_ram_kpi(rows)}{usage}</div>
<div class="tile">{_run_table(rows)}</div></section>
{_tile("antwortzeit", "Antwortzeit je Stufe", _response_chart(rows))}
{_tile("durchsatz", "Durchsatz je Stufe", _throughput_chart(rows))}
{_tile("phasen", "Wo die Zeit hingeht", _phase_chart(rows))}
{_tile("klassen", "Klassen je Stufe", _class_chart(rows))}
{_tile("langtext", "Langtext", _longtext_chart(rows))}
{_tile("ressourcen", "CPU, RAM und steal über die Zeit", _resource_chart(rows))}
</main></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    found = sorted(d.name for d in args.results.iterdir() if d.is_dir() and _is_run(d)) \
        if args.results.is_dir() else []
    selected = found
    if args.runs:
        unmatched = [p for p in args.runs if not fnmatch.filter(found, p)]
        if unmatched:
            print(f"Keine Läufe zu {', '.join(unmatched)} in {args.results}. Vorhanden: "
                  f"{', '.join(found) or 'keine'}", file=sys.stderr)
            return 1
        selected = [n for n in found if any(fnmatch.fnmatch(n, p) for p in args.runs)]
    if not selected:
        print(f"Keine Läufe in {args.results}. Erst: make loadtest", file=sys.stderr)
        return 1
    request_log = None
    if args.request_log:
        if not args.request_log.is_file():
            print(f"Request-Log {args.request_log} fehlt.", file=sys.stderr)
            return 1
        request_log = ev.read_jsonl(args.request_log)
    out = args.out or args.results / "bericht.html"
    html = render([ev.read_run(args.results / name) for name in selected], args.target,
                  request_log, datetime.now().astimezone())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Bericht über {len(selected)} {'Lauf' if len(selected) == 1 else 'Läufe'}: {out}")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--results", type=Path, default=RESULTS,
                    help="Ablage der Läufe (Standard: loadtest-results/)")
    ap.add_argument("--runs", nargs="+", metavar="LAUF",
                    help="nur diese Läufe, Verzeichnisnamen oder Muster wie '*-8cpu-*' "
                         "(Standard: alle)")
    ap.add_argument("--target", type=int, default=ev.TARGET_LOAD,
                    help="Ziellast in gleichzeitigen Prüfungen (Standard: %(default)s)")
    ap.add_argument("--request-log", type=Path, metavar="DATEI",
                    help="Request-Log der App (Download über /api/request-log) für die echte "
                         "Nutzung")
    ap.add_argument("--out", type=Path,
                    help="HTML-Datei (Standard: bericht.html in der Ablage)")
    return ap.parse_args(argv)


def _is_run(directory: Path) -> bool:
    return (directory / "requests.jsonl").is_file() or (directory / "run.json").is_file()


def _row(run: dict) -> dict:
    """Ein Lauf mit seinen Kennzahlen aus evaluate_run und den Angaben aus run.json."""
    meta = run["run"]
    result = ev.evaluate_run(run["requests"], meta.get("stufen") or [], run["samples"])
    return {"name": run["name"], "vcpu": meta.get("vcpu"), "ram_bytes": meta.get("ram_bytes"),
            "threads": meta.get("threads"), "zugang": meta.get("zugang"), **result,
            "timeline": ev.timeline(run["samples"], meta.get("stufen") or [], meta.get("zeit"))}


def _stage(row: dict, stage: int | None) -> dict | None:
    return next((s for s in row["stages"] if s["stage"] == stage), None)


# ---------- Kopf ----------

def _sweet_spot(rows: list[dict], target: int) -> str:
    """Der Sweet Spot in einem Satz, darunter die Läufe, die nicht zählen, mit ihrem Grund."""
    excluded = [(r["name"], reason) for r in rows
                if (reason := ev.sweet_spot_exclusion(r)) is not None]
    note = ("" if not excluded else
            '<p class="hint">Nicht im Sweet Spot, weil nur Läufe über den SSH-Tunnel zählen: '
            + ", ".join(f"{escape(name)} ({reason})" for name, reason in excluded) + "</p>")
    spot = ev.sweet_spot(rows, target)
    if spot:
        lead = (f"<strong>Sweet Spot: {spot['vcpu']} vCPU, {ev.gib(spot['ram_bytes'])} RAM</strong>"
                f" – die kleinste gemessene Größe, die {target} gleichzeitige Prüfungen unter der "
                f"Komfortgrenze hält (c* = {spot['c_star']}, Lauf {escape(spot['name'])}).")
    elif len(excluded) == len(rows):
        lead = ("<strong>Kein Sweet Spot:</strong> Kein Lauf lief über den SSH-Tunnel auf einer "
                "VM bekannter Größe.")
    else:
        lead = (f"<strong>Kein Sweet Spot:</strong> Keine gemessene Größe hält {target} "
                "gleichzeitige Prüfungen unter der Komfortgrenze.")
    return f'<p class="lead">{lead}</p>{note}'


def _kpi(label: str, value: str, note: str) -> str:
    return (f'<div class="kpi"><div class="k">{label}</div><div class="v">{value}</div>'
            f'<div class="t">{note}</div></div>')


def _ram_kpi(rows: list[dict]) -> str:
    peaks = [r["ram_peak_bytes"] for r in rows]
    recommended = ev.recommended_ram_bytes(peaks)
    if recommended is None:
        return _kpi("Empfohlener RAM", "–", "keine Messwerte der VM")
    return _kpi("Empfohlener RAM", ev.gib(recommended),
                f"höchste RAM-Spitze {ev.gib(max(p for p in peaks if p is not None))} "
                f"+ {round(ev.RAM_HEADROOM * 100)} %")


def _usage_kpi(usage: dict, target: int) -> str:
    """Gleichzeitigkeit echter Nutzung; die Ziellast nimmt das p99 an (Spec Abschnitt 2)."""
    label = "Echte Nutzung, gleichzeitig"
    if not usage["requests"]:
        return _kpi(label, "–", "keine echten Prüfungen im Request-Log")
    fits = usage["p99"] <= target
    verdict = (f"Ziellast {target} reicht" if fits
               else f'<span class="worse">über der Ziellast {target}</span>')
    checks = "Prüfung" if usage["requests"] == 1 else "Prüfungen"
    return _kpi(label, f"höchstens {usage['max']}",
                f"p99 {usage['p99']} bei {_int(usage['requests'])} {checks}, {verdict}")


def _run_table(rows: list[dict]) -> str:
    head = ["Lauf", "vCPU", "RAM", "Threads", "c*", "Bruchstufe", "Durchsatz bei c* (Prüf./min)",
            f"p95 bei Stufe {WORST_CASE_STAGE}", "RAM-Spitze"]
    body = []
    for row in rows:
        at_c_star = _stage(row, row["c_star"]) or {}
        worst = _stage(row, WORST_CASE_STAGE) or {}
        broken = _stage(row, row["break_stage"])
        cells = [
            _int(row["vcpu"]), ev.gib(row["ram_bytes"]), _int(row["threads"]), _int(row["c_star"]),
            f'<span title="{escape(", ".join(broken["breaks"]))}">{broken["stage"]}</span>'
            if broken else "keine",
            ev.num(at_c_star.get("throughput_per_min")), _ms(worst.get("p95_ms")),
            ev.gib(row["ram_peak_bytes"]),
        ]
        color = f'<i class="dot" style="background:{_color(len(body))}"></i>'
        body.append(f"<tr><td>{color}{escape(row['name'])}</td>"
                    + "".join(f'<td class="num">{c}</td>' for c in cells) + "</tr>")
    head_cells = [f"<th>{escape(head[0])}</th>"] + [f'<th class="num">{escape(h)}</th>'
                                                     for h in head[1:]]
    return (f"<table><thead><tr>{''.join(head_cells)}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>")


# ---------- Grafiken ----------

def _tile(section_id: str, title: str, content: str) -> str:
    return f'<section id="{section_id}" class="tile"><h2>{title}</h2>{content}</section>'


def _legend(rows: list[dict], extra: str = "") -> str:
    """Läufe mit ihrer Farbe; extra hängt Schlüssel für Linienarten an."""
    runs = "".join(f'<span><i style="background:{_color(i)}"></i>{escape(r["name"])}</span>'
                   for i, r in enumerate(rows))
    return f'<div class="legendrow">{runs}{extra}</div>'


def _line_key(label: str, dashed: bool) -> str:
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    return (f'<span><svg class="key" viewBox="0 0 18 8"><line x1="0" x2="18" y1="4" y2="4"'
            f'{dash}/></svg>{label}</span>')


def _response_chart(rows: list[dict]) -> str:
    """Hauptgrafik: p95 durchgezogen, p50 gestrichelt, eine Farbe je Lauf, dazu Komfort- und
    Bruchgrenze. Werte über RESPONSE_CLIP_MS (Timeouts) stehen am oberen Rand, damit die Stufen
    um die Komfortgrenze lesbar bleiben."""
    values = [v for r in rows for s in r["stages"] for v in (s["p50_ms"], s["p95_ms"])
              if v is not None]
    if not values:
        return _empty("Keine Stufen gemessen.")
    top = max(ev.BREAK_P95_MS * 1.1, min(max(values), RESPONSE_CLIP_MS))
    lines, hovers = [], []
    for i, r in enumerate(rows):
        lines.append((i, [(s["stage"], s["p95_ms"]) for s in r["stages"]], False))
        lines.append((i, [(s["stage"], s["p50_ms"]) for s in r["stages"]], True))
        hovers += [(s["stage"], (s["p50_ms"], s["p95_ms"]),
                    (f'{r["name"]} · Stufe {s["stage"]}: p50 {_ms(s["p50_ms"])}, '
                     f'p95 {_ms(s["p95_ms"])}')) for s in r["stages"]]
    chart = _xy_chart(lines, hovers, _stages(rows), top=top, y_fmt=_seconds,
                      x_title="gleichzeitige Prüfungen →",
                      refs=[(ev.COMFORT_P95_MS, f"Komfortgrenze {_seconds(ev.COMFORT_P95_MS)}"),
                            (ev.BREAK_P95_MS, f"Bruchgrenze {_seconds(ev.BREAK_P95_MS)}")])
    return (chart + _legend(rows, _line_key("p95", False) + _line_key("p50", True))
            + f'<p class="hint">Client-Zeit je Stufe. Werte über {_seconds(RESPONSE_CLIP_MS)} '
            "stehen am oberen Rand, beschriftet mit ihrem Wert.</p>")


def _throughput_chart(rows: list[dict]) -> str:
    values = [s["throughput_per_min"] for r in rows for s in r["stages"]
              if s["throughput_per_min"] is not None]
    if not values:
        return _empty("Keine Stufen gemessen.")
    lines = [(i, [(s["stage"], s["throughput_per_min"]) for s in r["stages"]], False)
             for i, r in enumerate(rows)]
    hovers = [(s["stage"], (s["throughput_per_min"],),
               f'{r["name"]} · Stufe {s["stage"]}: {ev.num(s["throughput_per_min"])} Prüfungen/min')
              for r in rows for s in r["stages"]]
    chart = _xy_chart(lines, hovers, _stages(rows), top=max(values) * 1.1,
                      y_fmt=lambda v: ev.num(v, 0 if v == int(v) else 1),
                      x_title="gleichzeitige Prüfungen →", height=200)
    return (chart + _legend(rows)
            + '<p class="hint">Fertige Prüfungen (ok und degradiert) je Minute. Bleibt die Linie '
            "flach, warten mehr gleichzeitige Prüfungen nur länger.</p>")


PHASES = (("gate", "Gate", "var(--c1)"), ("detect", "Erkennung", "var(--c2)"),
          ("laya", "Laya", "var(--c3)"), ("rest", "Rest", "var(--c7)"))


def _phase_chart(rows: list[dict]) -> str:
    """Mediane der Server-Phasen und der Rest, gestapelt je Stufe, ein Feld je Lauf."""
    def stack(stage):
        return [(stage["phases_ms"][key] or 0, color) for key, _, color in PHASES]

    def tip(row, stage):
        phases = ", ".join(f"{label} {_ms(stage['phases_ms'][key])}" for key, label, _ in PHASES)
        return f'{row["name"]} · Stufe {stage["stage"]}: {phases}'

    sums = [sum(v for v, _ in stack(s)) for r in rows for s in r["stages"]]
    if not any(sums):
        return _empty("Keine Stufen mit Antworten der App.")
    legend = "".join(f'<span><i style="background:{color}"></i>{label}</span>'
                     for _, label, color in PHASES)
    return (_stacked_panels(rows, stack, tip, top=max(sums), y_fmt=_seconds)
            + f'<div class="legendrow">{legend}</div>'
            + '<p class="hint">Mediane je Phase über die gezählten Prüfungen, in denen sie lief: '
            "Erkennung und Laya ohne das harmlose Beispiel, das am Gate endet. Ihre Summe ist "
            "nicht der Median der Gesamtzeit. Rest ist Client-Zeit minus Serverzeit: Netz, "
            "Proxy und Warten vor der App.</p>")


def _longtext_chart(rows: list[dict]) -> str:
    """Je Lauf zwei Balken: p95 aller Nutzer der Stufe c* aus der Treppe und p95 der übrigen
    Nutzer, während einer den Langtext schickt."""
    with_part = [(i, r) for i, r in enumerate(rows) if r["longtext"]]
    missing = [r["name"] for r in rows if not r["longtext"]]
    note = (f'<p class="hint">Ohne Langtext-Abschnitt: {escape(", ".join(missing))}</p>'
            if missing else "")
    if not with_part:
        return _empty("Kein Lauf hat einen Langtext-Abschnitt.") + note
    values = [v for _, r in with_part
              for v in (r["longtext"]["ladder_p95_ms"], r["longtext"]["others"]["p95_ms"])
              if v is not None]
    ticks = _nice_ticks(max(values + [ev.COMFORT_P95_MS]), 4)
    x_max = ticks[-1]
    pad_left, bar_h, block = 110, 12, 52
    height = block * len(with_part) + 18

    def sx(v):
        return round(pad_left + min(v, x_max) / x_max * (WIDE - pad_left - 50), 1)

    parts = [f'<line class="grid" x1="{sx(t)}" x2="{sx(t)}" y1="0" y2="{height - 16}"/>'
             f'<text x="{sx(t)}" y="{height - 4}" text-anchor="middle">{_seconds(t)}</text>'
             for t in ticks]
    for k, (i, r) in enumerate(with_part):
        lt, top = r["longtext"], k * block
        parts.append(f'<text class="label" x="0" y="{top + 11}">{escape(r["name"])}</text>')
        bars = [
            ("ohne", lt["ladder_p95_ms"], ".4",
             (f'{r["name"]} · Stufe {lt["stage"]} ohne Langtext (Treppe): '
              f'p95 {_ms(lt["ladder_p95_ms"])}')),
            ("mit Langtext", lt["others"]["p95_ms"], "1",
             (f'{r["name"]} · Stufe {lt["stage"]} mit Langtext: p95 der anderen '
              f'{_ms(lt["others"]["p95_ms"])}, Langtext selbst p50 '
              f'{_ms(lt["long"]["p50_ms"])}')),
        ]
        for j, (label, value, opacity, tip) in enumerate(bars):
            y = top + 18 + j * (bar_h + 3)
            width = 0 if value is None else sx(value) - pad_left
            parts.append(
                f'<g><title>{escape(tip)}</title>'
                f'<text x="{pad_left - 6}" y="{y + 9}" text-anchor="end">{label}</text>'
                f'<rect x="{pad_left}" y="{y}" width="{round(max(width, 0.5), 1)}" '
                f'height="{bar_h}" rx="2" style="fill:{_color(i)}" fill-opacity="{opacity}"/>'
                f'<text x="{pad_left + width + 4}" y="{y + 9}">{_ms(value)}</text></g>')
    parts.append(f'<line class="ref" x1="{sx(ev.COMFORT_P95_MS)}" x2="{sx(ev.COMFORT_P95_MS)}" '
                 f'y1="0" y2="{height - 16}"/>')
    return (f'<svg class="chart" viewBox="0 0 {WIDE} {height}" role="img">{"".join(parts)}</svg>'
            + '<p class="hint">Stufe c*. „ohne“: p95 aller c* Nutzer derselben Stufe aus der '
            "Treppe. „mit Langtext“: p95 der übrigen Nutzer, während einer von ihnen den "
            "Langtext (alle Beispiele aneinander) schickt. "
            f"Gestrichelt: Komfortgrenze {_seconds(ev.COMFORT_P95_MS)}.</p>" + note)


CLASS_COLORS = {ev.OK: "var(--better)", ev.DEGRADED: "var(--c5)", ev.FAILED: "var(--worse)"}


def _class_chart(rows: list[dict]) -> str:
    """Anteil jeder Klasse je Stufe, ein Feld je Lauf. Ein Lauf endet nach der ersten Stufe mit
    einer degradierten oder fehlgeschlagenen Anfrage, Farbe zeigt sich also höchstens ganz
    rechts."""
    def stack(stage):
        return [(stage["shares"][c] or 0, CLASS_COLORS[c]) for c in ev.CLASSES]

    def tip(row, stage):
        classes = ", ".join(f"{c} {stage['classes'][c]} ({_percent(stage['shares'][c])})"
                            for c in ev.CLASSES)
        return f'{row["name"]} · Stufe {stage["stage"]}: {classes}'

    if not any(r["stages"] for r in rows):
        return _empty("Keine Stufen gemessen.")
    legend = "".join(f'<span><i style="background:{CLASS_COLORS[c]}"></i>{c}</span>'
                     for c in ev.CLASSES)
    return (_stacked_panels(rows, stack, tip, top=1, y_fmt=_percent, height=80)
            + f'<div class="legendrow">{legend}</div>'
            + '<p class="hint">Anteile der gezählten Prüfungen. Für den Bruch zählen auch '
            "degradierte und fehlgeschlagene beim Aufwärmen, siehe Tabelle oben.</p>")


def _stacked_panels(rows: list[dict], stack, tip, *, top: float, y_fmt,
                    height: int = 110) -> str:
    """Kleine Vielfache: je Lauf ein Feld mit einem gestapelten Balken je Stufe. Alle Felder
    teilen Achsen und Stufenpositionen, damit dieselbe Stufe untereinander steht. stack(stage):
    [(Wert, Farbe)] von unten nach oben; tip(row, stage): Tooltip des Balkens."""
    stages = _stages(rows)
    ticks = _nice_ticks(top, 3)
    y_max = ticks[-1]
    pad_left, pad_bottom, pad_top = 44, 16, 6
    base, inner = height - pad_bottom, height - pad_bottom - pad_top
    band = (PANEL - pad_left) / len(stages)
    bar = min(24, band * 0.6)
    panels = []
    for row in rows:
        if not row["stages"]:
            continue
        parts = _y_grid(pad_left, base, inner, ticks, y_fmt)
        parts += [f'<text x="{round(pad_left + (k + 0.5) * band, 1)}" y="{height - 4}" '
                  f'text-anchor="middle">{s}</text>' for k, s in enumerate(stages)]
        parts.append(f'<line class="axis" x1="{pad_left}" x2="{PANEL}" y1="{base}" y2="{base}"/>')
        for stage in row["stages"]:
            x0 = pad_left + stages.index(stage["stage"]) * band
            x, y, rects = round(x0 + (band - bar) / 2, 1), base, []
            for value, color in stack(stage):
                h = min(value, y_max) / y_max * inner
                if h <= 0:
                    continue
                y -= h
                rects.append(f'<rect x="{x}" y="{round(y + 1, 1)}" width="{round(bar, 1)}" '
                             f'height="{round(max(h - 2, 0.5), 1)}" style="fill:{color}"/>')
            parts.append(f'<g class="bars"><title>{escape(tip(row, stage))}</title>'
                         f'<rect class="hit" x="{round(x0, 1)}" y="{pad_top}" '
                         f'width="{round(band, 1)}" height="{inner}"/>{"".join(rects)}</g>')
        panels.append(f'<div class="panel"><h3>{escape(row["name"])}</h3>'
                      f'<svg class="chart" viewBox="0 0 {PANEL} {height}" role="img">'
                      f'{"".join(parts)}</svg></div>')
    return f'<div class="panels">{"".join(panels)}</div>'


RESOURCE_COLORS = {"app": "var(--c1)", "laya": "var(--c2)", "VM gesamt": "var(--c7)",
                   "steal der VM": "var(--c5)"}


def _resource_chart(rows: list[dict]) -> str:
    """Je Lauf mit Messwerten ein Feld mit CPU, RAM und steal über die Zeit, Stufengrenzen als
    senkrechte Linien."""
    measured = [r for r in rows if r["timeline"]["samples"]]
    missing = [r["name"] for r in rows if not r["timeline"]["samples"]]
    note = (f'<p class="hint">Ohne Messwerte der VM: {escape(", ".join(missing))}</p>'
            if missing else "")
    if not measured:
        return _empty("Kein Lauf hat Messwerte der VM.") + note
    legend = "".join(f'<span><i style="background:{color}"></i>{label}</span>'
                     for label, color in RESOURCE_COLORS.items())
    return (f'<div class="panels">{"".join(_resource_panel(r) for r in measured)}</div>'
            + f'<div class="legendrow">{legend}</div>'
            + '<p class="hint">CPU in ausgelasteten CPUs je Container (docker stats), oben '
            "begrenzt durch die vCPU der VM. RAM je Container und belegt auf der VM "
            "(MemTotal − MemAvailable). steal: Anteil der CPU-Zeit, den der Host anderen gab. "
            "Senkrechte Linien: Beginn einer Stufe, L = Langtext.</p>" + note)


def _resource_panel(row: dict) -> str:
    timeline = row["timeline"]
    samples, stages = timeline["samples"], timeline["stages"]
    end = max([s["t_s"] for s in samples]
              + [t for st in stages for t in (st["start_s"], st["end_s"]) if t is not None])

    def series(label, color, pick, scale=1):
        return (label, color, [(s["t_s"], None if (v := pick(s)) is None else v / scale)
                               for s in samples])

    colors = RESOURCE_COLORS
    cpus = [series(c, colors[c], lambda s, c=c: s["cpu_pct"][c], 100) for c in ev.CONTAINERS]
    ram = [series(c, colors[c], lambda s, c=c: s["mem_bytes"][c], 2 ** 30)
           for c in ev.CONTAINERS]
    ram.append(series("VM gesamt", colors["VM gesamt"], lambda s: s["vm_used_bytes"], 2 ** 30))
    steal = [series("VM", colors["steal der VM"], lambda s: s["steal_pct"])]

    def peak(lines):
        return max((y for *_, points in lines for _, y in points if y is not None), default=0)

    vcpu, total = row["vcpu"], row["ram_bytes"]
    charts = [
        _time_chart(row, "CPU", cpus, stages, end, top=vcpu or peak(cpus),
                    y_fmt=lambda v: ev.num(v, 0), cap=f"{vcpu} vCPU" if vcpu else None,
                    stage_tips=True),
        _time_chart(row, "RAM", ram, stages, end, top=total / 2 ** 30 if total else peak(ram),
                    y_fmt=lambda v: f"{ev.num(v, 0)} GiB", cap=ev.gib(total) if total else None),
        _time_chart(row, "steal", steal, stages, end, top=max(5, peak(steal)),
                    y_fmt=lambda v: f"{ev.num(v, 0)} %", y_ticks=1, height=70, x_labels=True),
    ]
    return f'<div class="panel"><h3>{escape(row["name"])}</h3>{"".join(charts)}</div>'


def _time_chart(row, title, lines, stages, end, *, top, y_fmt, cap=None, stage_tips=False,
                y_ticks=2, height=84, x_labels=False) -> str:
    """Ein Streifen der Ressourcen-Grafik: Zeit in Minuten seit Laufbeginn auf der x-Achse,
    lines: (Name, Farbe, [(t_s, y)]). cap beschriftet die Obergrenze (vCPU, MemTotal). Über dem
    Streifen steht eine Zeile für Titel und Stufennummern; nur der unterste trägt die Minuten."""
    ticks = _nice_ticks(top, y_ticks)
    y_max = ticks[-1]
    pad_left, pad_top, pad_bottom = 52, 22, 16 if x_labels else 4
    base, inner = height - pad_bottom, height - pad_bottom - pad_top
    x_ticks = _nice_ticks(end / 60, 4)

    def sx(t):
        return round(pad_left + min(t, end) / (end or 1) * (PANEL - pad_left), 1)

    parts = [f'<text class="label" x="0" y="10">{title}</text>']
    parts += _y_grid(pad_left, base, inner, ticks, y_fmt)
    if x_labels:
        shown = [m for m in x_ticks if m * 60 <= end]
        parts += [f'<text x="{sx(m * 60)}" y="{height - 3}" text-anchor="middle">{ev.num(m, 0)}'
                  f'{" min" if m == shown[-1] else ""}</text>' for m in shown]
    parts.append(f'<line class="axis" x1="{pad_left}" x2="{PANEL}" y1="{base}" y2="{base}"/>')
    if cap:
        parts.append(f'<line class="cap" x1="{pad_left}" x2="{PANEL}" '
                     f'y1="{_y(base, inner, top, y_max)}" y2="{_y(base, inner, top, y_max)}"/>'
                     f'<text x="{PANEL}" y="{_y(base, inner, top, y_max) - 3}" '
                     f'text-anchor="end">{cap}</text>')
    for st in stages:
        if st["start_s"] is None:
            continue
        x = sx(st["start_s"])
        long = st["part"] == ev.LONG_TEXT_PART
        parts.append(f'<line class="stage" x1="{x}" x2="{x}" y1="{pad_top - 8}" y2="{base}"/>')
        if stage_tips:
            stop = st["end_s"] if st["end_s"] is not None else end
            label = f'{"Langtext, " if long else ""}Stufe {st["stage"]}'
            parts.append(f'<g class="hit"><title>{escape(row["name"])} · {label}: '
                         f'{_clock(st["start_s"])}–{_clock(stop)}</title><rect x="{x}" '
                         f'y="{pad_top}" width="{round(max(sx(stop) - x, 1), 1)}" '
                         f'height="{inner}"/></g>'
                         f'<text x="{x + 3}" y="10">{"L" if long else ""}'
                         f'{st["stage"]}</text>')
    for label, color, points in lines:
        for segment in _segments(points):
            coords = " ".join(f"{sx(t)},{_y(base, inner, y, y_max)}" for t, y in segment)
            parts.append(f'<polyline class="line thin" points="{coords}" '
                         f'style="stroke:{color}"><title>'
                         f'{escape(row["name"])} · {title} {label}</title></polyline>')
    return (f'<svg class="chart" viewBox="0 0 {PANEL} {height}" role="img">'
            + "".join(parts) + "</svg>")


def _clock(seconds: float) -> str:
    """Zeit seit Laufbeginn als m:ss."""
    s = round(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _y(base: float, inner: float, value: float, y_max: float) -> float:
    return round(base - min(value, y_max) / y_max * inner, 1)


def _y_grid(pad_left: float, base: float, inner: float, ticks: list[float], y_fmt) -> list[str]:
    """Waagerechte Gitterlinien mit Beschriftung links für die Felder in .panels, ohne die 0."""
    parts = []
    for t in ticks[1:]:
        y = _y(base, inner, t, ticks[-1])
        parts.append(f'<line class="grid" x1="{pad_left}" x2="{PANEL}" y1="{y}" y2="{y}"/>'
                     f'<text x="{pad_left - 4}" y="{y + 3}" text-anchor="end">{y_fmt(t)}</text>')
    return parts


def _stages(rows: list[dict]) -> list[int]:
    return sorted({s["stage"] for r in rows for s in r["stages"]})


def _xy_chart(lines, hovers, xs, *, top: float, y_fmt, x_title: str, refs=(),
              height: int = 240) -> str:
    """Liniendiagramm über den Stufen. lines: (Farbindex, [(x, y)], gestrichelt), y None lässt
    eine Lücke; hovers: (x, (y, …), Tooltip) als unsichtbare Trefferfläche um die Punkte; xs:
    beschriftete x-Werte; refs: (y, Text) als waagerechte Linien. Die y-Achse beginnt bei 0 und
    endet am nächsten runden Wert über top; was darüber liegt, steht am oberen Rand."""
    ticks = _nice_ticks(top)
    y_max = ticks[-1]
    pad_left, pad_bottom, pad_top, inset = 44, 20, 8, 14
    lo, hi = xs[0], xs[-1]

    def sx(x):
        share = (x - lo) / (hi - lo) if hi > lo else 0.5
        return round(pad_left + inset + share * (WIDE - pad_left - 2 * inset), 1)

    def sy(y):
        return round(pad_top + (1 - min(y, y_max) / y_max) * (height - pad_top - pad_bottom), 1)

    parts = [f'<line class="grid" x1="{pad_left}" x2="{WIDE}" y1="{sy(t)}" y2="{sy(t)}"/>'
             f'<text x="{pad_left - 4}" y="{sy(t) + 3}" text-anchor="end">{y_fmt(t)}</text>'
             for t in ticks]
    parts += [f'<text x="{sx(x)}" y="{height - 6}" text-anchor="middle">{x}</text>' for x in xs]
    parts.append(f'<line class="axis" x1="{pad_left}" x2="{WIDE}" y1="{sy(0)}" y2="{sy(0)}"/>')
    parts += [f'<line class="ref" x1="{pad_left}" x2="{WIDE}" y1="{sy(y)}" y2="{sy(y)}"/>'
              f'<text class="mark" x="{WIDE}" y="{sy(y) - 4}" text-anchor="end">{label}</text>'
              for y, label in refs if y <= y_max]
    for color, points, dashed in lines:
        for segment in _segments(points):
            coords = " ".join(f"{sx(x)},{sy(y)}" for x, y in segment)
            parts.append(f'<polyline class="line{" dashed" if dashed else ""}" points="{coords}" '
                         f'style="stroke:{_color(color)}"/>')
            parts += [f'<circle class="dot" cx="{sx(x)}" cy="{sy(y)}" r="{3 if dashed else 4}" '
                      f'style="fill:{_color(color)}"/>' for x, y in segment]
            parts += [f'<text x="{sx(x) + 6}" y="{pad_top + 4}">▲ {y_fmt(y)}</text>'
                      for x, y in segment if y > y_max and not dashed]
    for x, ys, tip in hovers:
        hits = "".join(f'<circle cx="{sx(x)}" cy="{sy(y)}" r="9"/>' for y in ys if y is not None)
        parts.append(f'<g class="hit"><title>{escape(tip)}</title>{hits}</g>')
    parts.append(f'<text x="{WIDE}" y="{sy(0) - 4}" text-anchor="end">{x_title}</text>')
    return (f'<svg class="chart" viewBox="0 0 {WIDE} {height}" role="img">'
            + "".join(parts) + "</svg>")


def _segments(points):
    """Zusammenhängende Stücke einer Linie; ein fehlender Wert unterbricht sie."""
    segment = []
    for x, y in points:
        if y is None:
            if segment:
                yield segment
            segment = []
        else:
            segment.append((x, y))
    if segment:
        yield segment


def _nice_ticks(top: float, count: int = 4) -> list[float]:
    """0 und runde Schritte (1, 2, 2,5, 5 mal 10ⁿ) bis mindestens top."""
    if top <= 0:
        return [0, 1]
    raw = top / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    return [i * step for i in range(math.ceil(top / step - 1e-9) + 1)]


def _color(i: int) -> str:
    return f"var(--c{i % COLORS + 1})"


def _empty(text: str) -> str:
    return f'<p class="hint">{text}</p>'


# ---------- Zahlen wie in /auswertung (report.js), dazu ev.num und ev.gib ----------

def _int(v) -> str:
    return "–" if v is None else f"{round(v):,}".replace(",", ".")


def _ms(v) -> str:
    if v is None:
        return "–"
    return f"{round(v)} ms" if v < 1000 else f"{ev.num(v / 1000)} s"


def _percent(v) -> str:
    return "–" if v is None else f"{ev.num(v * 100, 0)} %"


def _seconds(v) -> str:
    """Achsen und Grenzen: ganze Sekunden, "20 s"."""
    return f"{ev.num(v / 1000, 0)} s"


if __name__ == "__main__":
    sys.exit(main())
