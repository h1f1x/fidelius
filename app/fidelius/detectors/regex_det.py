"""Regex-Erkenner für deterministische Muster: E-Mail, Telefon, IBAN, Datum, Straße, Kennungen."""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Iterator

import re2

from .base import RawHit

# Alle Muster laufen auf RE2: kein Backtracking, lineare Laufzeit, also kann kein präparierter
# Text die Erkennung zum Hängen bringen. Zwei Unterschiede zu Pythons re gleicht dieser Abschnitt
# aus, damit die Treffer dieselben bleiben wie vor der Umstellung.
#
# 1. RE2 liest \d, \D, \s und \w nur als ASCII, Pythons re las sie nach Unicode. Ohne Ausgleich
#    rutschten „03. 05. 2026“ mit geschütztem Leerzeichen oder vollbreite Ziffern durch. _unicode
#    ersetzt die Kürzel durch Klassen, die genau Pythons Mengen abdecken; in Zeichenklassen stehen
#    sie ausgeschrieben (_SPACE_CHARS, _WORD_CHARS).
_SPACE_CHARS = r"\t-\r\x1c-\x20\x85\pZ"
_WORD_CHARS = r"\pL\pN_"


def _unicode(pattern: str) -> str:
    return (
        pattern.replace(r"\d", r"\p{Nd}")
        .replace(r"\D", r"\P{Nd}")
        .replace(r"\s", f"[{_SPACE_CHARS}]")
    )


def _not_word(also: str = "") -> str:
    return f"[^{_WORD_CHARS}{also}]"


# 2. RE2 kennt keine Lookarounds, und sein \b ist ebenfalls ASCII. Ein Rand wird deshalb als
#    Zeichen mitgematcht: davor Textanfang oder ein Nicht-Wortzeichen, dahinter Textende oder ein
#    Nicht-Wortzeichen. Der eigentliche Treffer liegt in der Gruppe „treffer“, _spans liest ihn aus.
_BEFORE_WORD = "(?:^|" + _not_word() + ")"
_AFTER_WORD = "(?:$|" + _not_word() + ")"


def _bounded(body: str, before: str = _BEFORE_WORD, after: str = _AFTER_WORD):
    # Kompiliert für Bytes, damit detect_regex den Text nur einmal kodiert (siehe _spans).
    return re2.compile(_unicode(before + "(?P<treffer>" + body + ")" + after).encode())


def _char_offsets(text: str, raw: bytes) -> Callable[[int], int]:
    """Rechnet Byte-Offsets in raw in Zeichen-Offsets in text um; aufsteigend in linearer Zeit."""
    if len(raw) == len(text):
        return lambda b: b
    last_b = last_c = 0

    def convert(b: int) -> int:
        nonlocal last_b, last_c
        if b < last_b:
            last_b = last_c = 0
        last_c += len(raw[last_b:b].decode())
        last_b = b
        return last_c

    return convert


def _spans(pattern, text: str, raw: bytes) -> Iterator[tuple[int, int]]:
    """Spannen der Gruppe „treffer“ in Zeichen-Offsets, in der Reihenfolge von Pythons finditer.

    Der Rand hinter einem Treffer kann der Rand vor dem nächsten sein („030 1234567,040 7654321“).
    finditer würde ihn verbrauchen, darum geht die Suche hinter dem Treffer weiter. Sie läuft auf
    den einmal kodierten Bytes: Mit str kodiert die RE2-Bibliothek bei jedem search() den ganzen
    Text neu, und viele Treffer machten die Laufzeit quadratisch.
    """
    group = pattern.groupindex[b"treffer"]
    to_char = _char_offsets(text, raw)
    pos = 0
    while (m := pattern.search(raw, pos)) is not None:
        s, e = m.span(group)
        yield to_char(s), to_char(e)
        pos = e


