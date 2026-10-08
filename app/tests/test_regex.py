import time

import pytest

from fidelius.detectors.regex_det import detect_regex

NBSP = "\u00a0"

# Großzügig, damit eine langsame CI nicht flackert, aber weit unter dem, was die alten Muster
# brauchten: Das Backtracking lief bei diesen Eingaben praktisch endlos, die quadratische
# Telefon-Suche mehrere Sekunden.
LAUFZEIT_GRENZE_S = 1.0


def cats(text):
    return {(h.category, h.text) for h in detect_regex(text)}


def detect_within_limit(text):
    start = time.perf_counter()
    hits = detect_regex(text)
    assert time.perf_counter() - start < LAUFZEIT_GRENZE_S
    return hits


def test_email_and_phone():
    r = cats("Erreichbar unter max.mustermann@example.de oder +49 30 23125042.")
    assert ("EMAIL", "max.mustermann@example.de") in r
    assert ("TELEFON", "+49 30 23125042") in r


def test_iban_checksum():
    assert ("IBAN", "DE89 3704 0044 0532 0130 00") in cats("IBAN: DE89 3704 0044 0532 0130 00")
    assert not any(c == "IBAN" for c, _ in cats("IBAN: DE89 3704 0044 0532 0130 01"))


def test_dates():
    r = cats("Am 03.05.2026 und am 3. Mai 2026 sowie 2026-05-03.")
    assert ("DATUM", "03.05.2026") in r
    assert ("DATUM", "3. Mai 2026") in r
    assert ("DATUM", "2026-05-03") in r


def test_street():
    assert ("ADRESSE", "Musterstraße 12a") in cats("Wohnhaft in der Musterstraße 12a, 10115 Berlin")


def test_street_and_plate_starting_with_umlaut():
    r = cats("Neue Anschrift: Überseering 5, Kennzeichen ÜB-AB 123.")
    assert ("ADRESSE", "Überseering 5") in r
    assert ("KENNUNG", "ÜB-AB 123") in r


def test_street_with_accented_letters():
    assert ("ADRESSE", "Cézanne-Weg 3") in cats("Sie wohnt im Cézanne-Weg 3.")


def test_id_keyword_and_prefixed():
    r = cats("Versicherungsschein-Nr.: KV-2024-00123, Kundennummer 4711-88, Vorgang VS-889911.")
    assert ("KENNUNG", "KV-2024-00123") in r
    assert ("KENNUNG", "4711-88") in r
    assert ("KENNUNG", "VS-889911") in r


def test_date_not_phone():
    r = detect_regex("Termin am 12.10.2026 um 10 Uhr.")
    assert all(h.category != "TELEFON" for h in r)


def test_id_patterns_tightened():
    r = cats("Betriebsnummer 0043-117. Ich. Vertrag RV-2027-HA-03 und Police GB-77-129044.")
    assert ("KENNUNG", "0043-117") in r
    assert ("KENNUNG", "RV-2027-HA-03") in r
    assert ("KENNUNG", "GB-77-129044") in r
    assert not any(t.endswith(". I") for _, t in r)


def test_aktenzeichen():
    assert ("KENNUNG", "2026/0912/HH-7781") in cats("unter dem Aktenzeichen 2026/0912/HH-7781 aufgenommen")


def test_street_adversarial_input_is_fast():
    # Viele großgeschriebene Wortteile ohne Straßenendung trieben das alte Muster in
    # katastrophales Backtracking; unter RE2 bleibt die Laufzeit linear.
    attack = "Ab-" * 22 + "x, " + "Ab " * 2_000 + "x"
    hits = detect_within_limit(attack)
    assert not any(h.category == "ADRESSE" for h in hits)


def test_phone_adversarial_input_is_fast():
    # Eine Null, ein langer Ziffernlauf und ein Buchstabe dahinter: Das alte Muster probierte
    # mit seinen optionalen Trennern und dem Lookahead jede Aufteilung der Ziffern durch.
    attack = "0" + "1" * 30 + "x"
    hits = detect_within_limit(attack)
    assert not any(h.category == "TELEFON" for h in hits)


