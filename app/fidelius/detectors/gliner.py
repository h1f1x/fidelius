"""GLiNER2-PII (fastino/gliner2-privacy-filter-PII-multi), Apache 2.0."""
from __future__ import annotations

import logging
from functools import lru_cache

from .. import config
from .base import RawHit

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _model():
    from gliner2 import GLiNER2

    log.info("Lade GLiNER2-PII %s", config.GLINER_MODEL)
    return GLiNER2.from_pretrained(config.GLINER_MODEL)


def warmup() -> None:
    _model()


def detect_gliner(text: str, threshold: float | None = None) -> list[RawHit]:
    """Doppelte Treffer aus der Überlappung der Fenster fasst merge_hits zusammen."""
    model = _model()
    labels = list(config.GLINER_LABELS)
    hits: list[RawHit] = []
    for offset, end in _windows(text, config.GLINER_WINDOW_CHARS, config.GLINER_WINDOW_OVERLAP):
        result = model.extract_entities(
            text[offset:end], labels,
            threshold=threshold if threshold is not None else config.GLINER_THRESHOLD,
            include_confidence=True, include_spans=True,
        )
        entities = result.get("entities", result) if isinstance(result, dict) else result
        for label, items in entities.items():
            category = config.GLINER_LABELS.get(label)
            if not category:
                continue
            for item in items:
                start, stop, score = _span(item)
                if start is None:
                    continue
                start, stop = start + offset, stop + offset
                hits.append(RawHit(start, stop, text[start:stop], category, "gliner", label, score))
    return hits


def _windows(text: str, size: int, overlap: int) -> list[tuple[int, int]]:
    """Fenster (start, ende) über den Text, geschnitten an Leerraum, damit kein Wort zerfällt.
    Aufeinanderfolgende Fenster überlappen um etwa `overlap` Zeichen."""
    windows, start, n = [], 0, len(text)
    while True:
        end = min(start + size, n)
        if end < n:
            cut = max(text.rfind(c, start + size // 2, end) for c in " \n\t")
            end = cut if cut > start else end
        windows.append((start, end))
        if end >= n:
            return windows
        nxt = max(end - overlap, start + 1)
        spaces = [i for i in (text.find(c, nxt, end) for c in " \n\t") if i >= 0]
        start = min(spaces) + 1 if spaces else nxt


def _span(item) -> tuple[int | None, int | None, float | None]:
    """gliner2 liefert je nach Version dicts mit start/end oder (text, start, end, score)."""
    if isinstance(item, dict):
        start = item.get("start")
        end = item.get("end")
        score = item.get("confidence", item.get("score"))
        return start, end, score
    if isinstance(item, (list, tuple)) and len(item) >= 3:
        return item[1], item[2], (item[3] if len(item) > 3 else None)
    return None, None, None