_EMAIL = re2.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Deutsche Telefonformate: +49 30 1234567, 0049 30 123 45 67, 030/1234567, (030) 12 34 56,
# 0171-1234567. Davor kein Wortzeichen und kein Punkt, dahinter kein Wortzeichen und kein Punkt
# mit Ziffer; sonst läse sich das Datum „12.10.2026“ als Nummer.
_PHONE_SEP = f"[{_SPACE_CHARS}\\-/]"
_PHONE = _bounded(
    r"(?:\+49|0049|\(0\)|0)" + _PHONE_SEP + r"?\(?\d{2,5}\)?" + _PHONE_SEP + r"?\d{2,}"
    r"(?:" + _PHONE_SEP + r"?\d{1,})*",
    before="(?:^|" + _not_word(".") + ")",
    after="(?:$|" + _not_word(".") + r"|\.(?:$|\D))",
)

_IBAN = _bounded(r"[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?")

_MONTHS = (
    "Januar|Februar|März|Maerz|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|"
    "Jan\\.|Feb\\.|Mär\\.|Apr\\.|Jun\\.|Jul\\.|Aug\\.|Sep\\.|Sept\\.|Okt\\.|Nov\\.|Dez\\."
)
_DATE = _bounded(
    r"(?:"
    r"\d{1,2}\.\s?\d{1,2}\.\s?(?:\d{4}|\d{2})"            # 03.05.2026, 3.5.26
    r"|\d{1,2}\.\s?(?:" + _MONTHS + r")\s?\d{4}"            # 3. Mai 2026
    r"|\d{4}-\d{2}-\d{2}"                                   # 2026-05-03
    r"|\d{1,2}/\d{1,2}/\d{4}"                               # 05/03/2026
    r")"
)

# Endet auf Hausnummer, optional mit Buchstabe: „Musterstraße 12a“, „Weg 3 b“. Den Fall, dass
# ein Leerzeichen dahinter zum Treffer gehört, ergänzt _street_end.
_STREET = _bounded(
    r"[A-ZÄÖÜ][" + _WORD_CHARS + r".\-]*(?:[ -][A-ZÄÖÜ][" + _WORD_CHARS + r".\-]*)*"
    r"(?:straße|strasse|str\.|Straße|Strasse|Str\.|weg|Weg|allee|Allee|platz|Platz|gasse|Gasse|"
    r"ring|Ring|damm|Damm|ufer|Ufer|chaussee|Chaussee)\s+\d+(?:\s?[a-zA-Z])?"
)

# Kennungen hinter Schlüsselwörtern: "Versicherungsschein-Nr.: KV-2024-00123", "Kundennummer 4711-88"
_ID_KEYWORD = re2.compile(_unicode(
    r"(?:Versicherungsschein|Versicherungs|Vertrags|Kunden|Schaden|Schadens|Policen|Police|"
    r"Mitglieds|Personal|Rechnungs|Akten|Vorgangs|Auftrags|Angebots|Steuer|Sozialversicherungs|"
    r"Betriebs|Bestell|Lieferanten|Objekt|Fall|Mandanten|Partner|Makler|Agentur|Vermittler|"
    r"Rentenversicherungs|Konto|Fahrgestell|Kennzeichen|Ticket|Referenz)"
    r"[" + _SPACE_CHARS + r"\-]?(?:Nummer|nummer|Nr\.?|nr\.?|ID|Id|Kennung|kennung|zeichen|Zeichen)?"
    r"\s*[:#]?\s*"
    r"(?P<id>[A-Z]{0,4}[\-/ ]?\d[A-Z0-9\-/]*(?: [A-Z0-9][A-Z0-9\-/]*){0,5})"
))
# Alleinstehende Kennungen mit Buchstabenpräfix: VS-2024-001234, KD/889911, SN2026-0042
_ID_PREFIXED = _bounded(r"[A-Z]{2,4}[\-/]?\d{2,}(?:[\-/][A-Z0-9]{2,}){0,4}")
# Deutsche Steuer-ID (11 Ziffern) und Sozialversicherungsnummer (12 345678 A 123)
_TAX_ID = _bounded(r"\d{2}\s?\d{3}\s?\d{3}\s?\d{3}")
_SVNR = _bounded(r"\d{2}\s?\d{6}\s?[A-Z]\s?\d{3}")
# Kfz-Kennzeichen: B-AB 1234, M-XY 12, HH-AB 123E
_PLATE = _bounded(r"[A-ZÄÖÜ]{1,3}-[A-Z]{1,2}\s?\d{1,4}[EH]?")


