"""Gemeinsame Fakes, Regeldatei und Fixtures der Tests, ohne Modelle.

Die Testmodule importieren Hilfen nur von hier, nicht voneinander.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from fidelius import config, main
from fidelius.detectors.base import RawHit
from fidelius.laya_client import GateResult, Section
from fidelius.models import Entity
from fidelius.pipeline import Pipeline

# ---- Regeldatei der Klassifikation -------------------------------------------------------

RULES = """\
freigegeben_bis: intern
schwelle: 0.3
stufen:
  - id: oeffentlich
    name: Öffentlich
    laya: Veröffentlichte Information
    text: Darf in jedes KI-System.
  - id: intern
    name: Intern
    laya: Interne Arbeitsunterlage
    text: Nur in freigegebene KI-Systeme.
  - id: vertraulich
    name: Vertraulich
    laya: Geschäftsgeheimnis
    text: Nur mit Freigabe.
zugangsdaten:
  text: Nie in ein KI-System.
"""

# Wahrscheinlichkeiten für `stufe`, passend zu RULES
OEFFENTLICH = {"oeffentlich": 0.7, "intern": 0.2, "vertraulich": 0.1}
INTERN = {"oeffentlich": 0.1, "intern": 0.8, "vertraulich": 0.1}  # = freigegeben_bis
VERTRAULICH = {"oeffentlich": 0.1, "intern": 0.3, "vertraulich": 0.6}


@pytest.fixture
def rules_file(tmp_path, monkeypatch):
    """Gültige Regeldatei unter CLASSIFICATION_FILE; das Flag bleibt, wie es ist."""
    f = tmp_path / "klassifikation.yaml"
    f.write_text(RULES, encoding="utf-8")
    monkeypatch.setattr(config, "CLASSIFICATION_FILE", str(f))
    return f


@pytest.fixture
def enabled(rules_file, monkeypatch):
    """Klassifikation aktiv: Flag an, gültige Regeldatei."""
    monkeypatch.setattr(config, "CLASSIFICATION_ENABLED", True)


# ---- Fake-Laya ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Chunk:
    """Ein Abschnitt, wie ihn die Fake-Laya beantwortet; `end=None` heißt bis zum Textende.

    `stufe` sind die Wahrscheinlichkeiten je Kriterium, `None` heißt: das erste Kriterium sicher.
    """
    start: int = 0
    end: int | None = None
    stufe: dict[str, float] | None = None
    zugang: float = 0.0


class FakeLaya:
    """Laya ohne Netz: fester Gate-Wert, Antworten auf Zusatzfragen je Abschnitt, Bestätigung
    lässt alles durch. Zeichnet Zusatzfragen (`extras`) und zweite Durchläufe (`asked`) auf.

    `chunks` beantworten die Zusatzfragen im Gate-Batch, `ask_chunks` den zweiten Durchlauf.
    """

    def __init__(self, gate_probability: float = 0.9, reachable: bool = True,
                 chunks: Sequence[Chunk] = (Chunk(),),
                 ask_chunks: Sequence[Chunk] = (Chunk(stufe=OEFFENTLICH),),
                 ask_reachable: bool = True):
        self.gate_probability = gate_probability
        self.reachable = reachable
        self.chunks = tuple(chunks)
        self.ask_chunks = tuple(ask_chunks)
        self.ask_reachable = ask_reachable
        self.extras: list[dict | None] = []
        self.asked: list[tuple[str, dict]] = []
        self.classified = False

    def gate(self, text: str, extra: dict[str, dict] | None = None) -> GateResult:
        self.extras.append(extra)
        if not self.reachable:
            raise ConnectionError("Laya ist weg")
        if not extra:
            return GateResult(probability=self.gate_probability)
        return GateResult(probability=self.gate_probability,
                          sections=_answer(text, extra, self.chunks))

    def ask(self, text: str, questions: dict[str, dict]) -> list[Section]:
        self.asked.append((text, questions))
        if not self.ask_reachable:
            raise TimeoutError("Laya antwortet nicht")
        return _answer(text, questions, self.ask_chunks)

    def classify(self, text: str, entities: list[Entity]) -> list[Entity]:
        self.classified = True
        return entities


def _answer(text: str, questions: dict[str, dict], chunks: Sequence[Chunk]) -> list[Section]:
    sections = []
    for c in chunks:
        end = len(text) if c.end is None else c.end
        answers = {}
        for key, spec in questions.items():
            if spec["type"] == "choice":
                probs = c.stufe or {k: float(i == 0) for i, k in enumerate(spec["criteria"])}
                answers[key] = {"choice": max(probs, key=probs.get), "probabilities": probs}
            else:
                answers[key] = {"noul": c.zugang}
        sections.append(Section(c.start, end, text[c.start:end], answers))
    return sections


class FakeDetector:
    def __init__(self, *hits: RawHit):
        self.hits = list(hits)
        self.called = False

    def __call__(self, text: str) -> list[RawHit]:
        self.called = True
        return self.hits


class FakeClock:
    """Sekunden wie time.perf_counter; die Fakes lassen die Zeit vorrücken."""

    def __init__(self):
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def analyze_http(laya, text: str, detectors=(), clock=lambda: 0.0, **body) -> dict:
    """POST /api/analyze über HTTP, damit auch fehlende Felder der JSON-Antwort geprüft sind."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(main, "pipeline", Pipeline(laya=laya, detectors=list(detectors), clock=clock))
        r = TestClient(main.app).post("/api/analyze", json={"text": text, **body})
    assert r.status_code == 200
    return r.json()


# ---- Request-Log -------------------------------------------------------------------------

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def read_log(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def entry(time="2026-10-06T10:00:00+00:00", **fields) -> dict:
    """Eine Logzeile wie aus pipeline._log_entry, harmloser Text ohne Fehler."""
    line = {
        "zeit": time,
        "build": {"version": "0.1.0", "number": 37, "commit": "0d15b11", "dirty": False, "time": None},
        "quelle": "anfrage", "zeichen": 1000, "gate_wert": 0.1, "schwelle": 0.5,
        "sensibel": False, "trotzdem": False, "laya_bestaetigung": True,
        "gate_ms": 100, "erkennung_ms": 0, "laya_ms": 0, "gesamt_ms": 120,
        "stellen": 0, "platzhalter": 0, "laya_abgelehnt": 0, "fehler": None,
    }
    line.update(fields)
    return line


def write_log(path, *lines) -> None:
    path.write_text("".join((line if isinstance(line, str) else json.dumps(line)) + "\n"
                            for line in lines), encoding="utf-8")
