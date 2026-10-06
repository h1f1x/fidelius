"""Die volle Pipeline mit Fake-Laya und Fake-Detektoren, ohne Modelle."""
import json
from concurrent.futures import ThreadPoolExecutor

from fidelius.detectors.base import RawHit
from fidelius.models import AnalyzeRequest, Entity
from fidelius.pipeline import Pipeline

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


def read_log(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_analyze_writes_one_log_line_with_all_fields(tmp_path):
    log_path = tmp_path / "requests.jsonl"
    detector = FakeDetector(RawHit(5, 16, "Emre Yilmaz", "PERSON", "gliner", "person", 0.9),
                            RawHit(26, 32, "Berlin", "ORT", "spacy", "LOC"))
    pipeline = Pipeline(laya=FakeLaya(gate_probability=0.9), detectors=[detector],
                        log_path=log_path)

    pipeline.analyze(AnalyzeRequest(text=TEXT, gate_threshold=0.5), source="anfrage")

    [line] = read_log(log_path)
    assert set(line) == {
        "zeit", "build", "quelle", "zeichen",
        "gate_wert", "schwelle", "sensibel", "trotzdem", "laya_bestaetigung",
        "gate_ms", "erkennung_ms", "laya_ms", "gesamt_ms",
        "stellen", "platzhalter", "laya_abgelehnt", "fehler",
    }
    assert line["zeit"].endswith("+00:00")  # UTC
    assert line["build"]["version"]
    assert line["quelle"] == "anfrage"
    assert line["zeichen"] == 33
    assert line["gate_wert"] == 0.9
    assert line["schwelle"] == 0.5
    assert line["sensibel"] is True
    assert line["trotzdem"] is False
    assert line["laya_bestaetigung"] is True
    assert line["stellen"] == 2
    assert line["platzhalter"] == 2
    assert line["laya_abgelehnt"] == 0
    assert line["fehler"] is None


def test_log_contains_neither_text_nor_hits_nor_placeholders(tmp_path):
    log_path = tmp_path / "requests.jsonl"
    text = "Frau Quirinella Zwackelmann zahlt auf DE02120300000000202051."
    detector = FakeDetector(
        RawHit(5, 27, "Quirinella Zwackelmann", "PERSON", "gliner", "person", 0.9),
        RawHit(38, 60, "DE02120300000000202051", "IBAN", "regex", "iban"))
    pipeline = Pipeline(laya=FakeLaya(), detectors=[detector], log_path=log_path)

    res = pipeline.analyze(AnalyzeRequest(text=text))

    content = log_path.read_text(encoding="utf-8")
    assert res.anonymized_text == "Frau [PERSON_1] zahlt auf [IBAN_1]."  # Treffer gab es wirklich
    for secret in ("Quirinella", "Zwackelmann", "DE0212", "zahlt", "PERSON_1", "IBAN_1"):
        assert secret not in content


def test_log_for_harmless_text_has_no_detection(tmp_path):
    log_path = tmp_path / "requests.jsonl"
    detector = FakeDetector(RawHit(26, 32, "Berlin", "ORT", "spacy", "LOC"))
    pipeline = Pipeline(laya=FakeLaya(gate_probability=0.1), detectors=[detector],
                        log_path=log_path)

    pipeline.analyze(AnalyzeRequest(text=TEXT))

    [line] = read_log(log_path)
    assert line["sensibel"] is False
    assert line["erkennung_ms"] == 0
    assert line["laya_ms"] == 0
    assert line["stellen"] == 0


def test_log_for_unreachable_laya_has_no_gate_value_but_error(tmp_path):
    log_path = tmp_path / "requests.jsonl"
    pipeline = Pipeline(laya=FakeLaya(reachable=False), detectors=[FakeDetector()],
                        log_path=log_path)

    pipeline.analyze(AnalyzeRequest(text=TEXT))

    [line] = read_log(log_path)
    assert line["gate_wert"] is None
    assert line["fehler"] == "Laya nicht erreichbar (ConnectionError); Gate übersprungen."


def test_log_counts_hits_rejected_by_laya(tmp_path):
    log_path = tmp_path / "requests.jsonl"

    class RejectingLaya(FakeLaya):
        def classify(self, text, entities):
            return [e.model_copy(update={"status": "rejected_laya"}) for e in entities]

    detector = FakeDetector(RawHit(5, 16, "Emre Yilmaz", "PERSON", "gliner", "person", 0.9),
                            RawHit(26, 32, "Berlin", "ORT", "spacy", "LOC"))
    pipeline = Pipeline(laya=RejectingLaya(), detectors=[detector], log_path=log_path)

    pipeline.analyze(AnalyzeRequest(text=TEXT))

    [line] = read_log(log_path)
    assert line["laya_abgelehnt"] == 2
    assert line["stellen"] == 0


def test_log_records_calibration_source_and_force(tmp_path):
    log_path = tmp_path / "requests.jsonl"
    pipeline = Pipeline(laya=FakeLaya(gate_probability=0.1), detectors=[FakeDetector()],
                        log_path=log_path)

    pipeline.analyze(AnalyzeRequest(text=TEXT, force=True), source="kalibrierung")

    [line] = read_log(log_path)
    assert line["quelle"] == "kalibrierung"
    assert line["trotzdem"] is True


def test_parallel_analyses_append_whole_lines(tmp_path):
    log_path = tmp_path / "requests.jsonl"
    pipeline = Pipeline(laya=FakeLaya(), detectors=[FakeDetector()], log_path=log_path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: pipeline.analyze(AnalyzeRequest(text=TEXT)), range(200)))

    assert len(read_log(log_path)) == 200  # jede Zeile ist für sich gültiges JSON


def test_pipeline_without_log_path_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pipeline = Pipeline(laya=FakeLaya(), detectors=[FakeDetector()])

    pipeline.analyze(AnalyzeRequest(text=TEXT))

    assert list(tmp_path.iterdir()) == []


def test_unwritable_log_path_only_warns(tmp_path, caplog):
    log_path = tmp_path / "fehlt" / "requests.jsonl"  # Verzeichnis existiert nicht
    pipeline = Pipeline(laya=FakeLaya(), detectors=[FakeDetector()], log_path=log_path)

    res = pipeline.analyze(AnalyzeRequest(text=TEXT))

    assert res.gate.sensitive
    assert "Request-Log nicht schreibbar" in caplog.text
