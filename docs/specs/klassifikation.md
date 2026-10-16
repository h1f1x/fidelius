# Spec: Klassifikation nach Schutzstufen

Stand: 2026-10-15, Ergebnis einer Klärungsrunde. Alle Punkte sind entschieden, umgesetzt ist noch nichts. Entscheidung: [ADR-0001](../adr/0001-klassifikation-warnt-je-installation.md). Issue: noch nicht angelegt.

## Ziel

- Fidelius schätzt ein, welcher Schutzstufe ein Text angehört, und zwar nach den Klassifikationsregeln der jeweiligen Installation.
- Es zeigt die Stufe vor und nach der Anonymisierung, etwa „Original: Vertraulich → Anonymisiert: Intern“.
- Liegt eine Stufe über der Freigabe der Installation oder enthält der Text Zugangsdaten, warnt Fidelius. Es sperrt nichts.
- Die Funktion hängt an einem Feature-Flag und ist ohne es aus. Ausgeschaltet verhält sich Fidelius genau wie heute.

## Ausgangslage

- Laya beantwortet heute zwei Arten von Fragen (`app/fidelius/laya_client.py`):
  - `noul` für das Gate: Ja/Nein-Wahrscheinlichkeit je Abschnitt von 600 Zeichen, der Höchstwert zählt.
  - `choice` für die Treffer-Bestätigung: `instructions` plus `criteria` (Label → Beschreibung), Antwort ist eine Wahrscheinlichkeit je Label.
- Kurze Kriterien funktionieren besser als lange: Mit ausführlichen Beschreibungen verwechselte Laya Personen mit Orten (`config.py`, Kommentar zu `LAYA_CHOICE_CRITERIA`).
- Stuft das Gate einen Text als harmlos ein, endet der Lauf vor den Erkennern. Die Antwort enthält dann keine Treffer, der anonymisierte Text ist gleich dem Original.
- Für Inhalte einer Installation gibt es ein Muster: `local/hinweise.md` liegt außerhalb des Repos, wird per `./local:/opt/local:ro` eingebunden, bei jedem Aufruf gelesen und von rsync weder übertragen noch gelöscht.
- GLiNER erkennt `password`, `secret` und `api_key` schon heute, sie landen in der Kategorie KENNUNG.
- `/api/apply` ist schnell und deterministisch, es ruft kein Modell auf.
- `calibration.py` misst Laufzeiten, nicht Treffsicherheit. Für die Treffsicherheit gibt es `scripts/run_examples.py` mit `examples/expected.json`.

## 1. Feature-Flag

- **Schalter:** Env `CLASSIFICATION_ENABLED`, Standard `0`. In `compose.yaml` als `"${CLASSIFICATION_ENABLED:-0}"` an den App-Container durchgereicht. Umschalten heißt Container neu starten.
- **Nur je Installation.** Nutzer können die Funktion in der UI nicht abschalten, denn eine Warnung, die man selbst abstellen kann, verfehlt ihren Zweck.
- **Flag aus:** Fidelius verhält sich genau wie heute.
  - Die Regeldatei wird nicht gelesen.
  - Keine Fragen `stufe` und `zugang` an Laya, kein zweiter Durchlauf.
  - Keine Kategorie `ZUGANG`, keine Regex-Muster für Zugangsdaten. GLiNER-Labels `password`, `secret`, `api_key` zeigen wie heute auf `KENNUNG`.
  - `/api/classify` antwortet mit 404.
  - `classification` fehlt in `/api/analyze` und ist `null` in `/api/config`. Die UI zeigt nichts davon.
  - Keine neuen Felder im Request-Log, keine Tabelle in `/auswertung`.
- **Flag an:** Die Funktion ist aktiv, sobald die Regeldatei gültig ist (Abschnitt 2).
- **Flag an, Datei fehlt oder ist ungültig:** Alles verhält sich wie bei Flag aus, auch `ZUGANG` ist aus. Einziger Unterschied: `/api/health` meldet den Fehler, damit eine vergessene Datei auffällt.
- **Tests** laufen mit beiden Stellungen. Mit Flag aus müssen die bestehenden Tests unverändert grün sein.

