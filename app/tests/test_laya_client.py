import json
from unittest.mock import patch

import httpx

from fidelius import config
from fidelius.laya_client import LayaClient, _context, _sections, _verdict
from fidelius.models import Entity, Source


def test_chunk_respects_paragraphs():
    text = "\n\n".join(["a" * 250, "b" * 250, "c" * 250])
    chunks = [s.body for s in _sections(text, 520)]
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


# ---- Gate gegen ein Fake-Laya über HTTP -------------------------------------------------

def fake_laya(answer):
    """Ein LayaClient, dessen Batches `answer(frage, body)` beantwortet; zeichnet die Requests auf."""
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        results = [{"answers": {k: answer(k, s["body"]) for k in payload["questions"]}}
                   for s in payload["states"]]
        return httpx.Response(200, json={"results": results})

    return LayaClient(base_url="http://laya", transport=httpx.MockTransport(handle)), requests


def noul(value):
    return {"type": "noul", "noul": value}


def test_gate_value_is_highest_over_sections_and_questions():
    text = "\n\n".join(["a" * 500, "b" * 500, "c" * 500])
    laya, _ = fake_laya(lambda k, body: noul(0.7 if body.startswith("b") and k == "names" else 0.1))
    assert laya.gate(text).probability == 0.7


def test_extra_questions_run_in_the_gate_batch_and_come_back_per_section():
    text = "Erster Absatz mit Passwort.\n\nZweiter Absatz ohne."
    stufe = {"type": "choice", "instructions": "Welche Stufe?", "criteria": {"A": "a", "B": "b"}}
    zugang = {"type": "noul", "instructions": "Zugangsdaten?"}

    def answer(k, body):
        if k == "stufe":
            return {"type": "choice", "choice": "B", "probabilities": {"A": 0.2, "B": 0.8}}
        if k == "zugang":
            return noul(0.9 if "Passwort" in body else 0.05)
        return noul(0.2)

    laya, requests = fake_laya(answer)
    with patch.object(config, "GATE_CHUNK_CHARS", 30):
        result = laya.gate(text, extra={"stufe": stufe, "zugang": zugang})

    assert len(requests) == 1  # kein zweiter Durchlauf
    assert requests[0]["questions"]["stufe"] == stufe
    assert result.probability == 0.2  # Zusatzfragen zählen nicht zum Gate-Wert
    assert [text[s.start:s.end] for s in result.sections] == ["Erster Absatz mit Passwort.",
                                                               "Zweiter Absatz ohne."]
    assert [s.answers["zugang"]["noul"] for s in result.sections] == [0.9, 0.05]
    assert result.sections[0].answers["stufe"]["probabilities"] == {"A": 0.2, "B": 0.8}


def test_ask_sends_only_the_given_questions_on_gate_sections():
    """Zweiter Durchlauf der Klassifikation: dieselben Abschnitte, aber keine Gate-Fragen."""
    text = "Erster Absatz mit [PERSON_1].\n\nZweiter Absatz ohne."
    stufe = {"type": "choice", "instructions": "Welche Stufe?", "criteria": {"A": "a", "B": "b"}}
    laya, requests = fake_laya(lambda k, body: {"type": "choice", "choice": "A",
                                                "probabilities": {"A": 0.7, "B": 0.3}})
    with patch.object(config, "GATE_CHUNK_CHARS", 30):
        sections = laya.ask(text, {"stufe": stufe})

    assert [r["questions"] for r in requests] == [{"stufe": stufe}]
    assert [text[s.start:s.end] for s in sections] == ["Erster Absatz mit [PERSON_1].",
                                                       "Zweiter Absatz ohne."]
    assert [s.answers["stufe"]["probabilities"]["A"] for s in sections] == [0.7, 0.7]
