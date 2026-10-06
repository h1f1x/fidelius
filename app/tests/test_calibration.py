"""Kalibrierung der Laufzeitschätzung über die Pipeline-Seam, ohne Modelle."""
import threading
from pathlib import Path

from pii_app.calibration import Calibration
from pii_app.pipeline import Pipeline

from .test_pipeline import FakeClock, FakeLaya, read_log

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

# Zweierpotenzen, damit die Sekunden binär exakt sind.
BASE_S = 0.5            # 500 ms Sockel je Lauf (Gate)
PER_CHAR_S = 2 ** -9    # 1,953125 ms je Zeichen (Erkennung)


def timed_pipeline(clock, laya=None, **kwargs) -> Pipeline:
    class TimedLaya(FakeLaya):
        def gate(self, text):
            clock.now += BASE_S
            return super().gate(text)

    def detector(text):
        clock.now += len(text) * PER_CHAR_S
        return []

    return Pipeline(laya=laya or TimedLaya(), detectors=[detector], clock=clock, **kwargs)


def test_calibration_fits_base_and_rate_from_clock():
    pipeline = timed_pipeline(FakeClock())
    calibration = Calibration(pipeline, EXAMPLES)

    calibration.run()

    result = calibration.as_dict()
    # total_ms wird auf ganze ms abgeschnitten, daher die Toleranz.
    assert abs(result["base_ms"] - 500) < 1
    assert abs(result["rate_ms_per_char"] - 1.953125) < 0.001
    assert result["measured_at"].endswith("+00:00")


def test_calibration_logs_all_four_runs_as_forced(tmp_path):
    log_path = tmp_path / "requests.jsonl"
    calibration = Calibration(timed_pipeline(FakeClock(), log_path=log_path), EXAMPLES)

    calibration.run()

    lines = read_log(log_path)
    assert len(lines) == 4  # Aufwärmlauf und drei Messläufe
    assert all(line["quelle"] == "kalibrierung" for line in lines)
    assert all(line["trotzdem"] is True for line in lines)
    assert [line["zeichen"] for line in lines][:3] == [515, 515, 1383]


def test_unreachable_laya_publishes_no_calibration():
    pipeline = timed_pipeline(FakeClock(), laya=FakeLaya(reachable=False))
    calibration = Calibration(pipeline, EXAMPLES)

    calibration.run()

    assert calibration.as_dict() is None


def test_missing_examples_publish_no_calibration(tmp_path):
    calibration = Calibration(timed_pipeline(FakeClock()), tmp_path)

    calibration.run()

    assert calibration.as_dict() is None


def test_calibration_is_null_until_measurement_ends():
    release = threading.Event()

    class BlockingLaya(FakeLaya):
        def gate(self, text):
            release.wait(timeout=5)
            return super().gate(text)

    calibration = Calibration(timed_pipeline(FakeClock(), laya=BlockingLaya()), EXAMPLES)

    thread = calibration.start()  # kehrt sofort zurück, die Messung hängt am Gate
    assert calibration.as_dict() is None
    release.set()
    thread.join(timeout=5)

    assert calibration.as_dict() is not None


def test_failing_detector_logs_and_publishes_no_calibration(caplog):
    def broken(text):
        raise RuntimeError("Modell kaputt")

    pipeline = Pipeline(laya=FakeLaya(), detectors=[broken], clock=FakeClock())
    calibration = Calibration(pipeline, EXAMPLES)

    calibration.run()  # darf nicht werfen, sonst stirbt der Thread stumm

    assert calibration.as_dict() is None
    record = next(r for r in caplog.records if r.name == "pii_app.calibration")
    assert "Kalibrierung fehlgeschlagen" in record.getMessage()
    assert record.exc_info is not None  # Traceback landet im Log