## 2. Regeln je Installation

- **Datei:** `local/klassifikation.yaml`, im Container `/opt/local/klassifikation.yaml`, Pfad per Env `CLASSIFICATION_FILE` änderbar.
- **Gelesen** bei jedem Aufruf, wie `hinweise.md`, aber nur bei Flag an. Eine Änderung an der Datei wirkt ohne Neustart.
- **Fehlt die Datei**, gibt es keine Klassifikation. Die UI zeigt nichts davon, `/api/config` liefert `classification: null`, `/api/health` meldet `"Fehler: Regeldatei fehlt (<Pfad>)"`.
- **Ist die Datei ungültig** (YAML-Fehler, weniger als zwei Stufen, unbekannte `freigegeben_bis`, doppelte `id`), ist die Funktion ebenfalls aus. `/api/health` meldet den Fehler mit Zeilennummer, die Anonymisierung läuft unverändert.
- **Format:**

```yaml
# Stufen von niedrig nach hoch. Die Reihenfolge ist die Rangfolge.
freigegeben_bis: intern        # id der höchsten Stufe, die ohne Warnung durchgeht
schwelle: 0.4                  # siehe Abschnitt 4
stufen:
  - id: oeffentlich
    name: Öffentlich
    laya: Veröffentlichte Information wie Pressemitteilung, Webseite, Gesetzestext oder Geschäftsbericht
    text: |
      **Definition:** Informationen, die für die Öffentlichkeit bestimmt und rechtmäßig veröffentlicht sind.
      **KI-Nutzung:** zulässig, sofern keine Rechte Dritter verletzt werden.
  - id: intern
    name: Intern
    laya: Interne Arbeitsunterlage, Protokoll oder Rundschreiben ohne Geschäftsgeheimnisse
    text: |
      …
  - id: vertraulich
    name: Vertraulich
    laya: Geschäftsgeheimnis, interne Finanzzahlen, Vertragsdaten einzelner Kunden, nicht öffentlicher Quellcode oder Sicherheitsinformation wie Schwachstelle, Netzwerkplan oder Firewall-Regel
    text: |
      …
  - id: streng_vertraulich
    name: Streng vertraulich
    laya: Gesundheitsdaten, Diagnose, Personalakte, Disziplinarvorgang oder Insider-Information
    text: |
      …
zugangsdaten:
  text: |
    Passwörter, Tokens, API-Keys und private Schlüssel dürfen nie in ein KI-System.
```

- **`laya`** ist die Kurzbeschreibung, die als `choice`-Kriterium an Laya geht: ein bis zwei Zeilen, konkrete Beispiele statt abstrakter Definition. Sie wird unabhängig von `text` getunt.
- **`text`** ist Markdown für die Anzeige: Definition, Beispiele, Regel für die KI-Nutzung.
- **`zugangsdaten.text`** ist optional. Fehlt es, zeigt die UI einen generischen Satz.
- Fidelius setzt keine Stufe voraus, auch nicht „Öffentlich“. Die unterste Stufe muss die Installation selbst definieren, sonst fehlt Laya eine Antwort für harmlose Texte.

## 3. Was im Repo liegt

- `klassifikation.example.yaml` im Repo-Root mit vier generischen Stufen wie oben. Kein Bezug auf eine bestimmte Organisation. Die Beispiele stammen aus Versicherung, Arztpraxis und Kanzlei, wie in `examples/`.
- Ein Abschnitt „Klassifikation“ im README: Format, Ablage in `local/`, Verhalten ohne oder mit ungültiger Datei.
- Synthetische Kalibrierbeispiele unter `examples/klassifikation/`, je Stufe mindestens drei Texte, dazu eine `expected.json` mit der erwarteten Stufe. Sie passen zur `klassifikation.example.yaml`. Das Unterverzeichnis taucht in der Beispielauswahl der UI nicht auf, weil `/api/examples` nur `*.txt` im obersten Verzeichnis listet.
- Die echten Regeln einer Installation, ihre Kurzfassungen und eigene Kalibrierbeispiele liegen nur in `local/`.
- `pyyaml` kommt als direkte Abhängigkeit in `app/pyproject.toml`. Heute ist es nur transitiv über `transformers` vorhanden.

