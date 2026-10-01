"""Gemeinsames Rohtreffer-Format aller Erkenner."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawHit:
    start: int
    end: int
    text: str
    category: str
    source: str   # gliner | spacy | regex
    label: str    # Originallabel des Erkenners
    score: float | None = None
