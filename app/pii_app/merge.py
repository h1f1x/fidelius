"""Rohtreffer aller Erkenner zusammenführen: Überlappungen auflösen, Quellen sammeln."""
from __future__ import annotations

import re

from . import config
from .detectors.base import RawHit
from .models import Entity, Source


def merge_hits(hits: list[RawHit], text: str, allowed: set[str] | None = None) -> list[Entity]:
    hits = [_cut_at_newline(h) for h in hits]
    hits = [h for h in hits if h.end > h.start and (allowed is None or h.category in allowed)]
    hits = [h for h in hits if not (h.category == "DATUM" and h.text.strip().casefold() in config.DATE_STOPWORDS)]
    hits.sort(key=lambda h: (h.start, -(h.end - h.start)))
    groups: list[list[RawHit]] = []
    for h in hits:
        if groups and h.start < max(g.end for g in groups[-1]):
            groups[-1].append(h)
        else:
            groups.append([h])

    entities: list[Entity] = []
    for idx, group in enumerate(groups, start=1):
        # Regex-Spans sind exakt (IBAN, Datum, Kennung) und gewinnen gegen Modell-Spans, die
        # darüber hinauslaufen. Sonst: längster Span, bei Gleichstand die Quelle mit Priorität.
        regex_hits = [h for h in group if h.source == "regex"]
        best = min(regex_hits or group,
                   key=lambda h: (-(h.end - h.start), config.SOURCE_PRIORITY[h.source]))
        start, end = best.start, best.end
        # Kategorie: Priorität Regex > GLiNER > spaCy, aber nur unter Treffern, die den
        # gewählten Span (fast) vollständig abdecken, damit ein kleiner Teiltreffer nicht
        # die Kategorie des großen bestimmt.
        covering = [h for h in group if _coverage(h, start, end) >= 0.6]
        cat_src = min(covering or [best], key=lambda h: (config.SOURCE_PRIORITY[h.source], -(h.score or 0)))
        sources: dict[tuple[str, str], Source] = {}
        for h in group:
            key = (h.source, h.label)
            if key not in sources or (h.score or 0) > (sources[key].score or 0):
                sources[key] = Source(name=h.source, label=h.label, score=h.score)
        ordered = sorted(sources.values(), key=lambda s: config.SOURCE_PRIORITY[s.name])
        entities.append(Entity(
            id=idx, start=start, end=end, text=text[start:end],
            category=cat_src.category, sources=ordered,
        ))
    return [e for e in _trim(entities, text) if _plausible(e)]


def _plausible(e: Entity) -> bool:
    """Zwei-Buchstaben-Treffer wie "Re" oder "EG" aus den Modellen verwerfen."""
    if any(s.name == "regex" for s in e.sources):
        return True
    return len(e.text) >= 3


_CELL_BREAK = re.compile(r"\n|\t|\||\s{2,}")


def _cut_at_newline(h: RawHit) -> RawHit:
    """Kein Treffer über Zeilenumbruch, Tab, Tabellenstrich oder Mehrfach-Leerzeichen hinweg:
    spaCy klebt sonst Signatur und Anrede oder Tabellenzellen zusammen."""
    m = _CELL_BREAK.search(h.text)
    if not m:
        return h
    return RawHit(h.start, h.start + m.start(), h.text[:m.start()], h.category, h.source, h.label, h.score)


def _coverage(h: RawHit, start: int, end: int) -> float:
    inter = max(0, min(h.end, end) - max(h.start, start))
    return inter / max(1, end - start)


def _trim(entities: list[Entity], text: str) -> list[Entity]:
    """Führende/abschließende Leerzeichen und Satzzeichen aus den Spans entfernen."""
    out = []
    for e in entities:
        s, t = e.start, e.end
        while s < t and text[s] in " \t\n\r,;:.!?\"'()[]<>":
            s += 1
        while t > s and text[t - 1] in " \t\n\r,;:!?\"'()[]<>":
            t -= 1
        if t > s:
            out.append(e.model_copy(update={"start": s, "end": t, "text": text[s:t]}))
    return out