## 4. Ablauf

- **Immer:** Die Klassifikation läuft auch dann, wenn das Gate den Text als harmlos einstuft. Gerade ein Text ohne Personen, aber mit Firewall-Regeln, braucht die Bewertung.
- **Original:** Die Fragen der Klassifikation gehen im selben Laya-Batch wie die Gate-Fragen raus, auf denselben Abschnitten von 600 Zeichen. Für das Original kostet die Klassifikation damit keinen zusätzlichen Durchlauf.
  - `stufe`: `choice` mit `instructions` „Welcher Schutzstufe gehört dieser Text an?“ und den `laya`-Beschreibungen als `criteria`.
  - `zugang`: `noul` mit „Enthält dieser Text ein Passwort, einen Token, einen API-Key, einen privaten Schlüssel oder andere Zugangsdaten?“
  - Ob Laya `noul` und `choice` in einem Batch mischt, ist vor der Umsetzung zu prüfen. Wenn nicht, wird es ein zweiter Batch auf denselben Abschnitten.
- **Anonymisierter Text:** Nach den Platzhaltern wird der anonymisierte Text auf dieselbe Weise klassifiziert, ein zweiter Laya-Durchlauf. Ist er gleich dem Original (Gate harmlos, keine Treffer), entfällt der Durchlauf und die Bewertung des Originals gilt für beide.
- **Stufe je Abschnitt:** Die höchste Stufe, deren Wahrscheinlichkeit mindestens `schwelle` beträgt. Erreicht keine Stufe die Schwelle, gilt die wahrscheinlichste. Bei einem Fehlalarm kostet eine Warnung wenig, ein übersehener vertraulicher Text kostet viel. Die Schwelle steht nach der Kalibrierung auf 0,4 (Abschnitt 9).
- **Stufe des Texts:** die höchste Stufe über alle Abschnitte. Der Abschnitt, der sie ausgelöst hat, wird mit Start und Ende im Text mitgeliefert.
- **Zugangsdaten im Text:** ja, wenn ein Treffer der Kategorie ZUGANG gefunden wurde (Abschnitt 5) oder `zugang` in einem Abschnitt den Wert `ZUGANG_THRESHOLD` erreicht (Env, Standard 0,9, kalibriert in Abschnitt 9).
- **Warnung:** ja, wenn die Stufe des Originals oder des anonymisierten Texts über `freigegeben_bis` liegt oder Zugangsdaten im Original gefunden wurden.
- **Laya nicht erreichbar:** wie beim Gate. Die App antwortet mit 200, die Klassifikation ist leer, ein Hinweis steht in `classification.note` und im Log-Feld `fehler`.

## 5. Zugangsdaten als Platzhalter

Alles in diesem Abschnitt gilt nur bei Flag an und gültiger Regeldatei.

- Neue Kategorie `ZUGANG` in `config.CATEGORIES` mit eigener Farbe, Platzhalter `[ZUGANG_1]`.
- Neue Regex-Muster im Regex-Erkenner, alle in RE2-Syntax:
  - privater Schlüssel im PEM-Format (`-----BEGIN … PRIVATE KEY-----` bis zum passenden END)
  - bekannte Token-Präfixe: `sk-`, `sk-ant-`, `ghp_`, `gho_`, `github_pat_`, `xoxb-`, `xoxp-`, `AKIA` mit 16 Zeichen, `glpat-`
  - JWT (`eyJ…\.eyJ…\.…`)
  - Schlüsselwort plus Wert: `passwort`, `password`, `pwd`, `kennwort`, `token`, `api_key`, `apikey`, `secret`, `client_secret`, gefolgt von `:` oder `=` und einem Wert ohne Leerzeichen
