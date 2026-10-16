"""Klassifikation nach Schutzstufen: Regeldatei der Installation lesen und prüfen, Laya-Antworten
zu einer Stufe je Abschnitt und je Text verdichten."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from . import config
from .models import ChunkLevel, Classification, Span, TextLevel

if TYPE_CHECKING:
    from .laya_client import Section

# Startwert, bis die Kalibrierbeispiele einen besseren liefern (docs/specs/klassifikation.md).
DEFAULT_THRESHOLD = 0.3


class RulesError(ValueError):
    """Regeldatei fehlt oder ist ungültig; die Meldung geht so an /api/health."""


@dataclass(frozen=True)
class Level:
    id: str
    name: str
    laya: str  # Kurzbeschreibung als choice-Kriterium für Laya
    text: str  # Markdown für die Anzeige


@dataclass(frozen=True)
class Rules:
    levels: tuple[Level, ...]  # von niedrig nach hoch
    approved_up_to: str
    threshold: float
    credentials_text: str | None

    def rank(self, level_id: str) -> int:
        return next(i for i, lv in enumerate(self.levels) if lv.id == level_id)

    def above_approval(self, level_id: str) -> bool:
        return self.rank(level_id) > self.rank(self.approved_up_to)


def load_rules(path: str) -> Rules:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise RulesError(f"Regeldatei fehlt ({path})") from None
    except OSError as exc:
        raise RulesError(f"Regeldatei nicht lesbar ({path}): {exc}") from None
    try:
        data = yaml.safe_load(raw)
        root = yaml.compose(raw, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"Zeile {mark.line + 1}: " if mark else ""
        raise RulesError(f"{where}{getattr(exc, 'problem', None) or exc}") from None
    return _parse(data, _Lines(root))


class _Lines:
    """Zeilennummern zur Regeldatei aus dem YAML-Knotenbaum, damit auch inhaltliche Fehler wie
    eine doppelte id die Stelle nennen."""

    def __init__(self, root: yaml.Node | None):
        self.root = root

    def error(self, msg: str, *path: str | int) -> RulesError:
        """Fehler an der Stelle `path` (Schlüssel und Listenindex); fehlt sie, am nächsten
        vorhandenen Knoten darüber."""
        node, line = self.root, None
        if node is not None:
            line = node.start_mark.line
        for key in path:
            if isinstance(node, yaml.MappingNode):
                pair = next(((k, v) for k, v in node.value if k.value == key), None)
                if pair is None:
                    break
                line, node = pair[0].start_mark.line, pair[1]
            elif isinstance(node, yaml.SequenceNode) and isinstance(key, int) and key < len(node.value):
                node = node.value[key]
                line = node.start_mark.line
            else:
                break
        return RulesError(msg if line is None else f"Zeile {line + 1}: {msg}")


def _parse(data: object, lines: _Lines) -> Rules:
    if not isinstance(data, dict):
        raise lines.error("Die Regeldatei muss eine Zuordnung mit stufen und freigegeben_bis sein")
    raw_levels = data.get("stufen")
    if not isinstance(raw_levels, list) or len(raw_levels) < 2:
        raise lines.error("stufen braucht mindestens zwei Einträge", "stufen")
    levels: list[Level] = []
    for n, item in enumerate(raw_levels, 1):
        if not isinstance(item, dict):
            raise lines.error(f"Stufe {n} ist keine Zuordnung", "stufen", n - 1)
        missing = [k for k in ("id", "name", "laya", "text") if not str(item.get(k) or "").strip()]
        if missing:
            raise lines.error(f"Stufe {n} ({item.get('id', '?')}): es fehlt {', '.join(missing)}",
                              "stufen", n - 1)
        lv = Level(*(str(item[k]).strip() for k in ("id", "name", "laya", "text")))
        if any(o.id == lv.id for o in levels):
            raise lines.error(f"Stufe {n}: id {lv.id} ist doppelt", "stufen", n - 1, "id")
        levels.append(lv)
    approved = str(data.get("freigegeben_bis") or "")
    if approved not in {lv.id for lv in levels}:
        raise lines.error(f"freigegeben_bis: {approved or '(leer)'} ist keine id aus stufen",
                          "freigegeben_bis")
    threshold = data.get("schwelle", DEFAULT_THRESHOLD)
    if not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
        raise lines.error(f"schwelle muss zwischen 0 und 1 liegen, nicht {threshold}", "schwelle")
    creds = data.get("zugangsdaten") or {}
    creds_text = str(creds.get("text") or "").strip() if isinstance(creds, dict) else ""
    return Rules(tuple(levels), approved, float(threshold), creds_text or None)


def active_rules() -> tuple[Rules | None, str]:
    """Die Regeln, falls Flag an und Datei gültig, dazu der Status für /api/health.

    Liest die Datei bei jedem Aufruf, damit eine Änderung ohne Neustart wirkt.
    """
    if not config.CLASSIFICATION_ENABLED:
        return None, "aus"
    try:
        rules = load_rules(config.CLASSIFICATION_FILE)
    except RulesError as exc:
        return None, f"Fehler: {exc}"
    return rules, f"aktiv: {len(rules.levels)} Stufen"


def categories(rules: Rules | None) -> dict[str, dict[str, str]]:
    """Die Kategorien für Erkennung und UI: mit aktiven Regeln um ZUGANG ergänzt."""
    if rules is None:
        return config.CATEGORIES
    return {**config.CATEGORIES, config.ZUGANG: config.ZUGANG_CATEGORY}


# ---- Laya-Fragen und Auswertung ---------------------------------------------------------

LEVEL_QUESTION = "stufe"
LEVEL_INSTRUCTIONS = "Welcher Schutzstufe gehört dieser Text an?"
CREDENTIALS_QUESTION = "zugang"
CREDENTIALS_INSTRUCTIONS = ("Enthält dieser Text ein Passwort, einen Token, einen API-Key, "
                            "einen privaten Schlüssel oder andere Zugangsdaten?")


def questions(rules: Rules) -> dict[str, dict]:
    """Die Laya-Fragen der Klassifikation im Format des Batch-Endpunkts.

    Sie laufen für das Original als `extra` im Gate-Batch mit. Die Kriterien sind die
    `laya`-Kurzfassungen unter der Stufen-id, so kommen die Wahrscheinlichkeiten je id zurück.
    """
    return {
        LEVEL_QUESTION: {
            "type": "choice",
            "instructions": LEVEL_INSTRUCTIONS,
            "criteria": {lv.id: lv.laya for lv in rules.levels},
        },
        CREDENTIALS_QUESTION: {"type": "noul", "instructions": CREDENTIALS_INSTRUCTIONS},
    }


def assess(rules: Rules, sections: Sequence[Section]) -> TextLevel:
    """Stufe des Texts aus den Laya-Antworten je Abschnitt.

    Je Abschnitt gilt die höchste Stufe mit einer Wahrscheinlichkeit ab `rules.threshold`,
    sonst die wahrscheinlichste. Für den Text gilt die höchste Stufe über alle Abschnitte;
    `chunk` ist der Abschnitt, der sie am deutlichsten trägt.
    """
    chunks = [_chunk_level(rules, s) for s in sections]
    top = max(chunks, key=lambda c: (rules.rank(c.level), c.probabilities.get(c.level, 0.0)))
    return TextLevel(level=top.level, chunk=Span(start=top.start, end=top.end), chunks=chunks)


def _chunk_level(rules: Rules, section: Section) -> ChunkLevel:
    raw = section.answers[LEVEL_QUESTION]["probabilities"]
    probs = {lv.id: float(raw.get(lv.id, 0.0)) for lv in rules.levels}
    above = [lv.id for lv in rules.levels if probs[lv.id] >= rules.threshold]
    level = above[-1] if above else max(probs, key=probs.get)
    creds = section.answers.get(CREDENTIALS_QUESTION)
    return ChunkLevel(start=section.start, end=section.end, level=level, probabilities=probs,
                      credentials=float(creds["noul"]) if creds else None)


def credentials_likely(level: TextLevel) -> bool:
    """Ob Laya in einem Abschnitt Zugangsdaten sieht, also `zugang` ab `ZUGANG_THRESHOLD`."""
    return any(c.credentials is not None and c.credentials >= config.ZUGANG_THRESHOLD
               for c in level.chunks)


def summarize(rules: Rules, original: TextLevel | None, anonymized: TextLevel | None = None,
              credentials: bool = False, note: str | None = None) -> Classification:
    """Gesamtbild für die Antwort: gewarnt wird über der Freigabe oder bei Zugangsdaten."""
    levels = [t.level for t in (original, anonymized) if t is not None]
    warn = credentials or any(rules.above_approval(lv) for lv in levels)
    return Classification(original=original, anonymized=anonymized, credentials=credentials,
                          warn=warn, note=note)