def repeat_to(unit, length):
    return (unit * (length // len(unit) + 1))[:length]


@pytest.mark.parametrize(
    "unit",
    [
        "0301234567,",  # dicht an dicht, jede Nummer teilt sich den Rand mit der nächsten
        "012 34, ",  # Kandidaten, die an der Ziffernzahl scheitern
        "012 34, ä ",  # dasselbe mit Nicht-ASCII, damit Zeichen- und Byte-Offsets auseinanderlaufen
        "DE89 3704 0044 0532 0130 00 ",  # Telefon-Kandidaten, die alle mit einer IBAN kollidieren
        "03.05.2026 ",
        "B-AB 12 ",
    ],
)
def test_many_candidates_stay_linear(unit):
    # 200.000 Zeichen mit Tausenden Kandidaten: Jede Suche, die den ganzen Text neu anfasst,
    # oder ein Abgleich jedes Kandidaten gegen alle Treffer wird hier quadratisch.
    detect_within_limit(repeat_to(unit, 200_000))


def test_phone_formats():
    text = (
        "Ruf an: +49 30 1234567, 0049 30 123 45 67; 030/1234567 oder 030 12 34 56. "
        "Mobil 0171-1234567,0172-7654321 und +49 40 987654. Büro (0171) 7654321."
    )
    phones = {t for c, t in cats(text) if c == "TELEFON"}
    assert phones == {
        "+49 30 1234567",
        "0049 30 123 45 67",
        "030/1234567",
        "030 12 34 56",
        "0171-1234567",
        "0172-7654321",
        "+49 40 987654",
        "(0171) 7654321",
    }


# Die öffnende Klammer gehört zur Vorwahl, nicht zum Rand davor; sonst bliebe sie beim Ersetzen
# verwaist stehen. Das gilt auch, wenn Punkt oder Buchstabe direkt davor stehen.
@pytest.mark.parametrize(
    "text, phone",
    [
        ("(030) 12 34 56", "(030) 12 34 56"),
        ("Tel.(030) 1234567", "(030) 1234567"),
        ("Tel(030) 1234567", "(030) 1234567"),
        ("x(030) 1234567", "(030) 1234567"),
        # Ohne schließende Klammer bleibt die öffnende draußen, wie bisher.
        ("Tel (030 1234567", "030 1234567"),
    ],
)
def test_phone_area_code_in_parentheses(text, phone):
    assert {t for c, t in cats(text) if c == "TELEFON"} == {phone}


def test_phone_needs_clean_edges():
    r = cats("Code A0301234567, Wert 0301234567x und Nummer 0301234567.5")
    assert not any(c == "TELEFON" for c, _ in r)


# Pythons re liest \d, \s, \w und \b nach Unicode, RE2 nur nach ASCII. Die Erwartungen stammen
# aus dem Stand vor der Umstellung auf RE2 (main mit re): dieselben Treffer wie zuvor.
@pytest.mark.parametrize(
    "text, expected",
    [
        (f"am 03.{NBSP}05.{NBSP}2026", ("DATUM", f"03.{NBSP}05.{NBSP}2026")),
        (f"am 3.{NBSP}Mai{NBSP}2026", ("DATUM", f"3.{NBSP}Mai{NBSP}2026")),
        ("am ０３.０５.２０２６", ("DATUM", "０３.０５.２０２６")),
        (f"ID 12{NBSP}345{NBSP}678{NBSP}901", ("KENNUNG", f"12{NBSP}345{NBSP}678{NBSP}901")),
        ("ID １２３４５６７８９０１", ("KENNUNG", "１２３４５６７８９０１")),
        (f"SV 12{NBSP}345678{NBSP}A{NBSP}123", ("KENNUNG", f"12{NBSP}345678{NBSP}A{NBSP}123")),
        (f"Musterstraße{NBSP}12", ("ADRESSE", f"Musterstraße{NBSP}12")),
        ("Musterstraße １２", ("ADRESSE", "Musterstraße １２")),
        (f"B-AB{NBSP}1234", ("KENNUNG", f"B-AB{NBSP}1234")),
        (f"Kundennummer{NBSP}4711-88", ("KENNUNG", "4711-88")),
        ("Tel ０１７１１２３４５６７", ("KENNUNG", "０１７１１２３４５６７")),
        ("Tel ٠١٧١١٢٣٤٥٦٧", ("KENNUNG", "٠١٧١١٢٣٤٥٦٧")),
        ("Tel 0171 １２３４５６７", ("TELEFON", "0171 １２３４５６７")),
        ("Tel 030\x0b1234567", ("TELEFON", "030\x0b1234567")),
        ("Tel 030\x851234567", ("TELEFON", "030\x851234567")),
        ("IBAN DE８９３７０４００４４０５３２０１３０００", ("KENNUNG", "DE８９３７０４００４４０５３２０１３０００")),
    ],
)
def test_unicode_digits_and_spaces_are_found(text, expected):
    assert expected in cats(text)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("IBAN äDE89370400440532013000ü", set()),
        ("Nrä12345678901ö", set()),
        ("SVä12345678A123", set()),
        ("Musterstraße 12ä", set()),
        ("ÜB-AB 123ä", set()),
        ("ÄVS-2024-001234", set()),
        ("VS-2024-001234ü", {("KENNUNG", "VS-2024")}),
        # Hinter „12 “ steht ein Wortzeichen, also liegt die Wortgrenze vor „ä“, nicht hinter „12“;
        # das Leerzeichen gehört wie bisher zum Treffer.
        ("Musterstraße 12 äb", {("ADRESSE", "Musterstraße 12 ")}),
    ],
)
def test_word_boundaries_follow_unicode(text, expected):
    assert cats(text) == expected
