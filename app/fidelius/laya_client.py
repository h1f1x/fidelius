"""HTTP-Client für den Laya-Server: Gesamtbewertung (noul) und Treffer-Bestätigung (choice)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx

from . import config
from .models import Entity, LayaVerdict

log = logging.getLogger(__name__)
_SENT_SPLIT = re.compile(r"(?<=[.!?\n])\s+")
_PARA_SPLIT = re.compile(r"\n\s*\n")


def unreachable(exc: BaseException) -> str:
    """Hinweis, wenn eine Laya-Anfrage scheitert; Gate, Klassifikation und /api/classify teilen ihn."""
    return f"Laya nicht erreichbar ({exc.__class__.__name__})"


@dataclass
class Section:
    """Ein Abschnitt des Texts, wie ihn das Gate an Laya schickt, mit Laya-Antworten je Frage.

    `start`/`end` sind Positionen im Originaltext. `answers` enthält die Rohantworten von Laya
    unter dem Schlüssel der Frage, also z. B. `{"noul": 0.8, ...}` oder
    `{"choice": "B", "probabilities": {...}, ...}`.
    """
    start: int
    end: int
    body: str
    answers: dict[str, dict] = field(default_factory=dict)


@dataclass
class GateResult:
    probability: float  # Höchstwert der Gate-Fragen über alle Abschnitte
    sections: list[Section] = field(default_factory=list)


class LayaClient:
    def __init__(self, base_url: str = config.LAYA_URL, timeout: float = config.LAYA_TIMEOUT,
                 transport: httpx.BaseTransport | None = None):
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def health(self) -> dict:
        r = self.client.get("/health")
        r.raise_for_status()
        return r.json()

    # ---- Gate -------------------------------------------------------------------------
    def gate(self, text: str, extra: dict[str, dict] | None = None) -> GateResult:
        """Bewertet den Text abschnittsweise mit den Gate-Fragen.

        `extra` sind weitere Laya-Fragen im Format des Batch-Endpunkts (`{"type": "noul" |
        "choice", "instructions": ..., "criteria": ...}`). Sie laufen im selben Batch auf
        denselben Abschnitten mit und zählen nicht zum Gate-Wert. Laya mischt `noul` und
        `choice` in einem Batch, die Gate-Werte bleiben dabei gleich (geprüft in #9).
        """
        extra = extra or {}
        clash = set(extra) & set(config.GATE_QUESTIONS)
        if clash:
            raise ValueError(f"Zusatzfragen überschreiben Gate-Fragen: {sorted(clash)}")
        gate_questions = {k: {"type": "noul", "instructions": v} for k, v in config.GATE_QUESTIONS.items()}
        sections = self.ask(text, {**gate_questions, **extra})
        best = max((float(s.answers[k]["noul"]) for s in sections for k in gate_questions), default=0.0)
        return GateResult(probability=best, sections=sections)

    def ask(self, text: str, questions: dict[str, dict]) -> list[Section]:
        """Stellt nur `questions` auf denselben Abschnitten wie das Gate, ohne Gate-Fragen.

        Für den zweiten Durchlauf der Klassifikation auf dem anonymisierten Text: Dort ist der
        Gate-Wert ohne Belang, die Abschnitte sollen aber genauso geschnitten sein wie beim Original.
        """
        sections = _sections(text, config.GATE_CHUNK_CHARS)
        for batch in _batches(sections, 16):
            r = self.client.post("/v1/systemone/batch", json={
                "states": [{"body": s.body} for s in batch],
                "questions": questions,
                "model": config.LAYA_MODEL,
            })
            r.raise_for_status()
            for section, res in zip(batch, r.json()["results"]):
                section.answers = res["answers"]
        return sections

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
    return [s.body for s in _sections(text, size)]


def _sections(text: str, size: int) -> list[Section]:
    """Absätze zu Abschnitten von höchstens `size` Zeichen; überlange Absätze werden geteilt.

    Der Text an Laya sind die Absätze, verbunden mit einer Leerzeile. `start`/`end` reichen
    vom ersten bis zum letzten Absatz des Abschnitts im Original.
    """
    paras, pos = [], 0
    for m in _PARA_SPLIT.finditer(text):
        paras.append((pos, m.start()))
        pos = m.end()
    paras.append((pos, len(text)))
    out: list[Section] = []
    cur: Section | None = None
    for start, end in paras:
        p = text[start:end]
        if not p.strip():
            continue
        if cur and len(cur.body) + len(p) + 2 > size:
            out.append(cur)
            cur = None
        while len(p) > size:
            out.append(Section(start, start + size, p[:size]))
            start, p = start + size, p[size:]
        if cur:
            cur.end, cur.body = end, cur.body + "\n\n" + p
        else:
            cur = Section(start, end, p)
    if cur:
        out.append(cur)
    return out or [Section(0, len(text), text)]


def _batches(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]
