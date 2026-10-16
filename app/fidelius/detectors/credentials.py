"""Zugangsdaten als Kategorie ZUGANG: Token-Formate, JWT, private Schlüssel, Schlüsselwort-Werte.

Läuft nur bei aktiver Klassifikation (docs/specs/klassifikation.md, Abschnitt 5) und unabhängig vom
Gate: Ein Passwort ist auch in einem sonst harmlosen Text zu ersetzen. Die Treffer gelten wie alle
Regex-Treffer als exakt (Quelle „regex“), Laya fragt sie nicht nach.
"""
from __future__ import annotations

from collections.abc import Iterator

import re2

from .base import RawHit
from .regex_det import bounded, char_offsets, spans

CATEGORY = "ZUGANG"

# Bekannte Präfixe der großen Anbieter. Die Mindestlängen halten Wörter wie „sk-Fahrer“ fern.
_TOKEN = bounded(
    r"(?:"
    r"sk-[A-Za-z0-9_\-]{20,}"               # OpenAI, auch sk-proj-; Anthropic sk-ant-
    r"|gh[pousr]_[A-Za-z0-9]{30,}"          # GitHub: ghp_, gho_, ghu_, ghs_, ghr_
    r"|github_pat_[A-Za-z0-9_]{22,}"
    r"|glpat-[A-Za-z0-9_\-]{20,}"           # GitLab
    r"|xox[abposr]-[A-Za-z0-9\-]{10,}"       # Slack: xoxb-, xoxp-, …
    r"|AKIA[0-9A-Z]{16}"                     # AWS Access Key ID
    r")"
)
_JWT = bounded(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")

# Der Block reicht über alle Zeilen bis zum END. Fehlt das END, weil der Schlüssel abgeschnitten
# eingefügt wurde, gilt der Rest des Texts als Schlüssel: lieber zu viel ersetzt als ein halber
# Schlüssel im Klartext. RE2 kennt keine Rückverweise, deshalb prüft das Muster nicht, ob BEGIN
# und END denselben Typ nennen; der erste END-Marker beendet den Block.
_PEM = re2.compile(
    r"(?s)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)".encode()
)

# Schlüsselwort, dann „:“ oder „=“, dann der Wert ohne Leerzeichen, wahlweise in Anführungszeichen.
# Ersetzt wird nur der Wert. Ein Präfix wie in DB_PASSWORD oder app-secret gehört zum Schlüsselwort.
_KEYWORD = bounded(
    r"(?i:(?:[a-z0-9]+[_\-])*"
    r"(?:passwort|password|passwd|pwd|kennwort|token|api[_\-]?key|client_secret|secret))"
    r"[ \t]*[:=][ \t]*[\"']?(?P<wert>[^ \t\r\n\"']+)",
    after="",
)
_VALUE_END = ".,;:)"


def detect_credentials(text: str) -> list[RawHit]:
    raw = text.encode()
    hits: list[RawHit] = []

    def add(s: int, e: int, label: str) -> None:
        hits.append(RawHit(s, e, text[s:e], CATEGORY, "regex", label, 1.0))

    for s, e in _pem_spans(text, raw):
        add(s, e, "private_key")
    for s, e in spans(_TOKEN, text, raw):
        add(s, e, "token")
    for s, e in spans(_JWT, text, raw):
        add(s, e, "jwt")
    for s, e in _keyword_values(text, raw):
        add(s, e, "keyword")
    return hits


def _pem_spans(text: str, raw: bytes) -> Iterator[tuple[int, int]]:
    to_char = char_offsets(text, raw)
    for m in _PEM.finditer(raw):
        yield to_char(m.start()), to_char(m.end())


def _keyword_values(text: str, raw: bytes) -> Iterator[tuple[int, int]]:
    group = _KEYWORD.groupindex[b"wert"]
    to_char = char_offsets(text, raw)
    pos = 0
    while (m := _KEYWORD.search(raw, pos)) is not None:
        pos = m.end()
        s, e = to_char(m.start(group)), to_char(m.end(group))
        # Satzzeichen am Ende gehören zum Satz, nicht zum Wert: „Passwort: abc123.“
        while e > s and text[e - 1] in _VALUE_END:
            e -= 1
        # Ein Wert aus reinen Buchstaben ist in Fließtext meist ein Wort („Das Passwort: bekommst
        # du per Telefon“). Erst Ziffer oder Sonderzeichen machen ihn zum Kandidaten. Ein Passwort
        # wie „geheim“ rutscht dadurch durch; Fehlalarme in jeder zweiten Mail wiegen schwerer.
        if e > s and not text[s:e].isalpha():
            yield s, e
