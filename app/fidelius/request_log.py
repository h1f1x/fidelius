"""Request-Log: eine JSON-Zeile je Prüfung, ohne Text und ohne Treffer."""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class RequestLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        # Kalibrierung (Hintergrund-Thread) und Anfragen (Threadpool) schreiben parallel;
        # ohne Lock könnten sich zwei Zeilen ineinanderschieben.
        self._lock = threading.Lock()

    def write(self, entry: dict) -> None:
        """Hängt eine Zeile an; ein Schreibfehler darf die Antwort an den Nutzer nicht kosten."""
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        try:
            with self._lock, self.path.open("a", encoding="utf-8") as f:
                f.write(line)
        except OSError as exc:
            log.warning("Request-Log nicht schreibbar (%s): %s", self.path, exc)
