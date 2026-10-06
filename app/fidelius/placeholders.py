"""Platzhalter vergeben, Werte normalisieren, Zuordnungstabelle bauen, Text ersetzen."""
from __future__ import annotations

import re

from .models import Entity, MappingEntry

_TITLES = re.compile(
    r"^(?:(?:herrn?|frau|hr\.|fr\.|dr\.|prof\.|dipl\.-ing\.|dipl\.-kfm\.|mag\.|med\.|"
    r"rechtsanwalt|rechtsanwältin|ra|mr\.?|mrs\.?|ms\.?|dr|prof|familie|fam\.|eheleute|"
    r"kollege|kollegin|mandant|mandantin)\s+)+",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")


def normalize(text: str, category: str) -> str:
    t = _WS.sub(" ", text.strip())
    if category == "PERSON":
        t = _TITLES.sub("", t).strip().rstrip(",")
        if "," in t:  # "Wiegand, Thorsten" → "Thorsten Wiegand"
            last, _, first = t.partition(",")
            t = f"{first.strip()} {last.strip()}".strip()
    if category in {"IBAN", "TELEFON"}:
        t = re.sub(r"[\s\-/()]", "", t)
    if category == "EMAIL":
        t = t.strip("<>")
    if category == "KENNUNG":
        t = re.sub(r"\s+", "", t)
    return t.casefold()


def _person_clusters(keys: list[str]) -> dict[str, str]:
    """Varianten eines Namens auf einen Vertreter abbilden.

    - "t. wiegand" → "thorsten wiegand" (Initiale passt zum Vornamen, Nachname gleich)
    - "wiegand" → "thorsten wiegand" (Nachname allein, wenn eindeutig)
    - "annika" → "annika reuter" (Vorname allein, wenn eindeutig)
    """
    cluster: dict[str, str] = {k: k for k in keys}
    full = [k for k in keys if " " in k and not _is_initial(k.split(" ")[0])]
    # 1. Initialen-Varianten an volle Namen hängen
    for k in keys:
        parts = k.split(" ")
        if len(parts) >= 2 and _is_initial(parts[0]):
            matches = {f for f in full if f.split(" ")[-1] == parts[-1] and f[0] == parts[0][0]}
            if len(matches) == 1:
                cluster[k] = matches.pop()
    # 2. Einzelne Tokens: Nachname oder Vorname eines vollen Namens
    for k in keys:
        if " " in k:
            continue
        by_last = {f for f in full if f.split(" ")[-1] == k}
        by_first = {f for f in full if f.split(" ")[0] == k}
        matches = by_last or by_first
        if len(matches) == 1:
            cluster[k] = matches.pop()
    return cluster


def _is_initial(token: str) -> bool:
    return len(token) <= 2 and token.endswith(".") or len(token) == 1


def assign_placeholders(entities: list[Entity]) -> list[Entity]:
    """Gleicher Wert → gleicher Platzhalter, Nummerierung nach erstem Auftreten."""
    active = sorted((e for e in entities if e.status in {"accepted", "manual"}), key=lambda e: e.start)
    person_keys = sorted({normalize(e.text, "PERSON") for e in active if e.category == "PERSON"})
    clusters = _person_clusters(person_keys)

    counters: dict[str, int] = {}
    table: dict[tuple[str, str], str] = {}
    result: dict[int, str] = {}
    for e in active:
        key = normalize(e.text, e.category)
        if e.category == "PERSON":
            key = clusters.get(key, key)
        tk = (e.category, key)
        if tk not in table:
            counters[e.category] = counters.get(e.category, 0) + 1
            table[tk] = f"[{e.category}_{counters[e.category]}]"
        result[e.id] = table[tk]

    out = []
    for e in entities:
        out.append(e.model_copy(update={"placeholder": result.get(e.id)}) if e.id in result
                   else e.model_copy(update={"placeholder": None}))
    return out


def anonymize(text: str, entities: list[Entity]) -> str:
    parts, pos = [], 0
    for e in sorted((e for e in entities if e.placeholder), key=lambda e: e.start):
        if e.start < pos:
            continue
        parts.append(text[pos:e.start])
        parts.append(e.placeholder)
        pos = e.end
    parts.append(text[pos:])
    return "".join(parts)


def build_mapping(entities: list[Entity]) -> list[MappingEntry]:
    by_ph: dict[str, MappingEntry] = {}
    for e in sorted((e for e in entities if e.placeholder), key=lambda e: e.start):
        entry = by_ph.get(e.placeholder)
        if entry is None:
            entry = MappingEntry(placeholder=e.placeholder, original=e.text, category=e.category,
                                 sources=[], variants=[])
            by_ph[e.placeholder] = entry
        for s in e.sources:
            if s.name not in entry.sources:
                entry.sources.append(s.name)
        if e.laya is not None and "laya" not in entry.sources:
            entry.sources.append("laya")
        if e.text != entry.original and e.text not in entry.variants:
            entry.variants.append(e.text)
        # Längste Variante (ohne Anrede/Titel gemessen) als Hauptwert, damit die Rückübersetzung
        # "Emre Yilmaz" liefert und nicht "Herr Yilmaz".
        if len(normalize(e.text, e.category)) > len(normalize(entry.original, e.category)):
            if entry.original not in entry.variants:
                entry.variants.insert(0, entry.original)
            entry.variants = [v for v in entry.variants if v != e.text]
            entry.original = e.text
    return list(by_ph.values())


_PH_RE_CACHE: dict[str, re.Pattern] = {}


def placeholder_pattern(placeholder: str) -> re.Pattern:
    """Erkennt auch Varianten, die KI-Antworten erzeugen: PERSON_1, [Person 1], «PERSON-1», **[PERSON_1]**."""
    if placeholder not in _PH_RE_CACHE:
        core = placeholder.strip("[]")
        cat, num = core.rsplit("_", 1)
        _PH_RE_CACHE[placeholder] = re.compile(
            r"(?:[\[\(\{<«„\"']\s*)?" + re.escape(cat) + r"[\s_\-]?" + num + r"(?![0-9])(?:\s*[\]\)\}>»“\"'])?",
            re.IGNORECASE,
        )
    return _PH_RE_CACHE[placeholder]


def deanonymize(text: str, mapping: list[MappingEntry]) -> str:
    # Längere Nummern zuerst, damit PERSON_1 nicht in PERSON_12 greift.
    for entry in sorted(mapping, key=lambda m: -len(m.placeholder)):
        text = placeholder_pattern(entry.placeholder).sub(lambda _m, o=entry.original: o, text)
    return text