- GLiNER-Labels `password`, `secret` und `api_key` zeigen künftig auf `ZUGANG` statt auf `KENNUNG`.
- Regex-Treffer für ZUGANG fragt Laya nicht nach, wie alle Regex-Treffer. GLiNER-Treffer für ZUGANG werden nicht bestätigt, weil `NICHT_SENSIBEL` ein Passwort wie „Sommer2026!“ zu leicht ablehnt: ZUGANG kommt nicht in `LAYA_CHECKED_CATEGORIES`.
- Die Warnung bleibt auch dann stehen, wenn alle Zugangsdaten ersetzt sind: „Im Original stehen Zugangsdaten. Sie sind ersetzt, sollten aber als offengelegt gelten und ausgetauscht werden.“ Ein Secret, das einmal in einer Zwischenablage lag, gilt als kompromittiert.

## 6. Schnittstelle

- **`/api/analyze`:** Die Antwort bekommt ein Feld `classification`. Bei Flag aus oder ohne gültige Regeldatei fehlt es:

```json
{
  "original":   {"level": "vertraulich", "chunk": {"start": 1200, "end": 1790},
                 "chunks": [{"start": 0, "end": 590, "level": "intern",
                             "probabilities": {"oeffentlich": 0.1, "intern": 0.6, "…": 0.0}, "credentials": 0.02}]},
  "anonymized": {"level": "intern", "chunk": {"start": 0, "end": 610}, "chunks": ["…"]},
  "credentials": false,
  "warn": true,
  "note": null
}
```

  `anonymized` ist `null`, wenn der Text unverändert blieb. Die Abschnitte von `anonymized` beziehen sich auf den anonymisierten Text.
- **`POST /api/classify`** mit `{"text": "…"}` liefert ein einzelnes Objekt wie `original` oben. Die UI ruft es für „neu bewerten“ mit dem aktuellen anonymisierten Text auf. Es gelten dieselben Grenzen wie bei `/api/analyze` (Textlänge, Body).
- **`/api/apply`** bleibt ohne Modellaufruf.
- **`/api/config`** liefert `classification` mit `levels` (`id`, `name`, `text`), `freigegeben_bis`, `schwelle` (für die Expertenansicht) und `zugangsdaten_text`, ohne die `laya`-Kurzfassungen. Bei Flag aus, fehlender oder ungültiger Datei: `null`.
- **`/api/classify`** antwortet bei Flag aus oder ohne gültige Regeldatei mit 404.
- **`/api/health`** liefert `classification`: `"aus"` (Flag aus), `"aktiv: 4 Stufen"` oder `"Fehler: <Meldung mit Zeile>"` (Flag an, Datei fehlt oder ist ungültig).

## 7. UI

- **Normaler Modus:**
  - Ein Badge über dem Ergebnis: „Original: Vertraulich → Anonymisiert: Intern“, bei unverändertem Text nur „Vertraulich“. Die Farbe richtet sich nach Freigabe: bis `freigegeben_bis` neutral, darüber Warnfarbe.
  - Ein Warnbanner, wenn `warn` gesetzt ist. Darin steht der `text` der Stufe des anonymisierten Texts, bei Zugangsdaten zusätzlich `zugangsdaten.text` und der Hinweis zum Austauschen.
  - Der auslösende Abschnitt ist im Text markiert, ein Klick auf das Badge springt hin.
  - Nach jeder Änderung über `/api/apply` steht am Badge „veraltet“ und ein Button „neu bewerten“. Der ruft `/api/classify` auf und ersetzt die Bewertung des anonymisierten Texts.
- **Expertenmodus:** je Abschnitt die Wahrscheinlichkeiten aller Stufen und der `zugang`-Wert, dazu die eingestellte Schwelle.
- **Infobox „Wie funktioniert das?“:** ein Satz, dass die Einschätzung von einem Modell stammt und keine Freigabe ersetzt.

## 8. Request-Log

- Neue Felder je `/api/analyze`:
  - `stufe_original`, `stufe_anonymisiert` (die `id`, `null` bei Laya-Fehler)
  - `zugangsdaten` (ja/nein)
  - `gewarnt` (ja/nein)
  - `klassifikation_ms`: Dauer des zweiten Durchlaufs für den anonymisierten Text. Die Bewertung des Originals steckt in `gate_ms`.
