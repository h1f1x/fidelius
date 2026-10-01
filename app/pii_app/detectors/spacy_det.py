"""spaCy de_core_news_lg: klassische NER für PER, LOC, ORG."""
from __future__ import annotations

import logging
from functools import lru_cache

from .. import config
from .base import RawHit

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _nlp():
    import spacy

    log.info("Lade spaCy %s", config.SPACY_MODEL)
    return spacy.load(config.SPACY_MODEL, disable=["parser", "lemmatizer", "morphologizer", "attribute_ruler"])


def warmup() -> None:
    _nlp()


def detect_spacy(text: str) -> list[RawHit]:
    doc = _nlp()(text)
    hits: list[RawHit] = []
    for ent in doc.ents:
        category = config.SPACY_LABELS.get(ent.label_)
        if not category:
            continue
        hits.append(RawHit(ent.start_char, ent.end_char, ent.text, category, "spacy", ent.label_, None))
    return hits
