import pytest

from fidelius import config
from fidelius.detectors import gliner

NAME = "Stefan Lorenz"


class FakeModel:
    """Findet NAME überall, wo er vollständig im übergebenen Text steht, und merkt sich die Längen."""

    def __init__(self):
        self.lengths = []

    def extract_entities(self, text, labels, **kwargs):
        self.lengths.append(len(text))
        spans, i = [], text.find(NAME)
        while i >= 0:
            spans.append({"start": i, "end": i + len(NAME), "confidence": 0.9})
            i = text.find(NAME, i + 1)
        return {"entities": {"person": spans}}


@pytest.fixture
def model(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(gliner, "_model", lambda: fake)
    return fake


def test_kurzer_text_geht_in_einem_aufruf(model):
    text = f"Hallo {NAME}, bis morgen."
    hits = gliner.detect_gliner(text)
    assert model.lengths == [len(text)]
    assert [(h.start, h.text) for h in hits] == [(6, NAME)]


def test_langer_text_geht_in_fenstern_mit_richtigen_offsets(model):
    # Der Speicher von GLiNER2 wächst überlinear mit der Textlänge, ein Aufruf mit ~8.000
    # Zeichen sprengt die VM (#9). Kein Aufruf darf mehr als ein Fenster bekommen.
    text = ("Lorem ipsum dolor sit amet. " * 40 + f"Gruß {NAME}\n\n") * 8
    hits = gliner.detect_gliner(text)
    assert max(model.lengths) <= config.GLINER_WINDOW_CHARS
    assert len(model.lengths) > 1
    assert all(text[h.start:h.end] == NAME for h in hits)
    assert {h.start for h in hits} == {i for i in range(len(text)) if text.startswith(NAME, i)}


def test_name_auf_der_fenstergrenze_wird_vollstaendig_gefunden(model):
    # Der Name steht so, dass ein Schnitt bei GLINER_WINDOW_CHARS mitten hindurchginge.
    pos = config.GLINER_WINDOW_CHARS - 5
    text = "x " * (pos // 2) + NAME + " y" * 1500
    start = text.index(NAME)
    hits = gliner.detect_gliner(text)
    assert (start, start + len(NAME)) in {(h.start, h.end) for h in hits}
