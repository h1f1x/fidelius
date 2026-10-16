"""Pydantic-Datenmodell: Treffer, Anfragen und Antworten der API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer

SourceName = Literal["gliner", "spacy", "regex"]
Status = Literal["accepted", "rejected_laya", "rejected_user", "manual"]


class Source(BaseModel):
    name: SourceName
    label: str
    score: float | None = None


class LayaVerdict(BaseModel):
    category: str
    probability: float
    probabilities: dict[str, float]
    accepted: bool
    recategorized_from: str | None = None


class Entity(BaseModel):
    id: int
    start: int
    end: int
    text: str
    category: str
    sources: list[Source] = Field(default_factory=list)
    laya: LayaVerdict | None = None
    placeholder: str | None = None
    status: Status = "accepted"

    def overlaps(self, other: "Entity") -> bool:
        return self.start < other.end and other.start < self.end


class Gate(BaseModel):
    probability: float | None
    threshold: float
    sensitive: bool
    skipped: bool = False
    note: str | None = None


class AnalyzeRequest(BaseModel):
    text: str
    categories: list[str] | None = None
    gate_threshold: float | None = None
    force: bool = False
    use_laya_check: bool = True


class Timing(BaseModel):
    gate_ms: int = 0
    detect_ms: int = 0
    laya_check_ms: int = 0
    # Zweiter Laya-Durchlauf auf dem anonymisierten Text; das Original steckt in gate_ms.
    classification_ms: int = 0
    total_ms: int = 0


class MappingEntry(BaseModel):
    placeholder: str
    original: str
    category: str
    sources: list[str]
    variants: list[str] = Field(default_factory=list)


class Span(BaseModel):
    start: int
    end: int


class ChunkLevel(BaseModel):
    """Bewertung eines Abschnitts, wie ihn das Gate an Laya schickt."""
    start: int
    end: int
    level: str
    probabilities: dict[str, float]  # je Stufen-id
    credentials: float | None = None  # Antwort auf `zugang`, solange nicht gefragt: None


class TextLevel(BaseModel):
    """Schutzstufe eines Texts: die höchste über alle Abschnitte, `chunk` hat sie ausgelöst."""
    level: str
    chunk: Span
    chunks: list[ChunkLevel]


class Classification(BaseModel):
    original: TextLevel | None  # None, wenn Laya nicht erreichbar war
    anonymized: TextLevel | None = None  # None, wenn der Text nicht neu bewertet wurde
    credentials: bool = False
    warn: bool = False
    note: str | None = None


class AnalyzeResponse(BaseModel):
    text: str
    gate: Gate
    entities: list[Entity]
    anonymized_text: str
    mapping: list[MappingEntry]
    timing: Timing
    # Nur bei aktiver Klassifikation; sonst fehlt das Feld in der Antwort ganz.
    classification: Classification | None = None

    @model_serializer(mode="wrap")
    def _omit_missing_classification(self, handler: SerializerFunctionWrapHandler) -> dict:
        data = handler(self)
        if data.get("classification") is None:
            data.pop("classification", None)
        return data


class ClassifyRequest(BaseModel):
    """„Neu bewerten“: der aktuelle anonymisierte Text."""
    text: str


class ApplyRequest(BaseModel):
    text: str
    entities: list[Entity]


class ApplyResponse(BaseModel):
    entities: list[Entity]
    anonymized_text: str
    mapping: list[MappingEntry]
