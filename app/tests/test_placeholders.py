from fidelius.models import Entity, Source
from fidelius.placeholders import (anonymize, assign_placeholders, build_mapping, deanonymize,
                                  normalize)


def ent(i, start, text, cat, status="accepted", src="gliner"):
    return Entity(id=i, start=start, end=start + len(text), text=text, category=cat,
                  sources=[Source(name=src, label="x")], status=status)


def test_normalize_person_titles():
    assert normalize("Herrn Dr. Thomas Müller", "PERSON") == "thomas müller"
    assert normalize("Frau Schmidt,", "PERSON") == "schmidt"
    assert normalize("DE89 3704 0044 0532 0130 00", "IBAN") == "de89370400440532013000"


def test_same_value_same_placeholder_and_surname_cluster():
    text = "Thomas Müller schrieb. Herr Müller antwortete. Anna Schmidt las mit. Müller ging."
    ents = [ent(1, 0, "Thomas Müller", "PERSON"),
            ent(2, 23, "Herr Müller", "PERSON"),
            ents3 := ent(3, 47, "Anna Schmidt", "PERSON"),
            ent(4, 69, "Müller", "PERSON")]
    out = assign_placeholders(ents)
    ph = {e.id: e.placeholder for e in out}
    assert ph[1] == ph[2] == ph[4] == "[PERSON_1]"
    assert ph[3] == "[PERSON_2]"
    anon = anonymize(text, out)
    assert anon == "[PERSON_1] schrieb. [PERSON_1] antwortete. [PERSON_2] las mit. [PERSON_1] ging."
    mapping = build_mapping(out)
    m1 = next(m for m in mapping if m.placeholder == "[PERSON_1]")
    assert m1.original == "Thomas Müller"
    assert set(m1.variants) == {"Herr Müller", "Müller"}


def test_rejected_entities_get_no_placeholder():
    text = "Berlin ist groß."
    out = assign_placeholders([ent(1, 0, "Berlin", "ORT", status="rejected_laya")])
    assert out[0].placeholder is None
    assert anonymize(text, out) == text


def test_deanonymize_handles_variants():
    out = assign_placeholders([ent(1, 0, "Thomas Müller", "PERSON"), ent(2, 20, "Berlin", "ORT")])
    mapping = build_mapping(out)
    reply = "Hallo [PERSON_1], PERSON_1 wohnt in [Ort 1]; **[PERSON_1]** sagt «ORT-1»."
    assert deanonymize(reply, mapping) == \
        "Hallo Thomas Müller, Thomas Müller wohnt in Berlin; **Thomas Müller** sagt Berlin."


def test_deanonymize_person_12_not_hit_by_person_1():
    ents = [ent(i, i * 20, f"Name{i}", "PERSON") for i in range(1, 13)]
    mapping = build_mapping(assign_placeholders(ents))
    assert deanonymize("[PERSON_12] und [PERSON_1]", mapping) == "Name12 und Name1"


def test_name_variants_cluster():
    names = ["Thorsten Wiegand", "T. Wiegand", "Wiegand, Thorsten", "Wiegand", "Annika Reuter", "Annika", "Familie Krause", "Dagmar Krause"]
    ents = [ent(i, i * 30, n, "PERSON") for i, n in enumerate(names, 1)]
    ph = {e.text: e.placeholder for e in assign_placeholders(ents)}
    assert ph["Thorsten Wiegand"] == ph["T. Wiegand"] == ph["Wiegand, Thorsten"] == ph["Wiegand"] == "[PERSON_1]"
    assert ph["Annika Reuter"] == ph["Annika"] == "[PERSON_2]"
    assert ph["Familie Krause"] == ph["Dagmar Krause"] == "[PERSON_3]"


def test_mapping_prefers_full_name_over_titled_variant():
    out = assign_placeholders([ent(1, 0, "Herr Yilmaz", "PERSON"), ent(2, 30, "Emre Yilmaz", "PERSON")])
    m = build_mapping(out)[0]
    assert m.original == "Emre Yilmaz" and m.variants == ["Herr Yilmaz"]
