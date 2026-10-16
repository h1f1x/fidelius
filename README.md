# Sensible Inhalte für ChatGPT ersetzen

Kleine Web-App, die Texte anonymisiert, bevor man sie in ChatGPT, Claude oder einen anderen
KI-Dienst einfügt, und die Antwort anschließend wieder zurückübersetzt. Alle Modelle laufen in den
eigenen Containern: Der Text geht an keinen externen Dienst, er bleibt auf dem Rechner oder Server,
auf dem die App läuft.

## Was passiert mit einem Text

1. **Laya bewertet** den ganzen Text: Enthält er personenbezogene Daten? Drei Fragen, der Höchstwert
   über alle Absätze zählt. Unter dem Schwellwert (Standard 0,5) endet der Lauf; „Trotzdem
   anonymisieren“ überspringt das Gate.
2. **Drei Erkenner finden Treffer**, parallel:
   - GLiNER2-PII (`fastino/gliner2-privacy-filter-PII-multi`), mehrsprachig, 42 PII-Labels
   - spaCy `de_core_news_lg` für Personen, Orte, Organisationen
   - Regex für E-Mail-Adresse, Telefon, IBAN (mit Prüfsumme), Datum, Straße mit Hausnummer, Kennungen
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

Voraussetzung: rund 8 GB RAM für Docker und 10 GB freier Plattenplatz. Einrichtung für macOS und
Windows (WSL2) mit allen Details: [docs/lokal-aufsetzen.md](docs/lokal-aufsetzen.md).

```bash
make init    # Tools prüfen und installieren, ohne Docker-Runtime kommt Colima dazu
make up      # erster Build lädt alle Modelle, dauert einige Minuten
open http://localhost:8080
```

Ports und Schwellwerte lassen sich über `.envrc` setzen (Vorlage `.envrc.example`).

Der Laya-Container lädt seinen Checkpoint beim ersten Start in ein Docker-Volume, die App hat
GLiNER2-PII und spaCy bereits im Image. Danach läuft alles ohne Internet (`HF_HUB_OFFLINE=1`).

| Dienst | Port | Inhalt |
|---|---|---|
| `app` | 8080 (nur localhost) | Web-UI, GLiNER2-PII, spaCy, Regex |
| `laya` | 8000 (nur im Compose-Netz) | Laya-Server, multilingualer Checkpoint |

Für Cloud oder On-Premise: beide Images bauen, `app` hinter einen Reverse-Proxy mit TLS und
Authentifizierung legen. Die Anmeldung prüft nur die Zugehörigkeit und gibt keine Identität an die
App weiter (siehe [docs/protokollierung.md](docs/protokollierung.md)). Die App selbst
hat keinen Login. Auf eine VM mit ssh-Zugang deployt
`make deploy DEPLOY_HOST=user@vm`, siehe [docs/deployen.md](docs/deployen.md).

## Hinweise für diese Installation

Beim ersten Aufruf zeigt die App einen kurzen Splash-Screen: was sie macht, die drei Schritte und
was zu beachten ist. Er erscheint wieder, sobald sich sein Inhalt ändert, und lässt sich über
„Hinweise“ in der Fußzeile jederzeit öffnen.

Hinweise, die nur für eine Installation gelten, etwa zu einer Betriebsvereinbarung, gehören nicht
ins Repo, sondern nach `local/hinweise.md` (in `.gitignore`). Der Splash zeigt sie als eigenen
Abschnitt. Die Datei ist Markdown mit Überschriften, Absätzen, Listen, **fett**, *kursiv* und Links
(`http`, `https`, `mailto`); HTML wird als Text angezeigt. Die App liest sie bei jedem Aufruf neu,
ein Neustart ist nicht nötig.

```markdown
## Betriebliche Nutzung

Zur betrieblichen Nutzung bei **Schraubenhuber & Co. KG** beachtet bitte auch die
[Betriebsvereinbarung](https://intranet.example/betriebsvereinbarung).
```

`make deploy` überträgt `local/` nicht und löscht es auf der VM auch nicht. Dort legt man die Datei
einmal selbst ab, z. B. nach `make remote-login`.

## Klassifikation

