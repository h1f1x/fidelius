#!/usr/bin/env python3
"""Schickt alle Beispielmails durch die laufende App und vergleicht mit examples/expected.json.

Aufruf (App läuft unter http://localhost:8080):
    python3 scripts/run_examples.py                # alle Beispiele
    python3 scripts/run_examples.py 05 06          # nur Beispiele mit diesem Präfix
    python3 scripts/run_examples.py --no-force     # Gate entscheidet, ob erkannt wird
    python3 scripts/run_examples.py -q             # nur Abgleich, keine Trefferliste
    python3 scripts/run_examples.py --json out.json  # Rohergebnis speichern

Ausgabe je Beispiel: Gate-Wert, alle Treffer mit Quellen und Laya-Urteil, dann der Abgleich:
  FEHLT     Soll-Treffer, der nicht ersetzt wurde (zu schwach)
  ZU VIEL   Wert, der laut expected.json stehen bleiben muss, aber ersetzt wurde (zu stark)
  EXTRA     ersetzt, aber in expected.json nicht aufgeführt (zur Durchsicht)
Am Ende eine Gesamtzeile mit Recall über die Soll-Treffer und der Zahl der Verstöße.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
BADGE = {"gliner": "G", "spacy": "S", "regex": "R"}


def analyze(url: str, text: str, force: bool) -> dict:
    req = urllib.request.Request(f"{url}/api/analyze", data=json.dumps({"text": text, "force": force}).encode(),
                                 headers={"content-type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=600))


def norm(s: str) -> str:
    return " ".join(s.split()).casefold()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prefixes", nargs="*")
    ap.add_argument("--url", default="http://localhost:8080")
    ap.add_argument("--no-force", action="store_true")
    ap.add_argument("--json")
    ap.add_argument("--quiet", "-q", action="store_true", help="nur Abgleich, keine Trefferliste")
    args = ap.parse_args()

    exp_file = EX / "expected.json"
    expected = json.loads(exp_file.read_text(encoding="utf-8")) if exp_file.exists() else {}
    files = sorted(p for p in EX.glob("*.txt")
                   if not args.prefixes or any(p.name.startswith(x) for x in args.prefixes))
    total_must = total_found = total_bad = 0
    raw = {}
    for p in files:
        text = p.read_text(encoding="utf-8")
        r = analyze(args.url, text, not args.no_force)
        raw[p.stem] = r
        g, t = r["gate"], r["timing"]
        gp = "n/a" if g["probability"] is None else f"{g['probability']:.2f}"
        print(f"\n=== {p.stem}  Gate {gp} → {'sensibel' if g['sensitive'] else 'unauffällig'}"
              f"  | Gate {t['gate_ms']} ms, Erkennung {t['detect_ms']} ms, Laya {t['laya_check_ms']} ms")
        accepted = [e for e in r["entities"] if e["placeholder"]]
        if not args.quiet:
            for e in r["entities"]:
                src = "+".join(BADGE[s["name"]] for s in e["sources"])
                laya = ""
                if e["laya"]:
                    laya = f"  L:{e['laya']['category']} {e['laya']['probability']:.2f}"
                    if e["laya"]["recategorized_from"]:
                        laya += f" (war {e['laya']['recategorized_from']})"
                mark = "  " if e["placeholder"] else "✗ "
                print(f"  {mark}{e['placeholder'] or '-':13} {e['category']:8} {e['text']!r:42} {src}{laya}")
        exp = expected.get(p.stem)
        if not exp:
            print("  (keine Soll-Treffer hinterlegt)")
            continue
        acc_norm = {(norm(e["text"]), e["category"]) for e in accepted}
        acc_texts = {norm(e["text"]) for e in accepted}
        must = [(norm(m["text"]), m["category"]) for m in exp.get("must", [])]
        found = [m for m in must if m in acc_norm
                 or any((m[0] in a or a in m[0]) for a in acc_texts if len(a) >= 4)]
        missing = [m for m in must if m not in found]
        keep = [norm(k) for k in exp.get("keep", [])]
        wrongly = [k for k in keep if k in acc_texts]
        listed = {m[0] for m in must}
        extra = sorted(a for a in acc_texts if a not in listed and not any(a in m or m in a for m in listed))
        total_must += len(must)
        total_found += len(found)
        total_bad += len(wrongly)
        for m in missing:
            print(f"  FEHLT    {m[1]:8} {m[0]!r}")
        for k in wrongly:
            print(f"  ZU VIEL           {k!r}")
        if extra:
            print(f"  EXTRA    {', '.join(repr(x) for x in extra)}")
        print(f"  → {len(found)}/{len(must)} Soll-Treffer, {len(wrongly)} zu viel, {len(extra)} extra")
    if total_must:
        print(f"\nGESAMT: Recall {total_found}/{total_must} = {total_found / total_must:.0%}, "
              f"{total_bad} zu viel ersetzt")
    if args.json:
        Path(args.json).write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if total_bad == 0 and total_found == total_must else 1


if __name__ == "__main__":
    sys.exit(main())
