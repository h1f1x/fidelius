"""Kategorien, Farben, Platzhalter und die Zuordnung der Modell-Labels auf unsere Kategorien."""
from __future__ import annotations

import os

# Reihenfolge = Anzeige-Reihenfolge in der UI. Farben sind für helle und dunkle Hintergründe lesbar.
CATEGORIES: dict[str, dict[str, str]] = {
    "PERSON":  {"label": "Person",            "color": "#e4572e"},
    "ORG":     {"label": "Organisation",      "color": "#17bebb"},
    "ORT":     {"label": "Ort",               "color": "#76b041"},
    "ADRESSE": {"label": "Adresse",           "color": "#ffc914"},
    "DATUM":   {"label": "Datum",             "color": "#a06cd5"},
    "EMAIL":   {"label": "E-Mail",            "color": "#2e86de"},
    "TELEFON": {"label": "Telefon",           "color": "#f368e0"},
    "IBAN":    {"label": "IBAN",              "color": "#ff9f43"},
    "KENNUNG": {"label": "Kennung / Nummer",  "color": "#8395a7"},
}

# Kategorien, bei denen Laya pro Treffer bestätigt. Regex-Treffer wie E-Mail oder IBAN sind
# deterministisch und werden nicht nachgefragt.
LAYA_CHECKED_CATEGORIES = {"PERSON", "ORG", "ORT", "ADRESSE", "DATUM", "KENNUNG"}

# Priorität bei Kategorie-Konflikten überlappender Treffer: kleiner gewinnt.
SOURCE_PRIORITY = {"regex": 0, "gliner": 1, "spacy": 2}

# GLiNER2-PII: nur die Labels, die wir abfragen, mit ihrer Zielkategorie.
GLINER_LABELS: dict[str, str] = {
    "person": "PERSON", "full_name": "PERSON", "first_name": "PERSON", "last_name": "PERSON",
    "date_of_birth": "DATUM", "sensitive_date": "DATUM", "document_date": "DATUM",
    "transaction_date": "DATUM", "expiration_date": "DATUM",
    "email": "EMAIL",
    "phone_number": "TELEFON",
    "address": "ADRESSE", "street_address": "ADRESSE", "postal_code": "ADRESSE",
    "city": "ORT", "state_or_region": "ORT",
    "bank_account": "KENNUNG", "account_number": "KENNUNG", "payment_card": "KENNUNG",
    "card_number": "KENNUNG", "government_id": "KENNUNG", "national_id_number": "KENNUNG",
    "passport_number": "KENNUNG", "drivers_license_number": "KENNUNG", "license_number": "KENNUNG",
    "tax_id": "KENNUNG", "tax_number": "KENNUNG", "account_id": "KENNUNG",
    "sensitive_account_id": "KENNUNG", "username": "KENNUNG", "ip_address": "KENNUNG",
    "password": "KENNUNG", "secret": "KENNUNG", "api_key": "KENNUNG",
}
GLINER_MODEL = "fastino/gliner2-privacy-filter-PII-multi"
GLINER_THRESHOLD = float(os.environ.get("GLINER_THRESHOLD", "0.5"))
# GLiNER2 bekommt den Text in Fenstern: Sein Speicher wächst überlinear mit der Länge, ab ~6.000
# Zeichen um Gigabytes (#9). Die Überlappung fasst Namen, die auf einer Fenstergrenze liegen.
GLINER_WINDOW_CHARS = 2000
GLINER_WINDOW_OVERLAP = 200

# spaCy de_core_news_lg: PER, LOC, ORG, MISC. MISC wird ignoriert.
SPACY_LABELS: dict[str, str] = {"PER": "PERSON", "LOC": "ORT", "ORG": "ORG"}
SPACY_MODEL = "de_core_news_lg"

LAYA_URL = os.environ.get("LAYA_URL", "http://localhost:8000").rstrip("/")
LAYA_MODEL = "multilingual"
LAYA_TIMEOUT = float(os.environ.get("LAYA_TIMEOUT", "120"))
GATE_THRESHOLD = float(os.environ.get("GATE_THRESHOLD", "0.5"))
# Laya lehnt einen Treffer nur bei sehr hoher Sicherheit ab: bei 0,6 bis 0,8 traf es auch echte
# Daten und Vornamen; die eindeutigen Fälle (Sprint-Review, Workshop) liegen über 0,9.
LAYA_REJECT_THRESHOLD = float(os.environ.get("LAYA_REJECT_THRESHOLD", "0.9"))
# Zeichen pro Abschnitt für das Gate. Kleine Abschnitte, weil Laya den Höchstwert über alle
# Abschnitte liefert und ein sensibler Absatz in einer langen Mail sonst untergeht.
GATE_CHUNK_CHARS = 600

