"""Auswertung des Request-Logs, Spec: docs/specs/request-log-auswertung.md.

Liest das ganze Log bei jedem Aufruf (10.000 Anfragen ~ 3 MB). Kaputte Zeilen werden gezählt und
übersprungen. Alle Kennzahlen außer „kalibrierung“ beziehen sich nur auf quelle = anfrage.
Perzentile nach Nearest-Rank. Zeiten in der Antwort sind ISO 8601 in Europe/Berlin, Dauern in ms,
Anteile als Bruch (0.2 = 20 %). Ohne Werte steht null.

Antwort von auswerten() bzw. GET /api/auswertung?zeitraum=24h|7t|30t|alles (Standard 30t):

    zeitraum        "24h" | "7t" | "30t" | "alles"
    log             {pfad, vorhanden, zeilen, kaputt}; vorhanden = false: Datei fehlt oder ist leer
    kennzahlen      {anfragen, gesamt_median_ms, gesamt_p90_ms, je_1000_median_ms,
                     fehler, fehlerquote, sensibel_anteil}
    vorperiode      wie kennzahlen, für die gleich lange Periode davor; null bei alles oder leerer Vorperiode
                    oder wenn die Vorperiode keine Anfragen hat („kein Vergleich“)
    phasen          {gate, erkennung, laya, gesamt}, je {anzahl, median_ms, p90_ms, p99_ms};
                    eine Phase zählt nur bei Anfragen, in denen sie lief
    histogramm      {bis_ms, breite_ms, anzahl: [24 Zahlen]}; Balken i deckt
                    [i·breite_ms, (i+1)·breite_ms), bis_ms = p99, Werte darüber zählen im letzten
    laengenklassen  [{label, bis_zeichen, anzahl, median_ms, p90_ms}], 5 Klassen à 3.300 Zeichen,
                    bis_zeichen = null bei der letzten
    streuung        [[zeichen, gesamt_ms, build]], ein Punkt je Anfrage; build wie builds[].name
    nutzung         {tage: [{tag: "JJJJ-MM-TT", anzahl}] lückenlos über den Zeitraum,
                     stunden: [24 Zahlen], Index = Stunde in Berliner Zeit}
    builds          [{name, nummer, commit, dirty, erste, letzte, anfragen, median_ms, p90_ms,
                     je_1000_median_ms, abweichung_vorgaenger}], sortiert nach erstem Auftauchen;
                    name z. B. "#37 · 0d15b11" („*“ = dirty); erste/letzte inkl. Kalibrierung;
                    abweichung_vorgaenger je 1.000 Zeichen zum letzten Build mit Anfragen
                    (0.2 = 20 % langsamer, negativ = schneller)
    kalibrierung    {texte: [Zeichenzahlen], zeilen: [{build, laeufe, median_ms: [je Text]}]}
    fehler          [{text, anzahl, zuletzt}], häufigste zuerst

GET /api/request-log liefert die Rohdatei als application/x-ndjson, 404 wenn sie fehlt.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Das Log bleibt in UTC; Tage und Stunden zählen so, wie die Nutzer sie erleben.
BERLIN = ZoneInfo("Europe/Berlin")

ZEITRAEUME = {"24h": timedelta(hours=24), "7t": timedelta(days=7), "30t": timedelta(days=30),
              "alles": None}
# Vergleich mit der gleich langen Vorperiode; „alles“ hat keine.
MIT_VERGLEICH = {"24h", "7t", "30t"}
BALKEN = 24
SEITE = 3300  # Zeichen, wie die Seitenangabe in der Haupt-UI
LAENGENKLASSEN = [("≤ 1 Seite", SEITE), ("1–3 Seiten", 3 * SEITE), ("3–7 Seiten", 7 * SEITE),
                  ("7–15 Seiten", 15 * SEITE), ("> 15 Seiten", None)]


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
    if zeitraum not in ZEITRAEUME:
        raise ValueError(f"Unbekannter Zeitraum {zeitraum!r}, erlaubt: {', '.join(ZEITRAEUME)}")
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
        "zeitraum": zeitraum,
        "log": {"pfad": str(pfad), "vorhanden": zeilen > 0, "zeilen": zeilen, "kaputt": kaputt},
        "kennzahlen": _kennzahlen(anfragen),
        "vorperiode": _kennzahlen(vorher) if vorher else None,
        "phasen": _phasen(anfragen),
        "histogramm": _histogramm([e["gesamt_ms"] for e in anfragen]),
        "laengenklassen": _laengenklassen(anfragen),
        "streuung": [[e["zeichen"], e["gesamt_ms"], build_name(e.get("build"))] for e in anfragen],
        "nutzung": _nutzung(anfragen, None if dauer is None else jetzt - dauer, jetzt),
        "builds": _builds(drin),
        "kalibrierung": _kalibrierung(drin),
        "fehler": _fehler(anfragen),
    }


def _fehler(anfragen: list[dict]) -> list[dict]:
    # strip: pipeline.analyze hängt den Hinweis zur Laya-Bestätigung mit führendem Leerzeichen an.
    gruppen: dict[str, list[datetime]] = {}
    for e in anfragen:
        if e.get("fehler"):
            gruppen.setdefault(str(e["fehler"]).strip(), []).append(e["_t"])
    liste = [{"text": text, "anzahl": len(zeiten), "zuletzt": _berlin(max(zeiten))}
             for text, zeiten in gruppen.items()]
    return sorted(liste, key=lambda f: (-f["anzahl"], f["text"]))


def _berlin(t: datetime) -> str:
    return t.astimezone(BERLIN).isoformat()


def _nach_build(eintraege: list[dict]) -> dict[str, list[dict]]:
    """Gruppiert nach Build, in der Reihenfolge, in der die Builds zuerst auftauchen."""
    gruppen: dict[str, list[dict]] = {}
    for e in sorted(eintraege, key=lambda e: e["_t"]):
        gruppen.setdefault(build_name(e.get("build")), []).append(e)
    return gruppen


def _builds(eintraege: list[dict]) -> list[dict]:
    """Verglichen wird je 1.000 Zeichen: Die Texte sind unterschiedlich lang, die reine Gesamtzeit
    würde Builds mit kürzeren Texten bevorzugen. Vorgänger ist der letzte Build mit Anfragen."""
    zeilen, vorgaenger = [], None
    for name, gruppe in _nach_build(eintraege).items():
        b = gruppe[0].get("build") if isinstance(gruppe[0].get("build"), dict) else {}
        k = _kennzahlen(_anfragen(gruppe))
        je_1000 = k["je_1000_median_ms"]
        abweichung = None
        if je_1000 is not None and vorgaenger:
            abweichung = round((je_1000 - vorgaenger) / vorgaenger, 4)
        if je_1000 is not None:
            vorgaenger = je_1000
        zeilen.append({
            "name": name, "nummer": b.get("number"), "commit": b.get("commit"),
            "dirty": bool(b.get("dirty")),
            "erste": _berlin(gruppe[0]["_t"]), "letzte": _berlin(gruppe[-1]["_t"]),
            "anfragen": k["anfragen"], "median_ms": k["gesamt_median_ms"],
            "p90_ms": k["gesamt_p90_ms"], "je_1000_median_ms": je_1000,
            "abweichung_vorgaenger": abweichung,
        })
    return zeilen


def _kalibrierung(eintraege: list[dict]) -> dict:
    """Gleiche Texte machen Builds direkt vergleichbar; die Zeichenzahl kennzeichnet den Text."""
    kalib = [e for e in eintraege if e.get("quelle") == "kalibrierung"]
    texte = sorted({e["zeichen"] for e in kalib})
    zeilen = []
    for name, gruppe in _nach_build(kalib).items():
        median = [perzentil([e["gesamt_ms"] for e in gruppe if e["zeichen"] == z], 50)
                  for z in texte]
        zeilen.append({"build": name, "laeufe": len(gruppe), "median_ms": median})
    return {"texte": texte, "zeilen": zeilen}


def _nutzung(anfragen: list[dict], anfang: datetime | None, ende: datetime) -> dict:
    """Tage in Berliner Zeit, lückenlos vom Anfang des Zeitraums bis heute; bei „alles“ von der
    ersten bis zur letzten Anfrage."""
    tage: dict[date, int] = {}
    stunden = [0] * 24
    for e in anfragen:
        t = e["_t"].astimezone(BERLIN)
        tage[t.date()] = tage.get(t.date(), 0) + 1
        stunden[t.hour] += 1
    if anfang is None:
        if not tage:
            return {"tage": [], "stunden": stunden}
        erster, letzter = min(tage), max(tage)
    else:
        erster, letzter = anfang.astimezone(BERLIN).date(), ende.astimezone(BERLIN).date()
    alle_tage = [erster + timedelta(days=i) for i in range((letzter - erster).days + 1)]
    return {"tage": [{"tag": d.isoformat(), "anzahl": tage.get(d, 0)} for d in alle_tage],
            "stunden": stunden}


def build_name(b) -> str:
    if not isinstance(b, dict):
        return "unbekannt"
    nummer = "?" if b.get("number") is None else b["number"]
    dirty = "*" if b.get("dirty") else ""
    return f"#{nummer} · {b.get('commit') or '?'}{dirty}"


def _histogramm(werte: list) -> dict:
    """Bis p99, damit einzelne Ausreißer die Skala nicht stauchen; sie zählen im letzten Balken."""
    bis = perzentil(werte, 99)
    if not bis:
        return {"bis_ms": bis, "breite_ms": None, "anzahl": [len(werte)] if werte else []}
    breite = bis / BALKEN
    anzahl = [0] * BALKEN
    for v in werte:
        anzahl[min(BALKEN - 1, int(v / breite))] += 1
    return {"bis_ms": bis, "breite_ms": breite, "anzahl": anzahl}


def _laengenklassen(anfragen: list[dict]) -> list[dict]:
    klassen = [{"label": label, "bis_zeichen": bis, "werte": []} for label, bis in LAENGENKLASSEN]
    for e in anfragen:
        k = next(k for k in klassen if k["bis_zeichen"] is None or e["zeichen"] <= k["bis_zeichen"])
        k["werte"].append(e["gesamt_ms"])
    return [{"label": k["label"], "bis_zeichen": k["bis_zeichen"], "anzahl": len(k["werte"]),
             "median_ms": perzentil(k["werte"], 50), "p90_ms": perzentil(k["werte"], 90)}
            for k in klassen]


def _erkennung_lief(e: dict) -> bool:
    return bool(e.get("sensibel") or e.get("trotzdem"))


def _laya_lief(e: dict) -> bool:
    # Wie in pipeline.analyze: Ohne Gate-Wert war Laya nicht erreichbar, die Bestätigung entfällt.
    return (_erkennung_lief(e) and bool(e.get("laya_bestaetigung"))
            and e.get("gate_wert") is not None)


def _verteilung(werte: list) -> dict:
    werte = [v for v in werte if _zahl(v)]
    return {"anzahl": len(werte), "median_ms": perzentil(werte, 50),
            "p90_ms": perzentil(werte, 90), "p99_ms": perzentil(werte, 99)}


def _phasen(anfragen: list[dict]) -> dict:
    return {
        "gate": _verteilung([e.get("gate_ms") for e in anfragen]),
        "erkennung": _verteilung([e.get("erkennung_ms") for e in anfragen if _erkennung_lief(e)]),
        "laya": _verteilung([e.get("laya_ms") for e in anfragen if _laya_lief(e)]),
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
