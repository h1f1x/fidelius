"""Auswertung des Request-Logs."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

ZEITRAEUME = {"24h": timedelta(hours=24), "7t": timedelta(days=7), "30t": timedelta(days=30),
              "alles": None}
# Laut Spec nur bei den kurzen Zeiträumen ein Vergleich mit der gleich langen Vorperiode.
MIT_VERGLEICH = {"24h", "7t"}


def lesen(pfad: Path) -> tuple[list[dict], int, int]:
    """Alle brauchbaren Einträge, die Zahl der nicht leeren Zeilen und die der kaputten."""
    if not pfad.is_file():
        return [], 0, 0
    eintraege, zeilen, kaputt = [], 0, 0
    for zeile in pfad.read_text(encoding="utf-8", errors="replace").splitlines():
        if not zeile.strip():
            continue
        zeilen += 1
        e = _eintrag(zeile)
        if e is None:
            kaputt += 1
        else:
            eintraege.append(e)
    return eintraege, zeilen, kaputt


def _zahl(v) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _eintrag(zeile: str) -> dict | None:
    """Ohne Zeitpunkt, Zeichenzahl und Gesamtzeit ist eine Zeile nicht auswertbar."""
    try:
        e = json.loads(zeile)
        e["_t"] = datetime.fromisoformat(e["zeit"]).astimezone(UTC)
    except (ValueError, TypeError, KeyError):
        return None
    if not (_zahl(e.get("zeichen")) and _zahl(e.get("gesamt_ms"))):
        return None
    return e


def auswerten(pfad: str | Path, zeitraum: str, jetzt: datetime | None = None) -> dict:
    pfad = Path(pfad)
    jetzt = jetzt or datetime.now(UTC)
    alle, zeilen, kaputt = lesen(pfad)
    dauer = ZEITRAEUME[zeitraum]
    drin = alle if dauer is None else _zwischen(alle, jetzt - dauer, jetzt)
    anfragen = _anfragen(drin)
    vorher = []
    if zeitraum in MIT_VERGLEICH:
        vorher = _anfragen(_zwischen(alle, jetzt - 2 * dauer, jetzt - dauer))
    return {
        "log": {"pfad": str(pfad), "vorhanden": zeilen > 0, "zeilen": zeilen, "kaputt": kaputt},
        "kennzahlen": _kennzahlen(anfragen),
        "vorperiode": _kennzahlen(vorher) if vorher else None,
        "phasen": _phasen(anfragen),
    }


def _erkennung_lief(e: dict) -> bool:
    return bool(e.get("sensibel") or e.get("trotzdem"))


def _laya_lief(e: dict) -> bool:
    # Wie in pipeline.analyze: Ohne Gate-Wert war Laya nicht erreichbar, die Bestätigung entfällt.
    return _erkennung_lief(e) and bool(e.get("laya_bestaetigung")) and e.get("gate_wert") is not None


def _verteilung(werte: list) -> dict:
    return {"anzahl": len(werte), "median_ms": perzentil(werte, 50),
            "p90_ms": perzentil(werte, 90), "p99_ms": perzentil(werte, 99)}


def _phasen(anfragen: list[dict]) -> dict:
    return {
        "gate": _verteilung([e.get("gate_ms", 0) for e in anfragen]),
        "erkennung": _verteilung([e.get("erkennung_ms", 0) for e in anfragen if _erkennung_lief(e)]),
        "laya": _verteilung([e.get("laya_ms", 0) for e in anfragen if _laya_lief(e)]),
        "gesamt": _verteilung([e["gesamt_ms"] for e in anfragen]),
    }


def _zwischen(eintraege: list[dict], anfang: datetime, ende: datetime) -> list[dict]:
    return [e for e in eintraege if anfang < e["_t"] <= ende]


def _anfragen(eintraege: list[dict]) -> list[dict]:
    return [e for e in eintraege if e.get("quelle") != "kalibrierung"]


def perzentil(werte: list, p: int):
    """Nearest-Rank: der kleinste Wert, unter oder auf dem mindestens p % der Werte liegen."""
    if not werte:
        return None
    s = sorted(werte)
    return s[max(0, -(-p * len(s) // 100) - 1)]


def _je_1000(e: dict) -> float | None:
    return e["gesamt_ms"] / e["zeichen"] * 1000 if e["zeichen"] else None


def _anteil(n: int, von: int) -> float | None:
    return round(n / von, 4) if von else None


def _kennzahlen(anfragen: list[dict]) -> dict:
    gesamt = [e["gesamt_ms"] for e in anfragen]
    je_1000 = perzentil([v for e in anfragen if (v := _je_1000(e)) is not None], 50)
    fehler = sum(bool(e.get("fehler")) for e in anfragen)
    return {
        "anfragen": len(anfragen),
        "gesamt_median_ms": perzentil(gesamt, 50),
        "gesamt_p90_ms": perzentil(gesamt, 90),
        "je_1000_median_ms": None if je_1000 is None else round(je_1000, 1),
        "fehler": fehler,
        "fehlerquote": _anteil(fehler, len(anfragen)),
        "sensibel_anteil": _anteil(sum(bool(e.get("sensibel")) for e in anfragen), len(anfragen)),
    }
