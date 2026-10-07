"""Regex-Erkenner für deterministische Muster: E-Mail, Telefon, IBAN, Datum, Straße, Kennungen."""
from __future__ import annotations

import re2

from .base import RawHit

# Alle Muster laufen auf RE2: kein Backtracking, lineare Laufzeit, also kann kein präparierter
# Text die Erkennung zum Hängen bringen. RE2 kennt keine Lookarounds; Ränder werden deshalb als
# Zeichenklassen mitgematcht, und der eigentliche Treffer liegt in Gruppe 1.
_EMAIL = re2.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Deutsche Telefonformate: +49 30 1234567, 0049 30 123 45 67, 030/1234567, (030) 12 34 56, 0171-1234567
# Vor der Nummer steht kein Wortzeichen und kein Punkt, dahinter kein Wortzeichen und kein Punkt
# mit Ziffer; sonst läse sich das Datum „12.10.2026“ als Nummer. \pZ deckt geschützte Leerzeichen
# ab, die RE2s ASCII-\s nicht kennt.
_PHONE_SEP = r"[\s\pZ\-/]"
_PHONE = re2.compile(
    r"(?:^|[^\pL\pN_.])"
    r"((?:\+49|0049|\(0\)|0)" + _PHONE_SEP + r"?\(?\d{2,5}\)?" + _PHONE_SEP + r"?\d{2,}"
    r"(?:" + _PHONE_SEP + r"?\d+)*)"
    r"(?:$|[^\pL\pN_.]|\.(?:$|\D))"
)

_IBAN = re2.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")

_MONTHS = (
    "Januar|Februar|März|Maerz|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|"
    "Jan\\.|Feb\\.|Mär\\.|Apr\\.|Jun\\.|Jul\\.|Aug\\.|Sep\\.|Sept\\.|Okt\\.|Nov\\.|Dez\\."
)
_DATE = re2.compile(
    r"\b(?:"
    r"\d{1,2}\.\s?\d{1,2}\.\s?(?:\d{4}|\d{2})"            # 03.05.2026, 3.5.26
    r"|\d{1,2}\.\s?(?:" + _MONTHS + r")\s?\d{4}"            # 3. Mai 2026
    r"|\d{4}-\d{2}-\d{2}"                                   # 2026-05-03
    r"|\d{1,2}/\d{1,2}/\d{4}"                               # 05/03/2026
    r")\b"
)

# RE2 kennt \w und \b nur für ASCII. Vor „Überseering“ sähe \b also keine Wortgrenze, und
# „Cézanne“ zerfiele. Darum steht [\pL\pN_] für ein Wortzeichen, und der Wortanfang wird als
# vorangehendes Nicht-Wortzeichen geprüft; der Treffer selbst liegt dann in Gruppe 1.
_WORD_START = r"(?:^|[^\pL\pN_])"

_STREET = re2.compile(
    _WORD_START + r"([A-ZÄÖÜ][\pL\pN_.\-]*(?:[ -][A-ZÄÖÜ][\pL\pN_.\-]*)*"
    r"(?:straße|strasse|str\.|Straße|Strasse|Str\.|weg|Weg|allee|Allee|platz|Platz|gasse|Gasse|"
    r"ring|Ring|damm|Damm|ufer|Ufer|chaussee|Chaussee)\s+\d+\s?[a-zA-Z]?\b)"
)

