"""Lastskript (scripts/loadtest.py), Spec: docs/specs/lasttest.md, 1 und 5.

Die Lastschleife selbst hat keine Unit-Tests (Spec Abschnitt 7). Hier steht nur, was das Skript
aus dem App-Paket nachbildet, weil es ohne das Paket läuft.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fidelius.calibration import Calibration

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _load():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module("loadtest")


loadtest = _load()


def test_long_text_is_the_long_text_of_the_calibration():
    calibration_text = Calibration(pipeline=None, examples_dir=ROOT / "examples")._texts()[-1]

    assert loadtest.long_text(loadtest.load_examples()) == calibration_text
