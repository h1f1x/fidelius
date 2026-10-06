"""Die volle Pipeline mit Fake-Laya und Fake-Detektoren, ohne Modelle."""
from pii_app.detectors.base import RawHit
from pii_app.models import AnalyzeRequest, Entity
from pii_app.pipeline import Pipeline

TEXT = "Herr Emre Yilmaz wohnt in Berlin."


class FakeLaya:
    def __init__(self, gate_probability=0.9, reachable=True):
        self.gate_probability = gate_probability
        self.reachable = reachable
        self.classified = False

    def gate(self, text: str) -> float:
        if not self.reachable:
            raise ConnectionError("Laya ist weg")
        return self.gate_probability

    def classify(self, text: str, entities: list[Entity]) -> list[Entity]:
        self.classified = True
        return entities


class FakeDetector:
    def __init__(self, *hits: RawHit):
        self.hits = list(hits)
        self.called = False

    def __call__(self, text: str) -> list[RawHit]:
        self.called = True
        return self.hits


def test_harmless_text_skips_detection_and_laya_check():
    laya = FakeLaya(gate_probability=0.1)
    detector = FakeDetector(RawHit(5, 16, "Emre Yilmaz", "PERSON", "gliner", "person", 0.9))
    pipeline = Pipeline(laya=laya, detectors=[detector])

    res = pipeline.analyze(AnalyzeRequest(text=TEXT))

    assert not res.gate.sensitive
    assert res.entities == []
    assert res.anonymized_text == TEXT
    assert not detector.called
    assert not laya.classified


def test_sensitive_text_merges_hits_and_assigns_placeholders():
    laya = FakeLaya(gate_probability=0.9)
    gliner = FakeDetector(RawHit(5, 16, "Emre Yilmaz", "PERSON", "gliner", "person", 0.9))
    spacy = FakeDetector(RawHit(5, 16, "Emre Yilmaz", "PERSON", "spacy", "PER"),
                         RawHit(26, 32, "Berlin", "ORT", "spacy", "LOC"))
    pipeline = Pipeline(laya=laya, detectors=[gliner, spacy])

    res = pipeline.analyze(AnalyzeRequest(text=TEXT))

    assert res.gate.sensitive
    assert res.anonymized_text == "Herr [PERSON_1] wohnt in [ORT_1]."
    person = next(e for e in res.entities if e.category == "PERSON")
    assert [s.name for s in person.sources] == ["gliner", "spacy"]
    assert laya.classified
    assert res.gate.note is None


def test_unreachable_laya_skips_gate_and_sets_note():
    laya = FakeLaya(reachable=False)
    detector = FakeDetector(RawHit(26, 32, "Berlin", "ORT", "spacy", "LOC"))
    pipeline = Pipeline(laya=laya, detectors=[detector])

    res = pipeline.analyze(AnalyzeRequest(text=TEXT))

    assert res.gate.probability is None
    assert res.gate.sensitive
    assert res.gate.note == "Laya nicht erreichbar (ConnectionError); Gate übersprungen."
    assert res.anonymized_text == "Herr Emre Yilmaz wohnt in [ORT_1]."
    assert not laya.classified


class FakeClock:
    """Sekunden wie time.perf_counter; die Fakes unten lassen die Zeit vorrücken."""

    def __init__(self):
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_timing_reports_phase_durations_from_clock():
    # Zweierpotenzen, damit die Sekunden binär exakt sind und kein Rundungsfehler entsteht.
    clock = FakeClock()

    class SlowLaya(FakeLaya):
        def gate(self, text):
            clock.now += 0.125
            return super().gate(text)

        def classify(self, text, entities):
            clock.now += 0.5
            return super().classify(text, entities)

    def slow_detector(text):
        clock.now += 0.25
        return [RawHit(26, 32, "Berlin", "ORT", "spacy", "LOC")]

    pipeline = Pipeline(laya=SlowLaya(gate_probability=0.9), detectors=[slow_detector], clock=clock)

    res = pipeline.analyze(AnalyzeRequest(text=TEXT))

    assert res.timing.gate_ms == 125
    assert res.timing.detect_ms == 250
    assert res.timing.laya_check_ms == 500
    assert res.timing.total_ms == 875