- Die Felder stehen nur bei aktiver Klassifikation im Eintrag. `log_report.py` behandelt Einträge ohne sie als „Klassifikation aus“, die Tabelle in `/auswertung` zählt nur Einträge mit ihnen.
- Kein Text, keine Abschnittsgrenzen, keine Wahrscheinlichkeiten.
- `/api/classify` wird nicht geloggt, wie `/api/apply`. `stufe_anonymisiert` beschreibt also den Stand direkt nach der Analyse.
- `/auswertung` zeigt eine Tabelle: wie oft welche Stufe im Original, wie oft die Anonymisierung die Stufe gesenkt hat, wie oft gewarnt wurde.

## 9. Kalibrierung der Treffsicherheit

- `scripts/run_classification.py` schickt die Texte eines Verzeichnisses an `/api/classify` und vergleicht mit der `expected.json` daneben. Ausgabe: Konfusionsmatrix der Stufen und Trefferquote für Zugangsdaten.
- Make-Ziel `make classification-examples ARGS="--dir examples/klassifikation"`. Mit `--dir local/klassifikation-beispiele` misst eine Installation ihre eigenen Regeln.
- Damit werden `schwelle`, `ZUGANG_THRESHOLD` und die `laya`-Kurzfassungen der Beispieldatei festgelegt, bevor die Funktion ausgerollt wird.
- Umgesetzt: 16 Beispiele, je Stufe drei aus Versicherung, Arztpraxis und Kanzlei, dazu vier mit Zugangsdaten (drei vertraulich, ein internes Rundschreiben mit Gäste-WLAN-Passwort). Das Skript zählt Zugangsdaten nur über `zugang`, weil `/api/classify` die Regex-Muster nicht anwendet, und nimmt die Schwelle als `--zugang-threshold`, damit sie sich ohne Neustart erproben lässt.

### Messung (16. Oktober 2026)

Laya `multilingual` (Revision 7b928d8) auf CPU, `examples/klassifikation` gegen `klassifikation.example.yaml`. Laya antwortet bei gleichem Text und gleichen Kriterien deterministisch; Abweichungen zwischen den Läufen kommen nur aus den geänderten Kurzfassungen. Zeilen Soll, Spalten Ist.

**Startwerte** (`schwelle: 0.3`, bisherige Kurzfassungen, `ZUGANG_THRESHOLD=0.5`): Stufen 5/16 richtig.

| Soll \ Ist | oeffentlich | intern | vertraulich | streng_vertraulich |
|---|---|---|---|---|
| oeffentlich | 0 | 0 | 0 | 3 |
| intern | 0 | 2 | 0 | 2 |
| vertraulich | 0 | 4 | 0 | 2 |
| streng_vertraulich | 0 | 0 | 0 | 3 |

Zugangsdaten ab 0,5: 4/4 erkannt, 4 Fehlalarme bei 12 Texten ohne Zugangsdaten (02 Webseite, 05 Rundschreiben, 07 Schadenakte, 10 Leistungsfall).

**Gewählte Werte** (`schwelle: 0.4`, neue Kurzfassungen, `ZUGANG_THRESHOLD=0.9`): Stufen 12/16 richtig.

| Soll \ Ist | oeffentlich | intern | vertraulich | streng_vertraulich |
|---|---|---|---|---|
| oeffentlich | 2 | 0 | 0 | 1 |
| intern | 0 | 3 | 1 | 0 |
| vertraulich | 0 | 1 | 4 | 1 |
| streng_vertraulich | 0 | 0 | 0 | 3 |

Zugangsdaten ab 0,9: 4/4 erkannt, 2 Fehlalarme (02 Webseite mit 0,99, 07 Schadenakte mit 0,92).

Verlauf:

