# Spec: Textgrenze, Fortschrittsbalken und Request-Log

Stand: 2026-10-06, Ergebnis einer Klärungsrunde. Alle Punkte sind entschieden, umgesetzt ist noch nichts.

## Ausgangslage

- Die Textgrenze steht als `MAX_TEXT_CHARS = 50000` in `app/fidelius/config.py` und lässt sich per Env überschreiben. Ein zu langer Text bekommt einen 413 mit Zeichenzahl. Die UI nennt die Grenze vorher nirgends.
- Während der Prüfung zeigt die UI „Prüfe … X s“, danach „Geprüft in X s“ (`app/fidelius/static/app.js`). Wie lange es ungefähr dauern wird, erfährt man nicht.
- Die Dauer ist nicht rein linear in der Zeichenzahl:
  - Das Gate teilt den Text in Abschnitte zu 600 Zeichen, seine Dauer wächst also linear.
  - Die Laya-Bestätigung wächst mit der Zahl der Treffer (Batches zu 64).
  - Stuft das Gate einen Text als harmlos ein, entfallen Erkennung und Bestätigung.
- Die Beispiele in `examples/` sind kurz, 517 bis 1.398 Zeichen.
- `docker compose up --build` legt bei jedem Deploy den App-Container neu an.

## 1. Textgrenze als Seitenzahl

- Die Grenze heißt in der UI „etwa 15 Seiten“. Gerechnet wird mit ~3.300 Zeichen pro A4-Seite Fließtext, weil das die Seite ist, die Leute aus Word kennen.
- Das Frontend rechnet die Seitenzahl aus `MAX_TEXT_CHARS` aus. `/api/config` liefert dafür den Wert mit, damit die Angabe auch nach einer Änderung der Env-Variable stimmt.
- Die Grenze steht an drei Stellen:
  - in der Infobox „Wie funktioniert das?“
  - im Hinweis über dem Textfeld
  - in der Fehlermeldung beim 413, dort in Seiten statt in Zeichen

## 2. Kalibrierung der Laufzeitschätzung

- **Zeitpunkt:** beim Start der App, in einem Hintergrund-Thread nach dem Modell-Warmup.
- **Ablage:** nur im Speicher. Sie gilt damit für diesen Lauf des Dienstes. Ein Deploy oder ein Neustart misst neu, und jede Änderung an App oder Laya zieht automatisch eine neue Messung nach sich.
- **Ablauf:**
  1. Ein Aufwärmlauf, dessen Ergebnis verworfen wird, weil der erste Modellaufruf immer langsamer ist.
  2. Drei Messläufe, alle mit `force=true`, damit die volle Pipeline gemessen wird:
     - `04_terminabsprache_harmlos` (517 Zeichen)
     - `06_mailkette_varianten` (1.398 Zeichen)
     - alle acht Beispiele aneinandergehängt (~8.000 Zeichen), damit die Hochrechnung auf lange Texte nicht nur auf kurzen Messpunkten steht
- **Modell:** Sockel + Rate pro Zeichen, angepasst über die kleinsten Quadrate an die drei Messpunkte. Daraus folgt `geschätzte Dauer = Sockel + Rate × Zeichenzahl`.
- **Schnittstelle:** `/api/config` liefert Sockel, Rate und Zeitpunkt der Messung. Solange die Messung nicht fertig ist, stehen dort `null`-Werte.
- **Expertenmodus:** Bei den Laufzeiten steht die Kalibrierung, etwa „Schätzung: 1,2 s Sockel + 0,4 s pro Seite, gemessen beim Start um 09:14“. Liegt die Schätzung daneben, sieht man so sofort, woran es liegt.

## 3. Fortschrittsbalken

- Er läuft von 0 bis zur geschätzten Dauer.
- Daneben steht „Prüfe … 4 s von ca. 7 s“. Einen Countdown („noch 3 s“) gibt es bewusst nicht, weil ein falscher Countdown mehr ärgert als eine ehrliche Angabe von Ist und Schätzung.
- Wird die Schätzung überschritten, bleibt der Balken bei ~95 % stehen. Der Text wird zu „Prüfe … 9 s von ca. 7 s, dauert länger als geschätzt“.
- Ist die Prüfung früher fertig (etwa weil das Gate den Text als harmlos einstuft), springt der Balken auf 100 %.
- Solange es keine Kalibrierung gibt, zeigt die UI die heutige Sekundenanzeige ohne Balken.

## 4. Request-Log

- **Zweck:** spätere Auswertung, also wie lang die Texte sind, wie oft das Gate anschlägt und wie lange es dauert.
- **Was geloggt wird:** nur `/api/analyze`. Korrekturen über `/api/apply` sind Handarbeit und sagen nichts über Dauer oder Erkennung.
- **Kalibrierläufe:** Die Läufe beim Start, auch der Aufwärmlauf, kommen mit ins Log und tragen `"quelle": "kalibrierung"`, echte Anfragen tragen `"quelle": "anfrage"`. So ist pro Build-Stand nachvollziehbar, wie schnell Modell und Maschine waren, und die Auswertung kann die Läufe herausfiltern.
- **Format:** JSONL, ein JSON-Objekt pro Anfrage.
- **Felder:**
  - Zeitstempel, Build-Stand, Quelle (`anfrage` oder `kalibrierung`)
  - Zeichenzahl
  - Sensitivität:
    - Gate-Wert von Laya
    - eingestellte Schwelle
    - Ergebnis sensibel ja/nein
    - „Trotzdem anonymisieren“ ja/nein
    - Laya-Bestätigung an/aus
  - Dauer je Phase in ms: Gate, Erkennung, Laya-Bestätigung, gesamt
  - Ersetzungen:
    - Zahl der ersetzten Stellen
    - Zahl der verschiedenen Platzhalter
    - Zahl der Treffer, die Laya abgelehnt hat
  - Fehlerhinweis, falls Laya nicht erreichbar war
- **Was nie hineinkommt:** Text, Trefferwerte, Platzhaltertabelle, IP-Adresse. Das hält das Versprechen der Infobox, dass der Text nirgends hingeht.
- **Ablage:** `/var/log/fidelius/requests.jsonl` auf einem benannten Volume. Die Datei überdauert so Deploys, `docker logs` würde das nicht.
- **Aufbewahrung:** unbegrenzt, ohne Rotation. Ein Eintrag hat ~300 Byte, 10.000 Anfragen ergeben also ~3 MB.

## Tickets nach der Umsetzung

Beide gehen als GitHub Issues an `h1f1x/fidelius`:

- **Feature-Wunsch:** Die Laufzeitschätzung lernt aus dem Request-Log nach, statt nur aus der Kalibrierung beim Start.
- **Technische Schuld:** Rotation des Request-Logs, damit die Datei bei breiter Nutzung nicht unbegrenzt wächst.
