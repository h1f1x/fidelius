#!/usr/bin/env python3
"""Schickt Kalibrierbeispiele an die laufende App und vergleicht mit der expected.json daneben.

Aufruf (App läuft unter http://localhost:8080, Klassifikation an):
    python3 scripts/run_classification.py                          # examples/klassifikation
    python3 scripts/run_classification.py --dir local/klassifikation-beispiele
    python3 scripts/run_classification.py 03 07                    # nur Texte mit diesem Präfix
    python3 scripts/run_classification.py --zugang-threshold 0.8   # andere Zugangsdaten-Schwelle
    python3 scripts/run_classification.py --json out.json          # Rohergebnis speichern

Die expected.json ordnet jedem Text (Dateiname ohne .txt) die erwartete Stufe zu und ob er
Zugangsdaten enthält: {"01_pressemitteilung": {"stufe": "oeffentlich", "zugangsdaten": false}}

Jeder Text geht an POST /api/classify. Die Stufe kommt so, wie die App sie mit ihrer `schwelle`
bestimmt. Zugangsdaten zählen, wenn ein Abschnitt bei `zugang` den Wert --zugang-threshold
erreicht, wie ZUGANG_THRESHOLD in der App; so lässt sich die Schwelle ohne Neustart erproben.
Treffer der Regex-Muster für ZUGANG zählen hier nicht mit, denn /api/classify fragt nur Laya.

Ausgabe: je Text erwartete und erkannte Stufe, höchster `zugang`-Wert, dann die
Konfusionsmatrix der Stufen (Zeilen erwartet, Spalten erkannt) und die Trefferquote für
Zugangsdaten. Exit-Code 0 nur, wenn alles stimmt.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "examples" / "klassifikation"


@dataclass
class Evaluation:
    levels: list[str]
    matrix: dict[str, dict[str, int]]
    levels_hit: int = 0
    misses: list[tuple[str, str, str]] = field(default_factory=list)  # (Text, erwartet, erkannt)
    credentials_hit: int = 0
    credentials_total: int = 0                                       # Texte mit Zugangsdaten laut Soll
    credentials_missed: list[str] = field(default_factory=list)
    credentials_false: list[str] = field(default_factory=list)       # erkannt, laut Soll ohne


def max_credentials(result: dict) -> float | None:
    """Höchster `zugang`-Wert über alle Abschnitte, None, wenn die App `zugang` nicht gefragt hat."""
    values = [c["credentials"] for c in result["chunks"] if c.get("credentials") is not None]
    return max(values) if values else None


def level_order(expected: dict, results: dict) -> list[str]:
    """Stufen in Rangfolge: Die App liefert die Wahrscheinlichkeiten in der Reihenfolge der
    Regeldatei. Stufen, die nur in der expected.json stehen, kommen hinten dran."""
    levels: list[str] = []
    for r in results.values():
        for chunk in r["chunks"]:
            levels += [lv for lv in chunk["probabilities"] if lv not in levels]
    for e in expected.values():
        if e["stufe"] not in levels:
            levels.append(e["stufe"])
    return levels


def evaluate(expected: dict, results: dict, credentials_threshold: float) -> Evaluation:
    """Vergleicht die Antworten von /api/classify mit der expected.json, je Text unter seinem Namen."""
    levels = level_order(expected, results)
    ev = Evaluation(levels=levels, matrix={e: {a: 0 for a in levels} for e in levels})
    for name in sorted(results):
        want, got = expected[name]["stufe"], results[name]["level"]
        ev.matrix[want][got] += 1
        if want == got:
            ev.levels_hit += 1
        else:
            ev.misses.append((name, want, got))
        want_creds = bool(expected[name].get("zugangsdaten", False))
        score = max_credentials(results[name])
        got_creds = score is not None and score >= credentials_threshold
        if want_creds:
            ev.credentials_total += 1
            if got_creds:
                ev.credentials_hit += 1
            else:
                ev.credentials_missed.append(name)
        elif got_creds:
            ev.credentials_false.append(name)
    return ev


def format_matrix(ev: Evaluation) -> str:
    """Konfusionsmatrix als Text, Zeilen erwartete Stufe, Spalten erkannte Stufe."""
    corner = "Soll \\ Ist"
    width = max(len(corner), *(len(lv) for lv in ev.levels))
    lines = [corner.ljust(width) + "".join(f"  {lv}" for lv in ev.levels)]
    for want in ev.levels:
        cells = "".join(f"  {ev.matrix[want][got]:>{len(got)}}" for got in ev.levels)
        lines.append(want.ljust(width) + cells)
    return "\n".join(lines)


def classify(url: str, text: str) -> dict:
    req = urllib.request.Request(f"{url}/api/classify", data=json.dumps({"text": text}).encode(),
                                 headers={"content-type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=600))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prefixes", nargs="*")
    ap.add_argument("--url", default="http://localhost:8080")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="Verzeichnis mit *.txt und expected.json")
    ap.add_argument("--zugang-threshold", type=float, default=0.9,
                    help="ab diesem zugang-Wert zählen Zugangsdaten, wie ZUGANG_THRESHOLD (Standard 0.9)")
    ap.add_argument("--json", help="Rohantworten von /api/classify in diese Datei schreiben")
    args = ap.parse_args()

    expected = json.loads((args.dir / "expected.json").read_text(encoding="utf-8"))
    files = sorted(p for p in args.dir.glob("*.txt")
                   if not args.prefixes or any(p.name.startswith(x) for x in args.prefixes))
    unknown = [p.stem for p in files if p.stem not in expected]
    if unknown:
        print(f"Ohne Eintrag in expected.json: {', '.join(unknown)}", file=sys.stderr)
        return 2

    results = {}
    for p in files:
        try:
            r = classify(args.url, p.read_text(encoding="utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                print("Die App klassifiziert nicht: CLASSIFICATION_ENABLED=1 und eine gültige "
                      "local/klassifikation.yaml nötig, siehe README.", file=sys.stderr)
                return 2
            raise
        results[p.stem] = r
        want = expected[p.stem]
        score = max_credentials(r)
        mark = "  " if r["level"] == want["stufe"] else "✗ "
        creds = "-" if score is None else f"{score:.2f}"
        print(f"{mark}{p.stem:40} Soll {want['stufe']:20} Ist {r['level']:20} "
              f"zugang {creds}{' (Soll ja)' if want.get('zugangsdaten') else ''}")

    ev = evaluate(expected, results, args.zugang_threshold)
    print(f"\n{format_matrix(ev)}")
    print(f"\nStufen: {ev.levels_hit}/{len(results)} richtig")
    if ev.credentials_total:
        print(f"Zugangsdaten ab {args.zugang_threshold}: {ev.credentials_hit}/{ev.credentials_total} erkannt"
              f" = {ev.credentials_hit / ev.credentials_total:.0%}")
    for name in ev.credentials_missed:
        print(f"  ÜBERSEHEN  {name}")
    for name in ev.credentials_false:
        print(f"  FEHLALARM  {name}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if not ev.misses and not ev.credentials_missed and not ev.credentials_false else 1


if __name__ == "__main__":
    sys.exit(main())
