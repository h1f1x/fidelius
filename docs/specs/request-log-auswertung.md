# Spec: Auswertung des Request-Logs

Stand: 2026-10-06, Ergebnis einer Klärungsrunde und eines UI-Prototyps. Alle Punkte sind entschieden, umgesetzt ist noch nichts. Issue: [#12](https://github.com/h1f1x/fidelius/issues/12).

## Ausgangslage

- Seit #10 schreibt fidelius je Prüfung eine JSON-Zeile nach `REQUEST_LOG` (Felder siehe `docs/specs/laufzeit-und-request-log.md`, Abschnitt 4). Die Datei liegt auf dem Volume `request-log`, im Betrieb also auf der VM.
- Das Log enthält nur Zahlen und Schalter, keinen Text und keine Treffer. Eine Auswertung zeigt deshalb nichts Sensibles.
- Bisher lässt sich das Log nur von Hand lesen, per `docker compose exec` auf der VM.
- Das Log wird nicht rotiert. 10.000 Anfragen ergeben ~3 MB, deshalb darf es bei jedem Aufruf ganz gelesen werden.

## 1. Seite und Zugang

- **Route:** `/auswertung` in fidelius, ausgeliefert wie `/` aus `app/fidelius/static/`.
- **Zugang:** ohne Zugriffsschutz. Wer die App erreicht, sieht auch die Auswertung.
- **Auffindbar:** über einen Link im Expertenmodus der Haupt-UI.
- **Kein Log:** Fehlt die Datei oder ist sie leer, zeigt die Seite „Kein Request-Log vorhanden“ mit dem konfigurierten Pfad. Sie liefert keinen 404.

## 2. Backend

- **Modul:** `app/fidelius/auswertung.py`. Es liest das Log, filtert nach Zeitraum und aggregiert. Es kommt ohne Modelle aus und wird über `make test` getestet.
- **Endpunkte:**
  - `GET /api/auswertung?zeitraum=24h|7t|30t|alles` liefert die fertigen Kennzahlen als JSON. Ein unbekannter Zeitraum ergibt einen 400.
  - `GET /api/request-log` liefert die Rohdatei als `application/x-ndjson` zum Download.
- **Zeitzone:** Tage und Stunden werden im Backend nach Europe/Berlin umgerechnet. Das Log bleibt in UTC.
- **Kaputte Zeilen:** werden übersprungen. Ihre Zahl steht in der Antwort und oben auf der Seite.
- **Quelle:** `quelle: kalibrierung` wird von den Anfragen getrennt. Alle Kennzahlen außer dem Abschnitt Kalibrierung beziehen sich nur auf `quelle: anfrage`.
- **Perzentile:** werden nach der Nearest-Rank-Methode berechnet. Eine Phase, die bei einer Anfrage nicht lief (Erkennung und Laya bei harmlosem Text ohne „Trotzdem“), zählt für diese Phase nicht mit.

## 3. Inhalt

- **Kennzahlen oben:**
  - Anfragen
  - Median und p90 der Gesamtzeit
  - Median je 1.000 Zeichen
  - Fehlerquote mit Anzahl
  - Anteil als sensibel erkannt
- **Trend:** Bei 24 h und 7 Tagen steht unter jeder Kennzahl die Abweichung zur gleich langen Vorperiode, rot wenn schlechter, grün wenn besser. Bei „alles“ und wenn die Vorperiode leer ist, steht „kein Vergleich“.
- **Laufzeit:**
  - Histogramm der Gesamtzeit, abgeschnitten bei p99, mit Markierung von Median und p90
  - Phasenanteile am Median als gestapelter Balken
  - Tabelle mit Median, p90 und p99 für Gate, Erkennung, Laya und Gesamt
- **Laufzeit nach Textlänge:**
  - Streudiagramm Zeichen gegen Gesamtzeit, ein Punkt je Anfrage, Farbe = Build
  - Tabelle mit Längenklassen ≤ 1, 1–3, 3–7, 7–15 und > 15 Seiten à 3.300 Zeichen, jeweils Anzahl, Median und p90
- **Nutzung:** Anfragen pro Tag und nach Uhrzeit, beides als Balken.
- **Builds:**
  - Eine Zeile je Build mit Nummer, Commit, Dirty-Kennung und dem Zeitraum, in dem der Build im Log auftaucht.
  - Spalten: Anzahl, Median, p90, Median je 1.000 Zeichen und die Abweichung zum Vorgänger.
  - Verglichen wird **je 1.000 Zeichen**, weil die Texte unterschiedlich lang sind und eine reine Gesamtzeit Builds mit kürzeren Texten bevorzugen würde.
- **Kalibrierung:** Eine Tabelle mit einer Zeile je Build und einer Spalte je Kalibriertext (nach Zeichenzahl), jeweils Median der Gesamtzeit. Gleiche Texte machen Builds direkt vergleichbar.
- **Fehler:**
  - Fehlerhafte Anfragen fließen in die Laufzeit ein, denn ein Fehlschlag ist auch Laufzeit, die ein Nutzer erlebt hat.
  - Zusätzlich gibt es eine Liste, gruppiert nach Fehlertext, mit Anzahl und dem Zeitpunkt, zu dem der Fehler zuletzt auftrat.

## 4. Layout: Kennzahlen-Cockpit

- **Aufbau:**
  - Oben links der Titel, darunter die Zeile mit Zeilenzahl, kaputten Zeilen und dem Link „Rohlog laden“.
  - Oben rechts die Zeitraumwahl 24 h / 7 Tage / 30 Tage / alles. Standard ist 30 Tage.
  - Darunter die Kennzahlen als Kacheln in einer Reihe, die bei schmalem Fenster umbricht.
  - Darunter ein Raster aus Kacheln: Nutzung pro Tag, Nutzung nach Uhrzeit, Histogramm, Phasen, Streudiagramm, Längenklassen, Builds über die volle Breite, Kalibrierung, Fehler.
- **Zeitraum in der URL:** Der Zeitraum steht als `?zeitraum=` in der URL. Die Seite übernimmt nur Werte aus der festen Liste, alles andere fällt auf 30 Tage zurück. Werte aus der URL und aus dem Log gelangen nie ungeprüft bzw. unescaped ins HTML.
- **Diagramme:** selbst gebautes SVG in Vanilla-JS, ohne Bibliothek und ohne CDN, mit `<title>` als Tooltip. Farben kommen aus den Variablen in `style.css`, Dark Mode inklusive.
- **Herkunft:** Ausgewählt aus drei Prototyp-Varianten (A Cockpit, B Bericht, C Explorer). Der Prototyp liegt auf dem Branch `prototype/request-log-auswertung` unter `/prototype/auswertung?variant=A&daten=synthetisch`. Er rechnet im Browser und ist Wegwerf-Code, die Umsetzung schreibt ihn neu.

## Nicht Teil dieser Spec

- Gate-Verhalten im Detail (Verteilung von `gate_wert` um die Schwelle, Quote für „Trotzdem“) und Kennzahlen zur Erkennung (Stellen, Laya-Ablehnungen). Beides lässt sich später als zusätzliche Kacheln ergänzen.
- Filter nach Build. Den Build-Vergleich übernimmt die Tabelle.
- Rotation des Logs, siehe die technische Schuld aus `docs/specs/laufzeit-und-request-log.md`.
