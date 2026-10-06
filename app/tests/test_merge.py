from fidelius.detectors.base import RawHit
from fidelius.merge import merge_hits


def test_longest_span_wins_and_sources_collected():
    text = "Herr Thomas Müller aus Berlin"
    hits = [
        RawHit(5, 18, "Thomas Müller", "PERSON", "gliner", "person", 0.9),
        RawHit(12, 18, "Müller", "PERSON", "spacy", "PER", None),
        RawHit(23, 29, "Berlin", "ORT", "spacy", "LOC", None),
    ]
    ents = merge_hits(hits, text)
    assert [(e.text, e.category) for e in ents] == [("Thomas Müller", "PERSON"), ("Berlin", "ORT")]
    assert {s.name for s in ents[0].sources} == {"gliner", "spacy"}


def test_regex_span_beats_overlapping_model_span():
    text = "Kundennummer 4711 Berlin"
    hits = [
        RawHit(13, 17, "4711", "KENNUNG", "regex", "id_keyword", 1.0),
        RawHit(13, 24, "4711 Berlin", "ORT", "spacy", "LOC", None),
    ]
    ents = merge_hits(hits, text)
    assert [(e.text, e.category) for e in ents] == [("4711", "KENNUNG")]
    assert {s.name for s in ents[0].sources} == {"regex", "spacy"}


def test_model_category_priority_only_when_covering():
    text = "Polizei Hamburg"
    hits = [
        RawHit(8, 15, "Hamburg", "ORT", "gliner", "city", 1.0),
        RawHit(0, 15, "Polizei Hamburg", "ORG", "spacy", "ORG", None),
    ]
    ents = merge_hits(hits, text)
    assert [(e.text, e.category) for e in ents] == [("Polizei Hamburg", "ORG")]


def test_filter_allowed_and_trim():
    text = "Hallo, Müller, "
    hits = [RawHit(6, 15, ", Müller, ", "PERSON", "spacy", "PER", None),
            RawHit(0, 5, "Hallo", "ORT", "spacy", "LOC", None)]
    ents = merge_hits(hits, text, allowed={"PERSON"})
    assert [e.text for e in ents] == ["Müller"]


def test_newline_cut_and_weekday_filter():
    text = "Müller Gruppe\n\nHallo Herr Hahn, am Donnerstag"
    hits = [RawHit(0, 30, "Müller Gruppe\n\nHallo Herr Hahn", "ORG", "spacy", "ORG", None),
            RawHit(35, 45, "Donnerstag", "DATUM", "gliner", "sensitive_date", 0.7)]
    ents = merge_hits(hits, text)
    assert [(e.text, e.category) for e in ents] == [("Müller Gruppe", "ORG")]


def test_regex_span_wins_over_longer_model_span():
    text = "Wasserschaden Schadennummer WS-2026-0918, Aufstellung"
    hits = [RawHit(28, 40, "WS-2026-0918", "KENNUNG", "regex", "id_keyword", 1.0),
            RawHit(0, 35, "Wasserschaden Schadennummer WS-2026", "ORT", "spacy", "LOC", None)]
    ents = merge_hits(hits, text)
    assert [(e.text, e.category) for e in ents] == [("WS-2026-0918", "KENNUNG")]


def test_table_cell_cut_and_short_spans():
    text = "| Malerbetrieb Lutz      | 2.110,00 EUR| Re: EG"
    hits = [RawHit(15, 38, "Lutz      | 2.110,00 EUR", "PERSON", "spacy", "PER", None),
            RawHit(41, 43, "Re", "PERSON", "spacy", "PER", None),
            RawHit(45, 47, "EG", "ORT", "gliner", "state_or_region", 0.7)]
    assert [e.text for e in merge_hits(hits, text)] == ["Lutz"]