def _iban_valid(s: str) -> bool:
    s = s.replace(" ", "").upper()
    if not 15 <= len(s) <= 34:
        return False
    rearranged = s[4:] + s[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def _phone_valid(s: str) -> bool:
    # isdecimal zählt genau, was \d in Pythons re zählt (Unicode-Kategorie Nd), also auch
    # vollbreite Ziffern; isdigit nähme zusätzlich hochgestellte wie „²“ mit.
    digits = sum(ch.isdecimal() for ch in s)
    return 7 <= digits <= 15


def _street_end(text: str, e: int) -> int:
    r"""Ergänzt den Zweig von „\s?[a-zA-Z]?\b“, den RE2 nicht ausdrücken kann.

    Pythons \b ließ den Treffer auf dem Leerzeichen hinter der Hausnummer enden, wenn danach ein
    Wortzeichen kommt: „Musterstraße 12 Berlin“ ergab „Musterstraße 12 “. Welcher Rand gilt, hängt
    davon ab, ob der Treffer auf Ziffer oder Leerzeichen endet; ohne Lookahead geht das nur hier.
    isspace, isalnum und isdecimal decken dieselben Zeichen ab wie \s, \w und \d in Pythons re.
    """
    if (
        e + 1 < len(text)
        and text[e - 1].isdecimal()
        and text[e].isspace()
        and (text[e + 1].isalnum() or text[e + 1] == "_")
    ):
        return e + 1
    return e


def _merged(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def detect_regex(text: str) -> list[RawHit]:
    hits: list[RawHit] = []
    raw = text.encode()

    def add(m_start: int, m_end: int, category: str, label: str) -> None:
        hits.append(RawHit(m_start, m_end, text[m_start:m_end], category, "regex", label, 1.0))

    for m in _EMAIL.finditer(text):
        add(m.start(), m.end(), "EMAIL", "email")
    for s, e in _spans(_IBAN, text, raw):
        if _iban_valid(text[s:e]):
            add(s, e, "IBAN", "iban")
    for s, e in _spans(_DATE, text, raw):
        add(s, e, "DATUM", "date")
    for s, e in _spans(_STREET, text, raw):
        add(s, _street_end(text, e), "ADRESSE", "street")
    id_group = _ID_KEYWORD.groupindex["id"]  # RE2-Treffer kennen Gruppen nur per Nummer.
    for m in _ID_KEYWORD.finditer(text):
        s, e = m.span(id_group)
        while e > s and text[e - 1] in "-/ .":
            e -= 1
        if e - s >= 4 and any(ch.isdigit() for ch in text[s:e]):
            add(s, e, "KENNUNG", "id_keyword")
    for s, e in _spans(_ID_PREFIXED, text, raw):
        add(s, e, "KENNUNG", "id_prefixed")
    for s, e in _spans(_TAX_ID, text, raw):
        add(s, e, "KENNUNG", "tax_id")
    for s, e in _spans(_SVNR, text, raw):
        add(s, e, "KENNUNG", "svnr")
    for s, e in _spans(_PLATE, text, raw):
        add(s, e, "KENNUNG", "plate")
    # Telefon zuletzt, damit Daten/IBAN/Kennungen, die wie Nummern aussehen, Vorrang haben. Die
    # belegten Bereiche liegen zusammengefasst und sortiert vor, damit jeder Kandidat per Binärsuche
    # statt gegen alle Treffer geprüft wird.
    taken = _merged([(h.start, h.end) for h in hits])
    taken_ends = [te for _, te in taken]
    for s, e in _spans(_PHONE, text, raw):
        if not _phone_valid(text[s:e]):
            continue
        i = bisect_right(taken_ends, s)  # erster belegter Bereich, der hinter s endet
        if i < len(taken) and taken[i][0] < e:
            continue
        add(s, e, "TELEFON", "phone")
    return hits
