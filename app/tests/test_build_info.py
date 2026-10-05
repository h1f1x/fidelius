import re

from pii_app import build_info

KEYS = ("BUILD_NUMBER", "BUILD_COMMIT", "BUILD_DIRTY", "BUILD_TIME")


def test_version_comes_from_pyproject():
    assert re.fullmatch(r"\d+\.\d+\.\d+", build_info.version())


def test_build_without_values_is_unknown(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    b = build_info.build()
    assert (b["number"], b["commit"], b["dirty"], b["time"]) == (None, None, False, None)


def test_build_reads_values(monkeypatch):
    for k, v in zip(KEYS, ("47", "5bad374", "1", "2026-10-05T12:32:00Z")):
        monkeypatch.setenv(k, v)
    b = build_info.build()
    assert (b["number"], b["commit"], b["dirty"], b["time"]) == (47, "5bad374", True, "2026-10-05T12:32:00Z")
