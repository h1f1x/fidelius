import time

from fidelius.detectors.regex_det import detect_regex


def cats(text):
    return {(h.category, h.text) for h in detect_regex(text)}


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
    start = time.perf_counter()
    hits = detect_regex(attack)
    assert time.perf_counter() - start < 0.1
    assert not any(h.category == "ADRESSE" for h in hits)
