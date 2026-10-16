"""Orchestrierung: Gate → Erkennung → Zusammenführen → Laya-Bestätigung → Platzhalter."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, get_args

from . import build_info, classification, config
from .detectors.base import RawHit
from .detectors.credentials import detect_credentials
from .detectors.gliner import detect_gliner
from .detectors.regex_det import detect_regex
from .detectors.spacy_det import detect_spacy
from .laya_client import GateResult, LayaClient
from .merge import merge_hits
from .models import AnalyzeRequest, AnalyzeResponse, Classification, Entity, Gate, Timing
from .placeholders import anonymize, assign_placeholders, build_mapping
from .request_log import RequestLog

log = logging.getLogger(__name__)

Detector = Callable[[str], list[RawHit]]
# Feld "quelle" im Request-Log; die Konstanten ersparen den übrigen Modulen die Strings.
Source = Literal["anfrage", "kalibrierung", "lasttest"]
REQUEST, CALIBRATION, LOAD_TEST = get_args(Source)
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

    def analyze(self, req: AnalyzeRequest, source: Source = REQUEST) -> AnalyzeResponse:
        t0 = self.clock()
        timing = Timing()
        text = req.text
        # Zugangsdaten nur bei aktiver Klassifikation, also Flag an und gültige Regeldatei.
        rules, _ = classification.active_rules()
        credentials = rules is not None
        allowed = set(req.categories) if req.categories else set(classification.categories(rules))
        threshold = req.gate_threshold if req.gate_threshold is not None else config.GATE_THRESHOLD

        # 1. Gate, bei aktiver Klassifikation mit deren Fragen im selben Batch
        gate_note = None
        prob: float | None = None
        result, laya_error = None, None
        try:
            result = (self.laya.gate(text, extra=classification.questions(rules)) if rules
                      else self.laya.gate(text))
            prob = result.probability
        except Exception as exc:  # Laya nicht erreichbar: Erkennung trotzdem erlauben
            log.warning("Laya-Gate fehlgeschlagen: %s", exc)
            laya_error = exc.__class__.__name__
            gate_note = f"Laya nicht erreichbar ({exc.__class__.__name__}); Gate übersprungen."
        timing.gate_ms = self._ms(t0)
        sensitive = prob is None or prob >= threshold
        gate = Gate(probability=prob, threshold=threshold, sensitive=sensitive,
                    skipped=req.force, note=gate_note)

        entities: list[Entity] = []
        laya_rejected = 0
        # Zugangsdaten werden auch ersetzt, wenn das Gate den Text für harmlos hält: Ein Passwort
        # bleibt ein Passwort, egal wie wenig Personenbezug drumherum steht.
        cred_hits = detect_credentials(text) if credentials else []
        # Für die Warnung zählt jeder ZUGANG-Treffer, auch einer, den die Kategorienwahl ausfiltert.
        credentials_found = bool(cred_hits)
        if cred_hits and not (sensitive or req.force):
            entities = merge_hits(cred_hits, text, allowed)
        if sensitive or req.force:
            # 2. Erkennung parallel
            t1 = self.clock()
            futs = [self.pool.submit(detect, text) for detect in self.detectors]
            hits = [h for f in futs for h in f.result()]
            if credentials:
                hits = [_as_credential(h) for h in hits] + cred_hits
                credentials_found = any(h.category == config.ZUGANG for h in hits)
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
        classified = _classify_original(rules, result, laya_error, credentials_found) if rules else None
        timing.total_ms = self._ms(t0)
        res = AnalyzeResponse(
            text=text, gate=gate, entities=entities,
            anonymized_text=anonymize(text, entities),
            mapping=build_mapping(entities), timing=timing, classification=classified,
        )
        if self.request_log:
            self.request_log.write(_log_entry(req, res, source, laya_rejected))
        return res

    def apply(self, text: str, entities: list[Entity]):
        entities = assign_placeholders(entities)
        return entities, anonymize(text, entities), build_mapping(entities)

    def _ms(self, t: float) -> int:
        return int((self.clock() - t) * 1000)


def _as_credential(h: RawHit) -> RawHit:
    """GLiNER-Treffer für Passwort, Secret und API-Key zählen bei aktiver Klassifikation als ZUGANG."""
    if h.source == "gliner" and h.label in config.ZUGANG_GLINER_LABELS:
        return replace(h, category=config.ZUGANG)
    return h


def _classify_original(rules: classification.Rules, result: GateResult | None,
                       laya_error: str | None, credentials: bool) -> Classification:
    """Stufe des Originals aus dem Gate-Batch; ohne Laya-Antwort nur ein Hinweis.

    Zugangsdaten stehen im Original, wenn ein ZUGANG-Treffer gefunden wurde (`credentials`)
    oder Laya sie in einem Abschnitt sieht.
    """
    if result is None:
        return classification.summarize(
            rules, None, credentials=credentials,
            note=f"Laya nicht erreichbar ({laya_error}); keine Schutzstufe.")
    original = classification.assess(rules, result.sections)
    credentials = credentials or classification.credentials_likely(original)
    return classification.summarize(rules, original, credentials=credentials)


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