# Mehrere Fragen, der Höchstwert zählt. Einzelne Formulierungen reagieren unterschiedlich auf
# Mails mit wenigen Personen, aber vielen Kontaktdaten, oder auf gemischtsprachige Texte.
GATE_QUESTIONS: dict[str, str] = {
    "pii": (
        "Enthält dieser Text personenbezogene Daten wie Namen von Personen, Postadressen, "
        "E-Mail-Adressen, Telefonnummern, Geburtsdaten, Bankverbindungen, Kunden-, Vertrags- oder "
        "Versicherungsnummern oder andere vertrauliche Angaben zu einzelnen Personen oder Firmen?"
    ),
    "names": "Werden in diesem Text einzelne Personen mit Namen genannt?",
    "contact": "Enthält der Text Kontaktdaten, Adressen, Kennnummern oder Bankdaten?",
}

# Kurze Beschreibungen: mit ausführlichen Kriterien verwechselte Laya Personen mit Orten.
LAYA_CHOICE_INSTRUCTIONS = "Welche Art von Angabe ist der Kandidat in diesem Zusammenhang?"
LAYA_CHOICE_CRITERIA: dict[str, str] = {
    "PERSON": "Name einer natürlichen Person",
    "ORG": "Name einer Firma, Behörde oder Organisation",
    "ORT": "Stadt, Region oder Land",
    "ADRESSE": "Straße mit Hausnummer oder Postleitzahl",
    "DATUM": "Kalenderdatum",
    "KENNUNG": "Nummer oder Kennung wie Kunden-, Vertrags- oder Kontonummer",
    "NICHT_SENSIBEL": "Allgemeines Wort, Fachbegriff, Wochentag oder Betrag",
}
# Laya darf die Kategorie nur ändern, wenn es sehr sicher ist und der Erkenner unsicher war
# (Laya hielt sonst "Herr Okonkwo" für einen Ort und "Deutsche Kreditbank" für eine Kennung).
LAYA_RECAT_THRESHOLD = float(os.environ.get("LAYA_RECAT_THRESHOLD", "0.95"))
# Nur Treffer, deren Erkenner höchstens so sicher ist, dürfen umkategorisiert werden (spaCy-only).
LAYA_RECAT_MAX_DETECTOR_CONFIDENCE = 0.6
# Feste Konfidenz für Erkenner ohne Score (spaCy); Regex gilt als 1.0.
SPACY_CONFIDENCE = 0.6

# Wochentage und Tageszeiten sind keine identifizierenden Daten.
DATE_STOPWORDS = {
    "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag",
    "montags", "dienstags", "mittwochs", "donnerstags", "freitags", "samstags", "sonntags",
    "morgen", "übermorgen", "gestern", "heute", "vormittag", "nachmittag", "abend",
    "wochenende", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}

EXAMPLES_DIR = os.environ.get("EXAMPLES_DIR", "/opt/examples")

# Eine JSON-Zeile je Prüfung für die spätere Auswertung (Textlängen, Gate-Quote, Dauern).
# Liegt auf einem Volume, weil docker logs einen Deploy nicht überdauert.
REQUEST_LOG = os.environ.get("REQUEST_LOG", "/var/log/fidelius/requests.jsonl")

# Obergrenze je Anfrage. Eine lange Mailkette hat einige tausend Zeichen; ohne Grenze hält ein
# einzelner Request mit Megabytes an Text die CPU minutenlang fest.
MAX_TEXT_CHARS = int(os.environ.get("MAX_TEXT_CHARS", "50000"))
# Die Textgrenze greift erst nach dem Parsen. Die Body-Grenze greift vorher, die Entity-Grenze
# deckt /api/apply ab, wo eine lange Trefferliste trotz kurzem Text Rechenzeit kostet.
MAX_BODY_BYTES = 2_000_000
MAX_ENTITIES = 2000
