"""Auswertung des Request-Logs, Spec: docs/specs/request-log-auswertung.md.

Liest das ganze Log bei jedem Aufruf (10.000 Anfragen ~ 3 MB). Kaputte Zeilen werden gezählt und
übersprungen. Alle Kennzahlen außer „calibration“ beziehen sich nur auf quelle = anfrage.
Perzentile nach Nearest-Rank. Zeiten in der Antwort sind ISO 8601 in Europe/Berlin, Dauern in ms,
Anteile als Bruch (0.2 = 20 %). Ohne Werte steht null. Die Feldnamen der Antwort sind englisch,
die des Logs selbst (zeichen, gesamt_ms, …) bleiben wie in docs/specs/laufzeit-und-request-log.md.

Antwort von report() bzw. GET /api/report?period=24h|7d|30d|all (Standard 30d):

    period          "24h" | "7d" | "30d" | "all"
    page_chars      Zeichen je Seite (3.300), Grundlage der Längenklassen
    log             {path, present, lines, broken}; present = false: Datei fehlt oder ist leer
    metrics         {requests, total_median_ms, total_p90_ms, per_1000_median_ms,
                     error_count, error_rate, sensitive_share}
    previous        wie metrics, für die gleich lange Periode davor; null bei all oder wenn die
                    Vorperiode keine Anfragen hat („kein Vergleich“)
    phases          {gate, detection, laya, total}, je {count, median_ms, p90_ms, p99_ms};
                    eine Phase zählt nur bei Anfragen, in denen sie lief
    histogram       {max_ms, width_ms, counts: [24 Zahlen]}; Balken i deckt
                    [i·width_ms, (i+1)·width_ms), max_ms = p99, Werte darüber zählen im letzten
    length_classes  [{label, max_chars, count, median_ms, p90_ms}], 5 Klassen à page_chars,
                    max_chars = null bei der letzten
    scatter         [[zeichen, gesamt_ms, build]], ein Punkt je Anfrage; build wie builds[].name
    usage           {days: [{day: "JJJJ-MM-TT", count}] lückenlos über den Zeitraum,
                     hours: [24 Zahlen], Index = Stunde in Berliner Zeit}
    builds          [{name, number, commit, dirty, first, last, requests, median_ms, p90_ms,
                     per_1000_median_ms, change_vs_previous}], sortiert nach erstem Auftauchen;
                    name z. B. "#37 · 0d15b11" („*“ = dirty); first/last inkl. Kalibrierung;
                    change_vs_previous je 1.000 Zeichen zum letzten Build mit Anfragen davor,
                    bestimmt über das ganze Log, auch außerhalb des Zeitraums
                    (0.2 = 20 % langsamer, negativ = schneller)
    calibration     {texts: [Zeichenzahlen], rows: [{build, runs, median_ms: [je Text]}]}
    errors          [{text, count, last}], häufigste zuerst

GET /api/request-log liefert die Rohdatei als application/x-ndjson, 404 wenn sie fehlt.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Das Log bleibt in UTC; Tage und Stunden zählen so, wie die Nutzer sie erleben.
BERLIN = ZoneInfo("Europe/Berlin")

# Zeitraum → Länge; None hat keine gleich lange Vorperiode zum Vergleich.
PERIODS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30),
           "all": None}
BARS = 24
PAGE_CHARS = 3300  # Zeichen, wie die Seitenangabe in der Haupt-UI
LENGTH_CLASSES = [("≤ 1 Seite", PAGE_CHARS), ("1–3 Seiten", 3 * PAGE_CHARS),
                  ("3–7 Seiten", 7 * PAGE_CHARS), ("7–15 Seiten", 15 * PAGE_CHARS),
                  ("> 15 Seiten", None)]


def report(path: str | Path, period: str, now: datetime | None = None) -> dict:
    if period not in PERIODS:
        raise ValueError(f"Unbekannter Zeitraum {period!r}, erlaubt: {', '.join(PERIODS)}")
    path = Path(path)
    now = now or datetime.now(UTC)
    entries, lines, broken = _read(path)
    duration = PERIODS[period]
    in_period = entries if duration is None else _between(entries, now - duration, now)
    requests = _requests(in_period)
    before = [] if duration is None else _requests(_between(entries, now - 2 * duration, now - duration))
    return {
        "period": period,
        "page_chars": PAGE_CHARS,
        "log": {"path": str(path), "present": lines > 0, "lines": lines, "broken": broken},
        "metrics": _metrics(requests),
        "previous": _metrics(before) if before else None,
        "phases": _phases(requests),
        "histogram": _histogram([e["gesamt_ms"] for e in requests]),
        "length_classes": _length_classes(requests),
        "scatter": [[e["zeichen"], e["gesamt_ms"], _build_name(e.get("build"))] for e in requests],
        "usage": _usage(requests, None if duration is None else now - duration, now),
        "builds": _builds(in_period, entries),
        "calibration": _calibration(in_period),
        "errors": _errors(requests),
    }


# ---------- log ----------

def _read(path: Path) -> tuple[list[dict], int, int]:
    """Alle brauchbaren Einträge, die Zahl der nicht leeren Zeilen und die der kaputten."""
    if not path.is_file():
        return [], 0, 0
    entries, lines, broken = [], 0, 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        lines += 1
        entry = _entry(line)
        if entry is None:
            broken += 1
        else:
            entries.append(entry)
    return entries, lines, broken


def _entry(line: str) -> dict | None:
    """Ohne Zeitpunkt, Zeichenzahl und Gesamtzeit ist eine Zeile nicht auswertbar."""
    try:
        entry = json.loads(line)
        entry["_t"] = datetime.fromisoformat(entry["zeit"]).astimezone(UTC)
    except (ValueError, TypeError, KeyError):
        return None
    if not (_is_number(entry.get("zeichen")) and _is_number(entry.get("gesamt_ms"))):
        return None
    return entry


# ---------- metrics, previous ----------

def _metrics(requests: list[dict]) -> dict:
    totals = _distribution([e["gesamt_ms"] for e in requests])
    per_1000 = _percentile([v for e in requests if (v := _per_1000(e)) is not None], 50)
    errors = sum(bool(e.get("fehler")) for e in requests)
    return {
        "requests": len(requests),
        "total_median_ms": totals["median_ms"],
        "total_p90_ms": totals["p90_ms"],
        "per_1000_median_ms": None if per_1000 is None else round(per_1000, 1),
        "error_count": errors,
        "error_rate": _share(errors, len(requests)),
        "sensitive_share": _share(sum(bool(e.get("sensibel")) for e in requests), len(requests)),
    }


def _per_1000(e: dict) -> float | None:
    return e["gesamt_ms"] / e["zeichen"] * 1000 if e["zeichen"] else None


def _share(n: int, total: int) -> float | None:
    return round(n / total, 4) if total else None


# ---------- phases ----------

def _phases(requests: list[dict]) -> dict:
    return {
        "gate": _distribution([e.get("gate_ms") for e in requests]),
        "detection": _distribution([e.get("erkennung_ms") for e in requests if _detection_ran(e)]),
        "laya": _distribution([e.get("laya_ms") for e in requests if _laya_ran(e)]),
        "total": _distribution([e["gesamt_ms"] for e in requests]),
    }


def _detection_ran(e: dict) -> bool:
    return bool(e.get("sensibel") or e.get("trotzdem"))


def _laya_ran(e: dict) -> bool:
    # Bildet die Bedingung aus Pipeline.analyze (app/fidelius/pipeline.py) nach: Die
    # Laya-Bestätigung läuft nur nach der Erkennung, wenn sie gewünscht war und das Gate Laya
    # erreicht hat. Ohne Gate-Wert war Laya nicht erreichbar, die Bestätigung entfällt.
    return (_detection_ran(e) and bool(e.get("laya_bestaetigung"))
            and e.get("gate_wert") is not None)


# ---------- histogram ----------

def _histogram(values: list) -> dict:
    """Bis p99, damit einzelne Ausreißer die Skala nicht stauchen; sie zählen im letzten Balken."""
    upper = _percentile(values, 99)
    if not upper:
        return {"max_ms": upper, "width_ms": None, "counts": [len(values)] if values else []}
    width = upper / BARS
    counts = [0] * BARS
    for v in values:
        counts[min(BARS - 1, int(v / width))] += 1
    return {"max_ms": upper, "width_ms": width, "counts": counts}


# ---------- length_classes ----------

def _length_classes(requests: list[dict]) -> list[dict]:
    values: list[list] = [[] for _ in LENGTH_CLASSES]
    for e in requests:
        index = next(i for i, (_, upper) in enumerate(LENGTH_CLASSES)
                     if upper is None or e["zeichen"] <= upper)
        values[index].append(e["gesamt_ms"])
    rows = []
    for (label, upper), totals in zip(LENGTH_CLASSES, values):
        dist = _distribution(totals)
        rows.append({"label": label, "max_chars": upper, "count": dist["count"],
                     "median_ms": dist["median_ms"], "p90_ms": dist["p90_ms"]})
    return rows


# ---------- usage ----------

def _usage(requests: list[dict], start: datetime | None, end: datetime) -> dict:
    """Tage in Berliner Zeit, lückenlos vom Anfang des Zeitraums bis heute; bei „all“ von der
    ersten bis zur letzten Anfrage."""
    days: dict[date, int] = {}
    hours = [0] * 24
    for e in requests:
        t = e["_t"].astimezone(BERLIN)
        days[t.date()] = days.get(t.date(), 0) + 1
        hours[t.hour] += 1
    if start is None:
        if not days:
            return {"days": [], "hours": hours}
        first, last = min(days), max(days)
    else:
        first, last = start.astimezone(BERLIN).date(), end.astimezone(BERLIN).date()
    all_days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    return {"days": [{"day": d.isoformat(), "count": days.get(d, 0)} for d in all_days],
            "hours": hours}


# ---------- builds ----------

def _builds(in_period: list[dict], entries: list[dict]) -> list[dict]:
    """Verglichen wird je 1.000 Zeichen: Die Texte sind unterschiedlich lang, die reine Gesamtzeit
    würde Builds mit kürzeren Texten bevorzugen. Vorgänger ist der letzte Build mit Anfragen davor,
    bestimmt über das ganze Log, samt seinem Wert. Sonst hätte der erste Build im Zeitraum nie
    einen Vergleich."""
    predecessor = _predecessor_per_1000(entries)
    rows = []
    for name, group in _by_build(in_period).items():
        info = group[0].get("build") if isinstance(group[0].get("build"), dict) else {}
        metrics = _metrics(_requests(group))
        per_1000 = metrics["per_1000_median_ms"]
        previous = predecessor.get(name)
        change = None
        if per_1000 is not None and previous:
            change = round((per_1000 - previous) / previous, 4)
        rows.append({
            "name": name, "number": info.get("number"), "commit": info.get("commit"),
            "dirty": bool(info.get("dirty")),
            "first": _berlin(group[0]["_t"]), "last": _berlin(group[-1]["_t"]),
            "requests": metrics["requests"], "median_ms": metrics["total_median_ms"],
            "p90_ms": metrics["total_p90_ms"], "per_1000_median_ms": per_1000,
            "change_vs_previous": change,
        })
    return rows


def _predecessor_per_1000(entries: list[dict]) -> dict[str, float | None]:
    """Je Build der Median je 1.000 Zeichen seines Vorgängers über das ganze Log, None ohne."""
    result, previous = {}, None
    for name, group in _by_build(entries).items():
        result[name] = previous
        per_1000 = _metrics(_requests(group))["per_1000_median_ms"]
        if per_1000 is not None:
            previous = per_1000
    return result


def _by_build(entries: list[dict]) -> dict[str, list[dict]]:
    """Gruppiert nach Build, in der Reihenfolge, in der die Builds zuerst auftauchen."""
    groups: dict[str, list[dict]] = {}
    for e in sorted(entries, key=lambda e: e["_t"]):
        groups.setdefault(_build_name(e.get("build")), []).append(e)
    return groups


def _build_name(info) -> str:
    if not isinstance(info, dict):
        return "unbekannt"
    number = "?" if info.get("number") is None else info["number"]
    dirty = "*" if info.get("dirty") else ""
    return f"#{number} · {info.get('commit') or '?'}{dirty}"


# ---------- calibration ----------

def _calibration(entries: list[dict]) -> dict:
    """Gleiche Texte machen Builds direkt vergleichbar; die Zeichenzahl kennzeichnet den Text."""
    runs = [e for e in entries if e.get("quelle") == "kalibrierung"]
    texts = sorted({e["zeichen"] for e in runs})
    rows = []
    for name, group in _by_build(runs).items():
        medians = [_percentile([e["gesamt_ms"] for e in group if e["zeichen"] == chars], 50)
                   for chars in texts]
        rows.append({"build": name, "runs": len(group), "median_ms": medians})
    return {"texts": texts, "rows": rows}


# ---------- errors ----------

def _errors(requests: list[dict]) -> list[dict]:
    # strip: Pipeline.analyze hängt den Hinweis zur Laya-Bestätigung mit führendem Leerzeichen an.
    groups: dict[str, list[datetime]] = {}
    for e in requests:
        if e.get("fehler"):
            groups.setdefault(str(e["fehler"]).strip(), []).append(e["_t"])
    rows = [{"text": text, "count": len(times), "last": _berlin(max(times))}
            for text, times in groups.items()]
    return sorted(rows, key=lambda row: (-row["count"], row["text"]))


# ---------- Hilfen ----------

def _between(entries: list[dict], start: datetime, end: datetime) -> list[dict]:
    return [e for e in entries if start < e["_t"] <= end]


def _requests(entries: list[dict]) -> list[dict]:
    return [e for e in entries if e.get("quelle") != "kalibrierung"]


def _distribution(values: list) -> dict:
    values = [v for v in values if _is_number(v)]
    return {"count": len(values), "median_ms": _percentile(values, 50),
            "p90_ms": _percentile(values, 90), "p99_ms": _percentile(values, 99)}


def _percentile(values: list, p: int):
    """Nearest-Rank: der kleinste Wert, unter oder auf dem mindestens p % der Werte liegen."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, -(-p * len(ordered) // 100) - 1)]


def _berlin(t: datetime) -> str:
    return t.astimezone(BERLIN).isoformat()


def _is_number(v) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)