Fidelius kann einschätzen, welcher Schutzstufe ein Text nach den Regeln der Installation angehört,
und warnen, wenn eine Stufe über der Freigabe liegt. Es sperrt nichts. Die Funktion ist aus, bis
eine Installation sie mit `CLASSIFICATION_ENABLED=1` einschaltet; ausgeschaltet verhält sich
Fidelius wie ohne sie und liest die Regeldatei nicht. Hintergrund:
[docs/specs/klassifikation.md](docs/specs/klassifikation.md) und
[ADR-0001](docs/adr/0001-klassifikation-warnt-je-installation.md).

Die Schutzstufen einer Organisation gehören nicht ins Repo, sondern nach `local/klassifikation.yaml`
(im Container `/opt/local/klassifikation.yaml`, änderbar mit `CLASSIFICATION_FILE`). Als Vorlage
dient [klassifikation.example.yaml](klassifikation.example.yaml) mit vier generischen Stufen:

```bash
mkdir -p local && cp klassifikation.example.yaml local/klassifikation.yaml
```

```yaml
freigegeben_bis: intern   # id der höchsten Stufe, die ohne Warnung durchgeht
schwelle: 0.3             # optional; eine Stufe zählt ab dieser Wahrscheinlichkeit
stufen:                   # von niedrig nach hoch, die Reihenfolge ist die Rangfolge
  - id: oeffentlich
    name: Öffentlich
    laya: Veröffentlichte Information wie Pressemitteilung, Webseite oder Gesetzestext
    text: |
      **Definition:** …
      **KI-Nutzung:** …
  - id: intern
    …
zugangsdaten:             # optional
  text: Passwörter, Tokens und API-Keys dürfen nie in ein KI-System.
```

- `id`, `name`, `laya` und `text` sind je Stufe Pflicht, die `id` muss eindeutig sein. Es braucht
  mindestens zwei Stufen, und auch die unterste definiert die Installation selbst.
- `laya` ist die Kurzbeschreibung, nach der das Modell die Stufe wählt: ein bis zwei Zeilen mit
  konkreten Beispielen. Sie bleibt auf dem Server, `/api/config` liefert sie nicht aus.
- `text` ist Markdown für die Anzeige, etwa Definition und Regel für die KI-Nutzung.
- `zugangsdaten.text` erscheint bei einer Warnung wegen Zugangsdaten; fehlt er, steht dort ein
  generischer Satz.
- `schwelle` bestimmt die Stufe eines Abschnitts von 600 Zeichen: die höchste Stufe mit mindestens
  dieser Wahrscheinlichkeit, sonst die wahrscheinlichste. Der Text bekommt die höchste Stufe über
  alle Abschnitte. Die Fragen dafür laufen im selben Laya-Batch wie das Gate, auch wenn das Gate
  den Text als harmlos einstuft.

Nach der Analyse zeigt die UI die Stufe als Badge über dem Ergebnis, bis `freigegeben_bis` neutral,
darüber in Warnfarbe und mit einem Banner, das den `text` der Stufe zeigt. `/api/analyze` liefert
dazu das Feld `classification` (Format in der Spec, Abschnitt 6); ist Laya nicht erreichbar, steht
dort nur ein Hinweis in `note`.

Die App liest die Datei bei jedem Aufruf neu, eine Änderung wirkt ohne Neustart. Das Flag dagegen
wirkt erst nach einem Neustart des Containers. `/api/health` zeigt im Feld `classification`, woran
man ist:

| Meldung | Bedeutung |
|---|---|
| `aus` | `CLASSIFICATION_ENABLED` ist nicht `1` |
| `aktiv: 4 Stufen` | Flag an, Regeldatei gültig |
| `Fehler: Regeldatei fehlt (…)` | Flag an, aber keine Datei unter dem Pfad |
| `Fehler: Zeile 7: …` | Flag an, Datei ungültig (YAML-Fehler mit Zeile, zu wenige Stufen, doppelte `id`, unbekanntes `freigegeben_bis`) |

Fehlt die Datei oder ist sie ungültig, läuft alles wie bei Flag aus, nur `/api/health` meldet den
Fehler, damit eine vergessene Datei auffällt.

## Bedienung

Die Oberfläche ist für Nutzer ohne technisches Vorwissen gedacht. Ein Klick auf „Wie funktioniert
das?“ klappt eine Erklärung auf; Fehler erscheinen als rote Box, sonst wird nichts angezeigt.

