"""Orchestrierung: Gate → Erkennung → Zusammenführen → Laya-Bestätigung → Platzhalter."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from . import build_info, config
from .detectors.base import RawHit
from .detectors.gliner import detect_gliner
from .detectors.regex_det import detect_regex
from .detectors.spacy_det import detect_spacy
from .laya_client import LayaClient
from .merge import merge_hits
from .models import AnalyzeRequest, AnalyzeResponse, Entity, Gate, Timing
from .placeholders import anonymize, assign_placeholders, build_mapping
from .request_log import RequestLog

log = logging.getLogger(__name__)

Detector = Callable[[str], list[RawHit]]
Source = Literal["anfrage", "kalibrierung"]
DEFAULT_DETECTORS: tuple[Detector, ...] = (detect_gliner, detect_spacy, detect_regex)


class Pipeline:
    def __init__(self, laya: LayaClient | None = None,
                 detectors: Sequence[Detector] = DEFAULT_DETECTORS,
                 clock: Callable[[], float] = time.perf_counter,
                 log_path: str | Path | None = None):
        self.laya = laya or LayaClient()
        self.clock = clock
        self.request_log = RequestLog(log_path) if log_path else None
        self.detectors = tuple(detectors)
        self.pool = ThreadPoolExecutor(max_workers=max(len(self.detectors), 1))

    def analyze(self, req: AnalyzeRequest, source: Source = "anfrage") -> AnalyzeResponse:
        t0 = self.clock()
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
        timing.gate_ms = self._ms(t0)
        sensitive = prob is None or prob >= threshold
        gate = Gate(probability=prob, threshold=threshold, sensitive=sensitive,
                    skipped=req.force, note=gate_note)

        entities: list[Entity] = []
        laya_rejected = 0
        if sensitive or req.force:
            # 2. Erkennung parallel
            t1 = self.clock()
            futs = [self.pool.submit(detect, text) for detect in self.detectors]
            hits = [h for f in futs for h in f.result()]
            # 3. Zusammenführen
            entities = merge_hits(hits, text, allowed)
            timing.detect_ms = self._ms(t1)
            # 4. Laya-Bestätigung
            if req.use_laya_check and gate_note is None:
                t2 = self.clock()
                try:
                    entities = self.laya.classify(text, entities)
                    # Vor dem Kategorienfilter zählen: der setzt abgewählte Kategorien auf
                    # rejected_user, auch wenn Laya sie schon abgelehnt hatte.
                    laya_rejected = sum(e.status == "rejected_laya" for e in entities)
                except Exception as exc:
                    log.warning("Laya-Bestätigung fehlgeschlagen: %s", exc)
                    gate.note = (gate.note or "") + f" Laya-Bestätigung fehlgeschlagen ({exc.__class__.__name__})."
                timing.laya_check_ms = self._ms(t2)
            # Abgewählte Kategorien nach Umkategorisierung erneut filtern
            entities = [e if e.category in allowed else e.model_copy(update={"status": "rejected_user"})
                        for e in entities]
        # 5. Platzhalter
        entities = assign_placeholders(entities)
        timing.total_ms = self._ms(t0)
        res = AnalyzeResponse(
            text=text, gate=gate, entities=entities,
            anonymized_text=anonymize(text, entities),
            mapping=build_mapping(entities), timing=timing,
        )
        if self.request_log:
            self.request_log.write(_log_entry(req, res, source, laya_rejected))
        return res

    def apply(self, text: str, entities: list[Entity]):
        entities = assign_placeholders(entities)
        return entities, anonymize(text, entities), build_mapping(entities)

    def _ms(self, t: float) -> int:
        return int((self.clock() - t) * 1000)


def _log_entry(req: AnalyzeRequest, res: AnalyzeResponse, source: Source,
               laya_rejected: int) -> dict:
    """Nur Zahlen und Schalter: Text, Treffer und Platzhalter verlassen die Anfrage nie."""
    return {
        "zeit": datetime.now(UTC).isoformat(timespec="seconds"),
        "build": build_info.build(),
        "quelle": source,
        "zeichen": len(req.text),
        "gate_wert": res.gate.probability,
        "schwelle": res.gate.threshold,
        "sensibel": res.gate.sensitive,
        "trotzdem": req.force,
        "laya_bestaetigung": req.use_laya_check,
        "gate_ms": res.timing.gate_ms,
        "erkennung_ms": res.timing.detect_ms,
        "laya_ms": res.timing.laya_check_ms,
        "gesamt_ms": res.timing.total_ms,
        "stellen": sum(e.placeholder is not None for e in res.entities),
        "platzhalter": len(res.mapping),
        "laya_abgelehnt": laya_rejected,
        "fehler": res.gate.note,
    }