- Mit den alten Kurzfassungen hilft keine `schwelle`: Zwischen 0,15 und 0,6 bleiben es 4 bis 6 von 16. `vertraulich` gewinnt keinen einzigen Abschnitt (höchstens 0,32), dafür reißen einzelne Abschnitte öffentliche Texte auf `streng_vertraulich` („Impfungen, EKG“ auf der Praxis-Webseite) und vertrauliche fallen auf `intern`. Die Kurzfassungen sind der Hebel, nicht die Schwelle.
- Fünf Runden mit neuen Kurzfassungen. Was wirkt: `streng_vertraulich` an eine bestimmte Person binden („Diagnose, Befund oder Krankheit einer bestimmten Person“) statt an das Wort Gesundheitsdaten; damit kippen Webseite und Rundschreiben nicht mehr. `intern` und `vertraulich` über den Empfängerkreis trennen („für alle Mitarbeitenden“ gegen „nur für wenige Beteiligte“); erst damit wählt Laya `vertraulich` überhaupt. Aufzählungen nach Datenart allein („Daten einzelner Kunden, Finanzzahlen …“) ließen `vertraulich` bei 1 bis 2 von 6.
- `schwelle` mit den neuen Kurzfassungen: 0,25 ergibt 7/16, 0,3 ergibt 9/16, von 0,35 bis 0,6 durchgehend 12/16. Unter 0,35 heben Nebenstufen mit 0,30 bis 0,33 öffentliche und interne Texte an. Gewählt ist 0,4: im flachen Bereich, mit Abstand zur Kante bei 0,3, und so niedrig wie möglich, damit eine deutlich vertretene höhere Stufe noch gewinnt.
- `zugang`: Die vier Texte mit Zugangsdaten liegen bei 0,98 bis 1,00, die übrigen streuen bis 0,99 (02, Webseite mit Online-Formular). Eine saubere Trennung gibt es nicht. 0,9 halbiert die Fehlalarme gegenüber 0,5 und lässt 0,08 Abstand zum schwächsten Treffer (16, Gäste-WLAN). 0,95 hätte einen Fehlalarm weniger, läge aber nur 0,03 unter diesem Treffer; bei Zugangsdaten wiegt ein übersehener Fall schwerer als eine Warnung zu viel. In der App greifen zusätzlich die Regex-Muster (Abschnitt 5), die das Skript nicht misst.

Verbleibende Fehler und ihre Folge bei `freigegeben_bis: intern`:

- 13 Ticket mit Zugangsdaten, Soll `vertraulich`, Ist `intern`: Die Stufe warnt nicht, die Zugangsdaten-Warnung schon. Kein Text über der Freigabe bleibt ganz ohne Warnung.
- 01 Pressemitteilung auf `streng_vertraulich`, 06 Statistik auf `vertraulich`: Warnung zu viel. Beide hängen an je einem Abschnitt (Einleitung der Pressemitteilung 0,49, Kanzleistatistik 0,70).
- 08 Praxisfinanzen auf `streng_vertraulich` statt `vertraulich`: Warnung kommt, nur eine Stufe zu hoch.

Grenzen: 16 Beispiele sind wenig, die Zahlen zeigen Tendenzen, keine Quoten für den Betrieb. Die neue Kurzfassung für `vertraulich` nennt Quellcode und Sicherheitsinformation (Schwachstelle, Netzwerkplan) nicht mehr, weil keine Beispiele dafür vorliegen und die kürzeren Fassungen besser trennten; eine Installation mit solchen Texten ergänzt sie und misst mit eigenen Beispielen nach.

## 10. Doku

- `docs/protokollierung.md`: Die Klassifikation ist eine Einschätzung durch ein Modell, die Regeln stammen aus der Installation, das Request-Log enthält die Stufen.
- `docs/deployen.md`: `CLASSIFICATION_ENABLED` in der `.env` der VM und `local/klassifikation.yaml` neben `local/hinweise.md`, mit Verweis auf das README-Format. Reihenfolge beim Einschalten: Datei hochladen, Flag setzen, Container neu starten, `/api/health` prüfen.
- `compose.yaml`: `CLASSIFICATION_ENABLED: "${CLASSIFICATION_ENABLED:-0}"` beim App-Container.
- `.envrc.example`: auskommentiert `# export CLASSIFICATION_ENABLED=0  # 1 schaltet die Klassifikation an, braucht local/klassifikation.yaml`. Das eigene `.envrc` bleibt unberührt.
- `CONTEXT.md` gibt es noch nicht. Die Begriffe Schutzstufe, Klassifikationsregeln, Freigabe und Zugangsdaten wären die ersten Einträge, falls das Glossar entsteht.
