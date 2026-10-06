"""Version und Build-Stand für die Anzeige in der UI."""
from __future__ import annotations

import os
import tomllib
from functools import cache
from pathlib import Path

# Liegt im Image neben fidelius (COPY pyproject.toml im Dockerfile), lokal eine Ebene über dem Paket.
PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@cache
def version() -> str:
    return tomllib.loads(PYPROJECT.read_text())["project"]["version"]


def build() -> dict:
    """Die BUILD_*-Werte setzt scripts/build-info.sh beim Image-Build. Fehlen sie, wurde ohne
    make up oder scripts/deploy.sh gebaut, und der Stand ist unbekannt."""
    env = lambda k: os.environ.get(k) or None  # noqa: E731
    number = env("BUILD_NUMBER")
    return {
        "version": version(),
        "number": int(number) if number else None,
        "commit": env("BUILD_COMMIT"),
        "dirty": env("BUILD_DIRTY") == "1",
        "time": env("BUILD_TIME"),
    }