# Kennungen hinter Schlüsselwörtern: "Versicherungsschein-Nr.: KV-2024-00123", "Kundennummer 4711-88"
_ID_KEYWORD = re2.compile(
    r"(?:Versicherungsschein|Versicherungs|Vertrags|Kunden|Schaden|Schadens|Policen|Police|"
    r"Mitglieds|Personal|Rechnungs|Akten|Vorgangs|Auftrags|Angebots|Steuer|Sozialversicherungs|"
    r"Betriebs|Bestell|Lieferanten|Objekt|Fall|Mandanten|Partner|Makler|Agentur|Vermittler|"
    r"Rentenversicherungs|Konto|Fahrgestell|Kennzeichen|Ticket|Referenz)"
    r"[\s\-]?(?:Nummer|nummer|Nr\.?|nr\.?|ID|Id|Kennung|kennung|zeichen|Zeichen)?\s*[:#]?\s*"
    r"(?P<id>[A-Z]{0,4}[\-/ ]?\d[A-Z0-9\-/]*(?: [A-Z0-9][A-Z0-9\-/]*){0,5})"
)
# Alleinstehende Kennungen mit Buchstabenpräfix: VS-2024-001234, KD/889911, SN2026-0042
_ID_PREFIXED = re2.compile(r"\b[A-Z]{2,4}[\-/]?\d{2,}(?:[\-/][A-Z0-9]{2,}){0,4}\b")
# Deutsche Steuer-ID (11 Ziffern) und Sozialversicherungsnummer (12 345678 A 123)
_TAX_ID = re2.compile(r"\b\d{2}\s?\d{3}\s?\d{3}\s?\d{3}\b")
_SVNR = re2.compile(r"\b\d{2}\s?\d{6}\s?[A-Z]\s?\d{3}\b")
# Kfz-Kennzeichen: B-AB 1234, M-XY 12, HH-AB 123E
_PLATE = re2.compile(_WORD_START + r"([A-ZÄÖÜ]{1,3}-[A-Z]{1,2}\s?\d{1,4}[EH]?\b)")


def _iban_valid(s: str) -> bool:
    s = s.replace(" ", "").upper()
    if not 15 <= len(s) <= 34:
        return False
    rearranged = s[4:] + s[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def _phone_valid(s: str) -> bool:
    digits = sum(ch.isdecimal() for ch in s)
    return 7 <= digits <= 15


def detect_regex(text: str) -> list[RawHit]:
    hits: list[RawHit] = []

    def add(m_start: int, m_end: int, category: str, label: str) -> None:
        hits.append(RawHit(m_start, m_end, text[m_start:m_end], category, "regex", label, 1.0))

    for m in _EMAIL.finditer(text):
        add(m.start(), m.end(), "EMAIL", "email")
    for m in _IBAN.finditer(text):
        if _iban_valid(m.group()):
            add(m.start(), m.end(), "IBAN", "iban")
    for m in _DATE.finditer(text):
        add(m.start(), m.end(), "DATUM", "date")
    for m in _STREET.finditer(text):
        add(m.start(1), m.end(1), "ADRESSE", "street")
    for m in _ID_KEYWORD.finditer(text):
        # RE2-Treffer kennen Gruppen nur per Nummer, nicht per Name.
        s, e = m.span(_ID_KEYWORD.groupindex["id"])
        while e > s and text[e - 1] in "-/ .":
            e -= 1
        if e - s >= 4 and any(ch.isdigit() for ch in text[s:e]):
            add(s, e, "KENNUNG", "id_keyword")
    for m in _ID_PREFIXED.finditer(text):
        add(m.start(), m.end(), "KENNUNG", "id_prefixed")
    for m in _TAX_ID.finditer(text):
        add(m.start(), m.end(), "KENNUNG", "tax_id")
    for m in _SVNR.finditer(text):
        add(m.start(), m.end(), "KENNUNG", "svnr")
    for m in _PLATE.finditer(text):
        add(m.start(1), m.end(1), "KENNUNG", "plate")
    # Telefon zuletzt, damit Daten/IBAN/Kennungen, die wie Nummern aussehen, Vorrang haben.
    taken = [(h.start, h.end) for h in hits]
    # Der Rand hinter einer Nummer kann der Rand vor der nächsten sein („030 1234567,040 7654321“).
    # finditer würde ihn verbrauchen, darum geht die Suche hinter Gruppe 1 weiter.
    pos = 0
    while (m := _PHONE.search(text, pos)) is not None:
        s, e = m.span(1)
        pos = e
        if not _phone_valid(text[s:e]):
            continue
        if any(s < te and ts < e for ts, te in taken):
            continue
        add(s, e, "TELEFON", "phone")
    return hits