Die drei Schritte stehen untereinander, verbunden durch eine Linie. Der aktive Schritt ist offen
und sagt in seiner Kopfzeile, was als Nächstes zu tun ist. Ein erledigter Schritt klappt zu einer
Zeile mit Zusammenfassung zusammen und lässt sich per Klick wieder aufklappen. Noch nicht
erreichte Schritte zeigen „wartet“.

1. **Text einfügen.** Eingefügter Text wird sofort geprüft, getippter Text nach Klick auf
   „Anonymisieren“ (auch Cmd/Ctrl+Enter). Unter dem Feld lässt sich ein Beispiel wählen; ein Dialog zeigt
   seinen Anfang und fragt, bevor es den Text im Feld ersetzt. Die
   Einschätzung zeigt ein rot-grüner Balken mit Wortstufe („sehr unwahrscheinlich“ bis „sehr
   sicher“). Ab „wahrscheinlich“ wird direkt anonymisiert, und Schritt 2 öffnet sich. Sonst bleibt
   Schritt 1 offen und bietet „Trotzdem anonymisieren“ an.
2. **Prüfen und in die KI kopieren.** „Anonymisierter Text“ mit zwei Reitern: „mit Markierungen“
   (Original durchgestrichen, Platzhalter farbig dahinter) und „so wie er kopiert wird“. Der
   Kopierknopf liefert immer nur den anonymisierten Text. Klick auf eine Stelle öffnet ein Popup:
   Art als farbige Chips wählen oder den Schalter „Wird ersetzt“ auf „Bleibt stehen“ stellen. Die
   Änderung gilt für alle Vorkommen desselben Werts. Darunter die Zuordnungstabelle mit
   Export/Import. Erledigt ist der Schritt, sobald der Kopierknopf erfolgreich kopiert hat oder in
   Schritt 3 eine Antwort steht.
3. **Antwort zurückübersetzen.** KI-Antwort einfügen, „Rückübersetzen“, Ergebnis kopieren. Dieser
   Schritt bleibt auch erledigt offen. „Von vorne beginnen“ leert wie „Leeren“ in Schritt 1 Text,
   Ergebnis, Tabelle und Antwort und springt zurück zu Schritt 1. Wer die Tabelle später noch
   braucht, exportiert sie vorher.

Jede Änderung am Text in Schritt 1 verwirft das alte Ergebnis, die Schritte beginnen dann von vorn.

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
make examples                # alle Beispiele, volle Trefferliste
make examples ARGS="-q 05"   # nur Abgleich, nur Beispiel 05
```

Das Skript zeigt je Mail den Gate-Wert, jeden Treffer mit Quellen und Laya-Urteil und dann
`FEHLT` (zu schwach), `ZU VIEL` (zu stark) und `EXTRA` (ersetzt, aber nicht in der Soll-Liste).
Eigene Texte: als `.txt` nach `examples/` legen, Soll-Treffer in `expected.json` ergänzen.

Unit-Tests ohne Modelle (Regex, Zusammenführen, Platzhalter, Rückübersetzung):

```bash
make test
```

## Lasttest

`make loadtest` misst, wie die App auf gleichzeitige Prüfungen reagiert: eine Treppe von 1 bis 20
gleichzeitigen Prüfungen, bis die Antwortzeiten die Bruchgrenze überschreiten. Methode und
Bewertung stehen in [docs/specs/lasttest.md](docs/specs/lasttest.md), das Ergebnis der Messreihe auf
der Dev-VM in [docs/lasttest.md](docs/lasttest.md).

```bash
make loadtest                        # Dev-VM per SSH-Tunnel, Variablen wie bei make deploy
make loadtest ARGS="--label 16gb"    # Zusatz im Namen des Ergebnisverzeichnisses
make loadtest ARGS="--url http://localhost:8080 --stages 1,2 --min-duration 20 --min-requests 3"
                                     # kurzer Rauchlauf gegen make up
