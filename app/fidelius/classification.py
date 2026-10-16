"""Klassifikation nach Schutzstufen: Regeldatei der Installation lesen und prüfen."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from . import config

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
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"Zeile {mark.line + 1}: " if mark else ""
        raise RulesError(f"{where}{getattr(exc, 'problem', None) or exc}") from None
    return _parse(data)


def _parse(data: object) -> Rules:
    if not isinstance(data, dict):
        raise RulesError("Die Regeldatei muss eine Zuordnung mit stufen und freigegeben_bis sein")
    raw_levels = data.get("stufen")
    if not isinstance(raw_levels, list) or len(raw_levels) < 2:
        raise RulesError("stufen braucht mindestens zwei Einträge")
    levels: list[Level] = []
    for n, item in enumerate(raw_levels, 1):
        if not isinstance(item, dict):
            raise RulesError(f"Stufe {n} ist keine Zuordnung")
        missing = [k for k in ("id", "name", "laya", "text") if not str(item.get(k) or "").strip()]
        if missing:
            raise RulesError(f"Stufe {n} ({item.get('id', '?')}): es fehlt {', '.join(missing)}")
        lv = Level(*(str(item[k]).strip() for k in ("id", "name", "laya", "text")))
        if any(o.id == lv.id for o in levels):
            raise RulesError(f"Stufe {n}: id {lv.id} ist doppelt")
        levels.append(lv)
    approved = str(data.get("freigegeben_bis") or "")
    if approved not in {lv.id for lv in levels}:
        raise RulesError(f"freigegeben_bis: {approved or '(leer)'} ist keine id aus stufen")
    threshold = data.get("schwelle", DEFAULT_THRESHOLD)
    if not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
        raise RulesError(f"schwelle muss zwischen 0 und 1 liegen, nicht {threshold}")
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
