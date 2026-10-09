# KI-Systembeschreibung fidelius: keine Eignung zur Leistungs- und Verhaltenskontrolle

Entwurf, Stand 8.10.2026.

Dieser Abschnitt der KI-Systembeschreibung (KI-Betriebsvereinbarung § 2 Abs. 2) legt dar, warum
fidelius nicht geeignet ist, Leistung oder Verhalten von Beschäftigten zu überwachen, und wie das
abgesichert ist. Die KI-Betriebsvereinbarung macht das in § 3 zur Voraussetzung für die Einstufung
in Kategorie D. Die übrigen Teile der Systembeschreibung (Zweck, Nutzerkreis, Schulung und weitere)
folgen gesondert.

## Was fidelius tut

Wer einen Text mit einem KI-Dienst wie ChatGPT bearbeiten will, fügt ihn zuerst in fidelius ein.
fidelius ersetzt darin Namen, Adressen, Telefonnummern, Kontonummern und ähnliche Angaben durch
Platzhalter wie `[PERSON_1]`. Den so bereinigten Text gibt man an den KI-Dienst. Dessen Antwort
lässt sich danach in fidelius zurückübersetzen: Die Platzhalter werden wieder durch die echten
Angaben ersetzt.

fidelius läuft auf einem eigenen Server. Der eingefügte Text geht an keinen externen Dienst.

## Kurz gesagt

fidelius weiß nicht, wer es benutzt. Es gibt keine Anmeldung und keine Nutzerkennung. Gespeichert
werden weder die Texte noch Angaben, die auf eine Person schließen lassen. Deshalb kann niemand mit
fidelius auswerten, wer wann wie viel oder wie gut gearbeitet hat.

## 1. Was mit dem Text geschieht

- Der Server bearbeitet den eingefügten Text nur für die Dauer der Prüfung, in der Regel wenige
  Sekunden, und verwirft ihn danach. Er speichert ihn nirgends.
- Welche echte Angabe zu welchem Platzhalter gehört, rechnet der Server aus und schickt es an den
  Browser zurück, ohne es zu speichern. Danach liegt diese Zuordnung nur im Browser der Person, die
  fidelius benutzt.
- Die Antwort des KI-Dienstes und ihre Rückübersetzung bleiben im Browser. Der Server bekommt sie
  nicht zu sehen.
- Ob und was jemand danach in einen KI-Dienst einfügt, erfährt fidelius nicht.

## 2. Was gespeichert wird

**Nutzungsprotokoll.** Für jede Prüfung schreibt fidelius eine Zeile mit diesen Angaben:

- Zeitpunkt der Prüfung
- Version der Software
- Länge des Textes in Zeichen
- wie wahrscheinlich der Text personenbezogene Angaben enthält, und ob deshalb ersetzt wurde
- ob die Person die Ersetzung trotz unauffälliger Einschätzung ausgelöst hat
- wie viele Stellen ersetzt wurden
- wie lange die einzelnen Rechenschritte gedauert haben
- ein Fehlerhinweis, falls ein Teil der Software nicht erreichbar war

Nicht darin stehen: der Text, die ersetzten Angaben, die Zuordnung zu den Platzhaltern, eine
Netzadresse, ein Name oder eine andere Kennung der Person.

Das Protokoll dient dem Betrieb: Es zeigt, wie lange Prüfungen dauern, wie stark fidelius genutzt
wird und wo Fehler auftreten. Eine Übersichtsseite fasst es zusammen, etwa als Laufzeiten und als
Zahl der Prüfungen je Tag und je Stunde, immer über alle Nutzenden zusammen.

**Technische Meldungen.** Die Software meldet ihren Start, Warnungen und Fehler. Ein Protokoll der
einzelnen Seitenaufrufe mit Netzadressen schreibt sie nicht. Die Meldungen sind auf 30 MB je Dienst
begrenzt; ältere werden überschrieben.