```

Ergebnisse landen in `loadtest-results/` (nicht im Repo), am Ende steht eine Tabelle je Stufe auf
der Konsole.

`make loadtest-report` fasst die Läufe aus `loadtest-results/` als `loadtest-results/bericht.html`
zusammen: Sweet Spot, eine Zeile je Lauf und die Grafiken zu Antwortzeit, Durchsatz, Zeitanteilen,
Klassen, Langtext und CPU/RAM/steal. Die Datei braucht kein Netz und lässt sich weitergeben.

```bash
make loadtest-report                                    # alle Läufe, Ziellast 4
make loadtest-report ARGS="--runs '*-8cpu-*' --target 3"   # Auswahl und andere Ziellast
make loadtest-report ARGS="--request-log requests.jsonl"   # echte Gleichzeitigkeit dazu
```

Das Request-Log kommt über `/api/request-log` von der laufenden App.

## Protokolle und Betriebsvereinbarung

Die App schreibt je Prüfung eine Zeile mit Zahlen und Schaltern ins Request-Log, ohne Text, Treffer
und Netzadresse. uvicorn schreibt kein Access-Log, und die Container-Logs sind auf 3 × 10 MB je
Dienst begrenzt. Warum fidelius damit nicht zur Leistungs- und Verhaltenskontrolle geeignet ist,
steht in [docs/protokollierung.md](docs/protokollierung.md). Änderungen daran, was die
App protokolliert, gelten dort als wesentliche Änderung und gehen vorher an den Betriebsrat.

## Stellschrauben

| Variable | Standard | Wirkung |
|---|---|---|
| `GATE_THRESHOLD` | 0.5 | Laya-Gesamtbewertung, ab der die Erkennung startet |
| `LAYA_REJECT_THRESHOLD` | 0.9 | Laya-Wahrscheinlichkeit „nicht sensibel“, ab der ein Treffer abgelehnt wird |
| `LAYA_RECAT_THRESHOLD` | 0.95 | Sicherheit, ab der Laya einen spaCy-Treffer umkategorisieren darf |
| `GLINER_THRESHOLD` | 0.5 | Mindest-Score für GLiNER2-PII-Treffer |
| `OMP_NUM_THREADS` | 4 | CPU-Threads je Container |
| `MAX_TEXT_CHARS` | 50000 | Höchstlänge eines Textes je Anfrage, längere lehnt die App ab |
| `NOTICE_FILE` | /opt/local/hinweise.md | Pfad im Container für die Hinweise dieser Installation im Splash-Screen; `./local` ist dorthin gemountet |
| `CLASSIFICATION_ENABLED` | 0 | `1` schaltet die Klassifikation an (siehe Klassifikation), wirkt nach Neustart des Containers |
| `CLASSIFICATION_FILE` | /opt/local/klassifikation.yaml | Pfad im Container für die Klassifikationsregeln dieser Installation |
| `REQUEST_LOG` | /var/log/fidelius/requests.jsonl | Pfad im Container für das Request-Log (eine JSON-Zeile je Prüfung, ohne Text); nur unter `/var/log/fidelius` liegt es auf dem Volume `request-log` |

Kategorien, Farben, Label-Zuordnungen und die Laya-Fragen stehen in `app/fidelius/config.py`.

## Bekannte Grenzen

- Laya markiert keine Textstellen, sondern klassifiziert. Es ist deshalb Gate und Bestätiger, nicht
  Finder. Seine Kategorieurteile sind schwankend; deshalb darf es nur sehr sicher ablehnen.
- Wörter, die Ort und Sache zugleich sind („Essen“), werden als Ort erkannt. Per Klick ablehnen.
- Firmennamen mit Nachnamen („Malerbetrieb Lutz“) werden teils als Person erkannt. Für die
  Anonymisierung ist das unschädlich, der Platzhalter ist nur anders benannt.
- Reine Jahreszahlen und Wochentage bleiben stehen, Beträge ebenfalls.
- Laufzeit auf CPU: 5 bis 12 Sekunden je Text, davon der größte Teil die Laya-Bestätigung
  (rund 0,2 s je Treffer). Ohne Bestätigung (Häkchen in der UI) rund 2 bis 5 Sekunden. Wie schnell
  die laufende Maschine ist, misst die App beim Start selbst (Kalibrierung mit drei
  Beispieltexten); Sockel und Rate je Seite stehen im Expertenmodus bei den Laufzeiten. Ist Laya
  beim Start nicht erreichbar, bleibt die Kalibrierung aus.

## Lizenzen der Modelle

Laya (Convai Innovations), GLiNER2-PII (Fastino) und spaCy-Modelle (Explosion) stehen unter
Apache 2.0 bzw. MIT.
