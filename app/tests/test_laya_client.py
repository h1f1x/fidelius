from fidelius import config
from fidelius.laya_client import _chunk, _context, _verdict
from fidelius.models import Entity, Source


def test_chunk_respects_paragraphs():
    text = "\n\n".join(["a" * 250, "b" * 250, "c" * 250])
    chunks = _chunk(text, 520)
    assert len(chunks) == 2
    assert chunks[0].startswith("a") and chunks[1].startswith("c")


def test_context_is_line_bounded():
    text = "Zeile eins.\nHerr Müller wohnt in Berlin.\nZeile drei."
    e = Entity(id=1, start=17, end=23, text="Müller", category="PERSON")
    assert _context(text, e) == "Herr Müller wohnt in Berlin."


def test_verdict_rules():
    e = Entity(id=1, start=0, end=6, text="Berlin", category="ORT",
               sources=[Source(name="spacy", label="LOC")])
    v = _verdict(e, "NICHT_SENSIBEL", {"NICHT_SENSIBEL": config.LAYA_REJECT_THRESHOLD + 0.1, "ORT": 0.2})
    assert not v.accepted
    v = _verdict(e, "ORG", {"ORG": 0.7, "ORT": 0.2})
    assert v.accepted and v.category == "ORT"  # 0.7 liegt unter der Umkategorisierungs-Schwelle
    v = _verdict(e, "ORG", {"ORG": 0.95, "ORT": 0.02})
    assert v.accepted and v.category == "ORG" and v.recategorized_from == "ORT"
    strong = e.model_copy(update={"sources": [Source(name="gliner", label="city", score=0.99)]})
    v = _verdict(strong, "ORG", {"ORG": 0.95, "ORT": 0.02})
    assert v.accepted and v.category == "ORT"  # GLiNER ist sicherer als Laya
    v = _verdict(e, "ORT", {"ORT": 0.9})
    assert v.accepted and v.recategorized_from is None
    v = _verdict(e, "NICHT_SENSIBEL", {"NICHT_SENSIBEL": 0.4, "ORT": 0.35})
    assert v.accepted and v.category == "ORT"
