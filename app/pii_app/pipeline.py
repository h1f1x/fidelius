"""Orchestrierung: Gate → Erkennung → Zusammenführen → Laya-Bestätigung → Platzhalter."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from . import config
from .detectors.gliner import detect_gliner
from .detectors.regex_det import detect_regex
from .detectors.spacy_det import detect_spacy
from .laya_client import LayaClient
from .merge import merge_hits
from .models import AnalyzeRequest, AnalyzeResponse, Entity, Gate, Timing
from .placeholders import anonymize, assign_placeholders, build_mapping

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, laya: LayaClient | None = None):
        self.laya = laya or LayaClient()
        self.pool = ThreadPoolExecutor(max_workers=3)

    def analyze(self, req: AnalyzeRequest) -> AnalyzeResponse:
        t0 = time.perf_counter()
        timing = Timing()
        text = req.text
        allowed = set(req.categories) if req.categories else set(config.CATEGORIES)
        threshold = req.gate_threshold if req.gate_threshold is not None else config.GATE_THRESHOLD

        # 1. Gate
        gate_note = None
        prob: float | None = None
        try:
            prob = self.laya.gate(text)
        except Exception as exc:  # Laya nicht erreichbar: Erkennung trotzdem erlauben
            log.warning("Laya-Gate fehlgeschlagen: %s", exc)
            gate_note = f"Laya nicht erreichbar ({exc.__class__.__name__}); Gate übersprungen."
        timing.gate_ms = _ms(t0)
        sensitive = prob is None or prob >= threshold
        gate = Gate(probability=prob, threshold=threshold, sensitive=sensitive,
                    skipped=req.force, note=gate_note)

        entities: list[Entity] = []
        if sensitive or req.force:
            # 2. Erkennung parallel
            t1 = time.perf_counter()
            futs = [self.pool.submit(detect_gliner, text),
                    self.pool.submit(detect_spacy, text),
                    self.pool.submit(detect_regex, text)]
            hits = [h for f in futs for h in f.result()]
            # 3. Zusammenführen
            entities = merge_hits(hits, text, allowed)
            timing.detect_ms = _ms(t1)
            # 4. Laya-Bestätigung
            if req.use_laya_check and gate_note is None:
                t2 = time.perf_counter()
                try:
                    entities = self.laya.classify(text, entities)
                except Exception as exc:
                    log.warning("Laya-Bestätigung fehlgeschlagen: %s", exc)
                    gate.note = (gate.note or "") + f" Laya-Bestätigung fehlgeschlagen ({exc.__class__.__name__})."
                timing.laya_check_ms = _ms(t2)
            # Abgewählte Kategorien nach Umkategorisierung erneut filtern
            entities = [e if e.category in allowed else e.model_copy(update={"status": "rejected_user"})
                        for e in entities]
        # 5. Platzhalter
        entities = assign_placeholders(entities)
        timing.total_ms = _ms(t0)
        return AnalyzeResponse(
            text=text, gate=gate, entities=entities,
            anonymized_text=anonymize(text, entities),
            mapping=build_mapping(entities), timing=timing,
        )

    def apply(self, text: str, entities: list[Entity]):
        entities = assign_placeholders(entities)
        return entities, anonymize(text, entities), build_mapping(entities)


def _ms(t: float) -> int:
    return int((time.perf_counter() - t) * 1000)
