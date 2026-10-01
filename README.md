# Sensible Inhalte für ChatGPT ersetzen

Kleine Web-App, die E-Mails lokal anonymisiert, bevor man sie in ChatGPT, Claude oder einen anderen
KI-Dienst einfügt, und die Antwort anschließend wieder zurückübersetzt. Nichts verlässt den Rechner.

## Was passiert mit einer Mail

1. **Laya bewertet** die ganze Mail: Enthält sie personenbezogene Daten? Drei Fragen, der Höchstwert
   über alle Absätze zählt. Unter dem Schwellwert (Standard 0,5) endet der Lauf; „Trotzdem erkennen“
   überspringt das Gate.
2. **Drei Erkenner finden Treffer**, parallel:
   - GLiNER2-PII (`fastino/gliner2-privacy-filter-PII-multi`), mehrsprachig, 42 PII-Labels
   - spaCy `de_core_news_lg` für Personen, Orte, Organisationen
   - Regex für E-Mail, Telefon, IBAN (mit Prüfsumme), Datum, Straße mit Hausnummer, Kennungen
     hinter Schlüsselwörtern (Versicherungsschein-Nr., Kundennummer, Aktenzeichen …), Steuer-ID,
     Sozialversicherungsnummer, Kfz-Kennzeichen
3. **Zusammenführen**: Überlappende Treffer werden vereint. Regex-Spans gewinnen, sonst der längste
   Span. Treffer über Zeilenumbrüche oder Tabellenzellen hinweg werden abgeschnitten.
4. **Laya bestätigt jeden Modell-Treffer** im Satzkontext (Person, Organisation, Ort, Adresse, Datum,
   Kennung, nicht sensibel). Ab 0,9 für „nicht sensibel“ wird der Treffer abgelehnt und nur noch
   ausgegraut gezeigt. Eine Umkategorisierung nimmt Laya nur vor, wenn es sehr sicher ist (≥ 0,95)
   und der Erkenner unsicher war (nur spaCy). Regex-Treffer werden nicht nachgefragt.
5. **Platzhalter**: `[PERSON_1]`, `[ORG_1]`, `[ORT_1]`, `[ADRESSE_1]`, `[DATUM_1]`, `[EMAIL_1]`,
   `[TELEFON_1]`, `[IBAN_1]`, `[KENNUNG_1]`. Gleicher Wert bekommt denselben Platzhalter, auch in
   Varianten: „Herr Müller“, „Müller“, „T. Müller“, „Müller, Thomas“ und „Thomas Müller“ landen auf
   einem Platzhalter, wenn die Zuordnung eindeutig ist.

Die Zuordnungstabelle liegt nur im Browser (localStorage) und kann als JSON exportiert und wieder
importiert werden. Die Rückübersetzung läuft rein in JavaScript und erkennt auch umformatierte
Platzhalter wie `PERSON_1`, `[Person 1]` oder `**[PERSON_1]**`.

## Starten

Voraussetzung: Docker mit Compose v2, rund 8 GB RAM für Docker und 10 GB freier Plattenplatz.

```bash
cp .envrc.example .envrc        # optional, Ports und Schwellwerte
docker compose up --build -d    # erster Build lädt alle Modelle, dauert einige Minuten
open http://localhost:8080
```

Der Laya-Container lädt seinen Checkpoint beim ersten Start in ein Docker-Volume, die App hat
GLiNER2-PII und spaCy bereits im Image. Danach läuft alles ohne Internet (`HF_HUB_OFFLINE=1`).

| Dienst | Port | Inhalt |
|---|---|---|
| `app` | 8080 (nur localhost) | Web-UI, GLiNER2-PII, spaCy, Regex |
| `laya` | 8000 (nur im Compose-Netz) | Laya-Server, multilingualer Checkpoint |

Für Cloud oder On-Premise: beide Images bauen, `app` hinter einen Reverse-Proxy mit TLS und
Authentifizierung legen. Die App selbst hat keinen Login.

## Bedienung

Die Oberfläche ist für Nutzer ohne technisches Vorwissen gedacht. Ein Klick auf „Wie funktioniert
das?“ klappt eine Erklärung auf; Fehler erscheinen als rote Box, sonst wird nichts angezeigt.

- Links: E-Mail einfügen. Eingefügter Text wird sofort geprüft, getippter Text nach Klick auf
  „Anonymisieren“ (auch Cmd/Ctrl+Enter). Unter dem Feld lässt sich ein Beispiel wählen.
- Einschätzung: ein rot-grüner Balken mit Wortstufe („sehr unwahrscheinlich“ bis „sehr sicher“).
  Ab „wahrscheinlich“ wird direkt anonymisiert, sonst steht ein Knopf „Trotzdem anonymisieren“ da.