**Löschfrist.** Geplant ist, das Nutzungsprotokoll nach 14 Tagen zu löschen
([#28](https://github.com/h1f1x/fidelius/issues/28)). Bis das umgesetzt ist, wird es nicht
automatisch gelöscht.

## 3. Warum sich nichts einer Person zuordnen lässt

- **Keine Anmeldung.** fidelius kennt keine Benutzerkonten, vergibt keine Kennung und setzt keine
  Cookies.
- **Keine Netzadresse der Person.** Alle Anfragen kommen über einen vorgeschalteten Zugangsrechner
  (Proxy). fidelius sieht nur dessen Adresse, nicht die des Rechners, an dem jemand arbeitet. Das
  Netz, in dem fidelius läuft, ist vom Firmennetz getrennt.
- **Offener Nutzerkreis.** Wer fidelius nutzt, wird weder begrenzt noch benannt. Bei einem kleinen,
  bekannten Kreis ließe sich aus der Nutzungszeit auf einzelne Personen schließen; deshalb bleibt
  der Kreis offen.
- **Gemessen wird die Maschine.** Die gespeicherten Dauern sind Rechenzeiten des Servers, nicht die
  Arbeitszeit eines Menschen. fidelius misst weder, wie lange jemand auf der Seite bleibt, noch wie
  schnell jemand tippt, noch wie gut ein Ergebnis ist.

## 4. Technische Absicherung

- Der Server schreibt kein Protokoll der Seitenaufrufe, also keine Netzadressen und keine
  Zeitpunkte einzelner Aufrufe neben dem Nutzungsprotokoll.
- Welche Angaben das Nutzungsprotokoll enthält, ist durch einen automatischen Test festgeschrieben.
  Kommt eine Angabe hinzu, schlägt der Test fehl, und die Änderung fällt auf.
- Bevor eine neue Version auf den Server kommt, laufen diese Tests. Aufgespielt wird nur ein
  versionierter, nachvollziehbarer Stand. Eine Ausnahme ist auf der Entwicklungsumgebung nur mit
  einem ausdrücklichen Schalter möglich.
- Technische Meldungen sind in der Größe begrenzt, das Nutzungsprotokoll wird nach 14 Tagen
  gelöscht (geplant, siehe oben).

## 5. Organisatorische Absicherung

- Der Nutzerkreis bleibt offen und unbenannt.
- Jede Änderung daran, was fidelius protokolliert, gilt als wesentliche Änderung nach § 4 Abs. 10
  der KI-Betriebsvereinbarung. Die KI-Arbeitsgruppe wird vorher informiert.
- Zugriff auf den Server haben nur namentlich benannte Administratoren.
- Kommt später eine Anmeldung dazu, prüft sie nur, ob jemand zum GDV gehört. Wer es ist, erfährt
  fidelius nicht, und die Anmeldung protokolliert es nicht
  ([#19](https://github.com/h1f1x/fidelius/issues/19)).

## 6. Welche anderen Systeme beteiligt sind

Zwei weitere Systeme sind beteiligt. Beide betreuen andere Stellen.

- **Der Zugangsrechner (Proxy)** nimmt alle Anfragen aus dem Netz entgegen, verschlüsselt die
  Verbindung und reicht sie an fidelius weiter.
- **Ein Überwachungsdienst** misst die Auslastung des Servers, etwa Rechenleistung, Arbeitsspeicher
  und Plattenplatz. Bei Bedarf kann er die letzten technischen Meldungen von fidelius anzeigen. Diese
  Meldungen enthalten keine Texte und keine Adressen von Nutzenden.

Wer fidelius betreibt, hat auf diese beiden Systeme keinen Zugriff. Deren Daten lassen sich deshalb
nicht mit denen von fidelius zusammenführen.

## Bezug zu den Vereinbarungen

- KI-Betriebsvereinbarung § 3: Kategorie D setzt voraus, dass die fehlende Eignung zur Leistungs-
  und Verhaltenskontrolle dargelegt und abgesichert ist (Abschnitte 3 bis 5).
- KI-Betriebsvereinbarung § 4 Abs. 10: Änderungen am Protokollieren sind wesentliche Änderungen
  (Abschnitt 5).
- IT-Rahmenvereinbarung § 3: Daten ohne Personenbezug sind nicht Gegenstand der Vereinbarung. Das
  Nutzungsprotokoll enthält keine Angaben, die sich einer Person zuordnen lassen (Abschnitte 2 und 3).
- IT-Rahmenvereinbarung § 5 Abs. 1: Personenbezogene Daten von Beschäftigten dürfen nicht zur
  Leistungs- oder Verhaltenskontrolle verwendet werden. fidelius erhebt keine.
- IT-Rahmenvereinbarung § 8: Datenminimierung und Speicherbegrenzung (Abschnitte 2 und 4).

## Offene Punkte

- Die Löschfrist von 14 Tagen für das Nutzungsprotokoll ist noch nicht umgesetzt
  ([#28](https://github.com/h1f1x/fidelius/issues/28)).
- Was ein Anmeldedienst bei einer späteren Anmeldung über die Person protokolliert, steht erst fest,
  wenn klar ist, welcher es wird ([#19](https://github.com/h1f1x/fidelius/issues/19)).
- Die Übersichtsseite und das Nutzungsprotokoll sind heute für alle erreichbar, die fidelius
  erreichen. Ob das so bleibt, wird in [#19](https://github.com/h1f1x/fidelius/issues/19)
  entschieden.
- Die rechtliche Bewertung durch Datenschutz und Betriebsrat steht aus.

## Anhang: technische Belege

Für IT, Informationssicherheit und Datenschutz. Geprüft am 8.10.2026 auf der Entwicklungs-VM
`fidelius-dev`, soweit nicht anders angegeben.

| Aussage | Beleg |
|---|---|
| Nutzungsprotokoll ohne Text, Treffer und Netzadresse | `app/fidelius/pipeline.py`, `_log_entry`; Felder: `zeit`, `build`, `quelle`, `zeichen`, `gate_wert`, `schwelle`, `sensibel`, `trotzdem`, `laya_bestaetigung`, `gate_ms`, `erkennung_ms`, `laya_ms`, `gesamt_ms`, `stellen`, `platzhalter`, `laya_abgelehnt`, `fehler` |
| Feldliste festgeschrieben | `app/tests/test_pipeline.py`, Vergleich mit der vollständigen Feldmenge |
| Kein Protokoll der Seitenaufrufe | `app/Dockerfile`: uvicorn mit `--no-access-log` |
| Technische Meldungen begrenzt | `compose.yaml`: `x-logging`, json-file mit `max-size: 10m`, `max-file: 3` |
| Tests und versionierter Stand vor jedem Deploy | `scripts/deploy.sh`, `docs/deployen.md` |
| fidelius sieht nur die Adresse des Proxys | uvicorn wertet `X-Forwarded-For` nur von `127.0.0.1` aus (Standard von `--forwarded-allow-ips`, auf der VM nicht geändert); im Access-Log vom 8.10. standen nur `127.0.0.1`, die VM selbst und `172.16.40.91` |
| Zuordnung und Rückübersetzung nur im Browser | `app/fidelius/static/app.js`: Zustand in `localStorage`, Rückübersetzung in `deanonymize` |
| Keine Cookies | weder `app/fidelius/main.py` noch `app/fidelius/static/` setzen Cookies |
| Laya speichert keine Texte | im Laya-Container keine neu geschriebenen Dateien außer dem Modell-Cache; Laya loggt nur Aufrufe aus dem App-Container |
| Überwachungsdienst | `beszel-agent` 0.21.0 auf der VM, verbunden mit einem Hub im VM-Netz; kann auf Abruf die letzten 200 Zeilen eines Container-Logs liefern (Beszel `agent/docker.go`, `getLogs`) |
| Netztrennung, kein Zugriff auf Proxy und Überwachungsdienst | Angabe des Betreibers |
