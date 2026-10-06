"""Kalibrierung beim Start: misst die Pipeline und schätzt die Laufzeit als Sockel + Rate × Zeichen."""
from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .models import AnalyzeRequest
from .pipeline import Pipeline

log = logging.getLogger(__name__)

SHORT = "04_terminabsprache_harmlos"
MEDIUM = "06_mailkette_varianten"


@dataclass(frozen=True)
class Estimate:
    base_ms: float
    rate_ms_per_char: float
    measured_at: str


class Calibration:
    def __init__(self, pipeline: Pipeline, examples_dir: str | Path):
        self.pipeline = pipeline
        self.examples_dir = Path(examples_dir)
        self.result: Estimate | None = None

    def start(self) -> threading.Thread:
        """Misst im Hintergrund, damit die App sofort Anfragen annimmt."""
        thread = threading.Thread(target=self.run, name="kalibrierung", daemon=True)
        thread.start()
        return thread

    def run(self) -> None:
        # Im Hintergrund-Thread verschwände eine Exception ohne Spur; die App liefe
        # dann ohne Schätzung weiter, und niemand wüsste warum.
        try:
            self._calibrate()
        except Exception:
            log.exception("Kalibrierung fehlgeschlagen, die App läuft ohne Laufzeitschätzung.")

    def _calibrate(self) -> None:
        try:
            texts = self._texts()
        except OSError as exc:
            log.warning("Kalibrierung übersprungen, Beispiele fehlen: %s", exc)
            return
        # Der erste Lauf nach dem Warmup ist langsamer (Caches, JIT in torch); er zählt nicht.
        if self._measure(texts[0]) is None:
            return
        points = []
        for text in texts:
            ms = self._measure(text)
            if ms is None:
                return
            points.append((len(text), ms))
        base, rate = _least_squares(points)
        self.result = Estimate(base_ms=base, rate_ms_per_char=rate,
                               measured_at=datetime.now(UTC).isoformat(timespec="seconds"))
        log.info("Kalibrierung: %.0f ms Sockel + %.3f ms je Zeichen.", base, rate)

    def as_dict(self) -> dict | None:
        return asdict(self.result) if self.result else None

    def _texts(self) -> list[str]:
        """Kurz, mittel und alle Beispiele aneinander: drei Längen spannen die Gerade auf."""
        def read(p: Path) -> str:
            return p.read_text(encoding="utf-8")
        everything = "\n\n".join(read(p) for p in sorted(self.examples_dir.glob("*.txt")))
        return [read(self.examples_dir / f"{SHORT}.txt"),
                read(self.examples_dir / f"{MEDIUM}.txt"),
                everything]

    def _measure(self, text: str) -> int | None:
        """Gesamtdauer in ms, oder None, wenn Laya fehlte: ohne Laya wäre die Schätzung zu niedrig."""
        res = self.pipeline.analyze(AnalyzeRequest(text=text, force=True), source="kalibrierung")
        if res.gate.note is not None:
            log.warning("Kalibrierung verworfen: %s", res.gate.note)
            return None
        return res.timing.total_ms


def _least_squares(points: list[tuple[int, int]]) -> tuple[float, float]:
    """Beste Gerade mit Sockel und Rate ≥ 0, denn eine negative Laufzeit gibt es nicht."""
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    rate = (sum((x - mx) * (y - my) for x, y in points)
            / sum((x - mx) ** 2 for x, _ in points))
    if rate < 0:  # längere Texte schneller: Messrauschen, kein echter Effekt
        return my, 0.0
    base = my - rate * mx
    if base < 0:  # Gerade durch den Nullpunkt, z. B. wenn lange Texte überproportional dauern
        return 0.0, sum(x * y for x, y in points) / sum(x * x for x, _ in points)
    return base, rate