- Rechts: „Anonymisierter Text“ mit zwei Reitern: „mit Markierungen“ (Original durchgestrichen,
  Platzhalter farbig dahinter) und „so wie er kopiert wird“. Der Kopierknopf liefert immer nur den
  anonymisierten Text. Klick auf eine Stelle öffnet ein Popup: Art als farbige Chips wählen oder
  den Schalter „Wird ersetzt“ auf „Bleibt stehen“ stellen. Die Änderung gilt für alle Vorkommen
  desselben Werts. Darunter die Zuordnungstabelle mit Export/Import.
- Unten: KI-Antwort einfügen, „Rückübersetzen“, Ergebnis kopieren.

**Expertenmodus** (Schalter oben rechts, wird im Browser gemerkt) zeigt zusätzlich an jedem Treffer
die Quellen (**G** GLiNER2-PII, **S** spaCy, **R** Regex, **L✓/L✗** Laya-Urteil), die Spalte
„Quellen“ in der Tabelle, die Laufzeiten und zwei Einstellungen: ab welcher Einschätzung
automatisch anonymisiert wird und ob Laya jeden Treffer bestätigt.

## Prüfen, ob die Anonymisierung zu stark oder zu schwach ist

`examples/` enthält acht deutsche Beispielmails (Schadenmeldung, Vertragsänderung mit IBAN,
Bewerbung, harmlose Terminmail, Mehrdeutigkeiten wie „Müller Gruppe“ und „Essen“, Mailkette mit
Namensvarianten, Schadenaufstellung als Tabelle, deutsch-englischer Mischtext) und in
`expected.json` je Mail die Soll-Treffer (`must`) und Wörter, die stehen bleiben müssen (`keep`).

```bash
python3 scripts/run_examples.py        # alle Beispiele, volle Trefferliste
python3 scripts/run_examples.py -q 05  # nur Abgleich, nur Beispiel 05
```

Das Skript zeigt je Mail den Gate-Wert, jeden Treffer mit Quellen und Laya-Urteil und dann
`FEHLT` (zu schwach), `ZU VIEL` (zu stark) und `EXTRA` (ersetzt, aber nicht in der Soll-Liste).
Eigene Mails: als `.txt` nach `examples/` legen, Soll-Treffer in `expected.json` ergänzen.

Unit-Tests ohne Modelle (Regex, Zusammenführen, Platzhalter, Rückübersetzung):

```bash
cd app && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python pydantic httpx fastapi pytest
.venv/bin/python -m pytest -q
```

## Stellschrauben

| Variable | Standard | Wirkung |
|---|---|---|
| `GATE_THRESHOLD` | 0.5 | Laya-Gesamtbewertung, ab der die Erkennung startet |
| `LAYA_REJECT_THRESHOLD` | 0.9 | Laya-Wahrscheinlichkeit „nicht sensibel“, ab der ein Treffer abgelehnt wird |
| `LAYA_RECAT_THRESHOLD` | 0.95 | Sicherheit, ab der Laya einen spaCy-Treffer umkategorisieren darf |
| `GLINER_THRESHOLD` | 0.5 | Mindest-Score für GLiNER2-PII-Treffer |
| `OMP_NUM_THREADS` | 4 | CPU-Threads je Container |

Kategorien, Farben, Label-Zuordnungen und die Laya-Fragen stehen in `app/pii_app/config.py`.

## Bekannte Grenzen

- Laya markiert keine Textstellen, sondern klassifiziert. Es ist deshalb Gate und Bestätiger, nicht
  Finder. Seine Kategorieurteile sind schwankend; deshalb darf es nur sehr sicher ablehnen.
- Wörter, die Ort und Sache zugleich sind („Essen“), werden als Ort erkannt. Per Klick ablehnen.
- Firmennamen mit Nachnamen („Malerbetrieb Lutz“) werden teils als Person erkannt. Für die
  Anonymisierung ist das unschädlich, der Platzhalter ist nur anders benannt.
- Reine Jahreszahlen und Wochentage bleiben stehen, Beträge ebenfalls.
- Laufzeit auf CPU: 5 bis 12 Sekunden je Mail, davon der größte Teil die Laya-Bestätigung
  (rund 0,2 s je Treffer). Ohne Bestätigung (Häkchen in der UI) rund 2 bis 5 Sekunden.

## Lizenzen der Modelle

Laya (Convai Innovations), GLiNER2-PII (Fastino) und spaCy-Modelle (Explosion) stehen unter
Apache 2.0 bzw. MIT.
