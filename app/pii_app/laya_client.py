"""HTTP-Client für den Laya-Server: Gesamtbewertung (noul) und Treffer-Bestätigung (choice)."""
from __future__ import annotations

import logging
import re

import httpx

from . import config
from .models import Entity, LayaVerdict

log = logging.getLogger(__name__)
_SENT_SPLIT = re.compile(r"(?<=[.!?\n])\s+")


class LayaClient:
    def __init__(self, base_url: str = config.LAYA_URL, timeout: float = config.LAYA_TIMEOUT):
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=timeout)

    def health(self) -> dict:
        r = self.client.get("/health")
        r.raise_for_status()
        return r.json()

    # ---- Gate -------------------------------------------------------------------------
    def gate(self, text: str) -> float:
        """Maximale Wahrscheinlichkeit über alle Abschnitte des Texts."""
        chunks = _chunk(text, config.GATE_CHUNK_CHARS)
        questions = {k: {"type": "noul", "instructions": v} for k, v in config.GATE_QUESTIONS.items()}
        best = 0.0
        for batch in _batches(chunks, 16):
            r = self.client.post("/v1/systemone/batch", json={
                "states": [{"body": c} for c in batch],
                "questions": questions,
                "model": config.LAYA_MODEL,
            })
            r.raise_for_status()
            for res in r.json()["results"]:
                for k in questions:
                    best = max(best, float(res["answers"][k]["noul"]))
        return best

    # ---- Treffer-Bestätigung ------------------------------------------------------------
    def classify(self, text: str, entities: list[Entity]) -> list[Entity]:
        todo = [e for e in entities
                if e.status == "accepted" and e.category in config.LAYA_CHECKED_CATEGORIES
                and not any(s.name == "regex" for s in e.sources)]  # Regex ist deterministisch
        if not todo:
            return entities
        questions = {"kind": {
            "type": "choice",
            "instructions": config.LAYA_CHOICE_INSTRUCTIONS,
            "criteria": config.LAYA_CHOICE_CRITERIA,
        }}
        verdicts: dict[int, LayaVerdict] = {}
        for batch in _batches(todo, 64):
            states = [{"body": _context(text, e), "candidate": e.text} for e in batch]
            r = self.client.post("/v1/systemone/batch", json={
                "states": states, "questions": questions, "model": config.LAYA_MODEL,
            })
            r.raise_for_status()
            for e, res in zip(batch, r.json()["results"]):
                ans = res["answers"]["kind"]
                verdicts[e.id] = _verdict(e, ans["choice"], ans["probabilities"])

        out = []
        for e in entities:
            v = verdicts.get(e.id)
            if v is None:
                out.append(e)
                continue
            update: dict = {"laya": v}
            if not v.accepted:
                update["status"] = "rejected_laya"
            elif v.recategorized_from:
                update["category"] = v.category
            out.append(e.model_copy(update=update))
        return out


def _verdict(e: Entity, choice: str, probs: dict[str, float]) -> LayaVerdict:
    p = float(probs.get(choice, 0.0))
    ns = float(probs.get("NICHT_SENSIBEL", 0.0))
    if ns >= config.LAYA_REJECT_THRESHOLD:
        return LayaVerdict(category="NICHT_SENSIBEL", probability=ns, probabilities=probs, accepted=False)
    if (choice != "NICHT_SENSIBEL" and choice != e.category
            and p >= config.LAYA_RECAT_THRESHOLD
            and _detector_confidence(e) <= config.LAYA_RECAT_MAX_DETECTOR_CONFIDENCE):
        return LayaVerdict(category=choice, probability=p, probabilities=probs, accepted=True,
                           recategorized_from=e.category)
    # Bestätigt (oder unsicher: dann bleibt die Kategorie des Erkenners stehen).
    return LayaVerdict(category=e.category, probability=float(probs.get(e.category, p)),
                       probabilities=probs, accepted=True)


def _detector_confidence(e: Entity) -> float:
    best = 0.0
    for s in e.sources:
        if s.name == "regex":
            best = max(best, 1.0)
        elif s.name == "spacy":
            best = max(best, config.SPACY_CONFIDENCE)
        else:
            best = max(best, s.score or 0.0)
    return best


def _context(text: str, e: Entity, window: int = 300) -> str:
    """Der Satz um den Treffer, aufgefüllt auf ein Fenster von etwa `window` Zeichen."""
    start = max(0, e.start - window // 2)
    end = min(len(text), e.end + window // 2)
    # An Satz-/Zeilengrenzen ausrichten, soweit möglich.
    left = text.rfind("\n", start, e.start)
    if left != -1:
        start = left + 1
    right = text.find("\n", e.end, end)
    if right != -1:
        end = right
    return text[start:end].strip()


def _chunk(text: str, size: int) -> list[str]:
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 > size and cur:
            chunks.append(cur)
            cur = ""
        while len(p) > size:
            chunks.append(p[:size])
            p = p[size:]
        cur = (cur + "\n\n" + p) if cur else p
    if cur:
        chunks.append(cur)
    return chunks or [text]


def _batches(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]
