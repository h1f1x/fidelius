# Spec: Lasttest und VM-Größe

Stand: 2026-10-07, Ergebnis einer Klärungsrunde. Alle Punkte sind entschieden, umgesetzt ist noch nichts. Issue: [#22](https://github.com/h1f1x/fidelius/issues/22).

## Ziel

- Wissen, was passiert, wenn rund 10 Leute fidelius gleichzeitig nutzen.
- Die Last finden, ab der die Antwortzeiten inakzeptabel werden oder die VM nicht mehr reagiert.
- Das auf mehreren VM-Größen messen und die kleinste finden, die die Ziellast unter der Komfortgrenze schafft (Sweet Spot).

## Ausgangslage

- **Eine Prüfung ist ein `POST /api/analyze`.** Gate, Erkennung, Laya-Bestätigung und Platzhalter laufen in diesem einen synchronen Request (`app/fidelius/pipeline.py`). Der Fortschrittsbalken rechnet nur im Browser, die UI setzt kein Timeout auf den Request. Die Rückübersetzung läuft ganz im Browser und belastet den Server nicht.
- **App:**
  - Ein uvicorn-Prozess ohne `--workers`. Die Endpunkte sind `def` und laufen im Threadpool von Starlette (40 Threads).
  - Eine globale `Pipeline` mit einem Detektor-Pool aus 3 Threads, den sich alle gleichzeitigen Anfragen teilen.
  - Die Laya-Aufrufe einer Anfrage laufen nacheinander, mit 120 s Timeout und ohne Retries.
- **Laya** (`laya[serve]==0.3.22`):
  - Ein Prozess mit genau einem Inferenz-Thread, dazu ein Lock um jede Inferenz. Anfragen laufen strikt nacheinander.
  - Ab der 17. gleichzeitigen Anfrage antwortet Laya sofort mit 503 (`LAYA_MAX_CONCURRENT`, Standard 16).
- **Threads:** Beide Container laufen mit `OMP_NUM_THREADS=4`, Laya übernimmt den Wert als `LAYA_THREADS`.
- **Fehlerverhalten:** Bei einem 503 oder Timeout von Laya antwortet die App trotzdem mit 200, dann aber ohne Gate oder ohne Bestätigung. Der Hinweis steht in `gate.note` und im Log-Feld `fehler`.
- **Kalibrierung:** Nach jedem Start misst die App rund 45 s lang. Danach liefert `/api/config` Sockel und Rate, eine Einzelbetriebs-Messung der laufenden Maschine.
- **Request-Log:** `quelle` ist immer `anfrage`, außer bei der Kalibrierung. Lasttest-Anfragen sind heute nicht unterscheidbar. `log_report.py` filtert nur `kalibrierung` heraus.
- **Dev-VM:** die einzige VM, hinter Caddy mit TLS, ohne Auth (#19).
  - 8 vCPU (AMD EPYC 9454, KVM), 7,76 GiB RAM.
  - Im Leerlauf belegt die App 4,0 GiB und Laya 1,8 GiB, rund 2 GiB sind frei.
  - In der `.env` steht nur `APP_BIND`, `OMP_NUM_THREADS` ist also 4.
  - Ein `beszel-agent` läuft mit.
- **Speicher bei langen Texten:** Laut #9 dauerte ein Text mit 50.000 Zeichen und `force` 206 s. Die Spitzen lagen bei 3,2 GB (App) und 3,6 GB (Laya).

## Hypothese

App und Laya arbeiten im Kern nacheinander. Mehr gleichzeitige Prüfungen verlängern die Warteschlange, erhöhen aber nicht den Durchsatz. Erwartet wird:

- Die Komfortgrenze liegt schon bei 2 bis 3 gleichzeitigen Prüfungen.
- Mehr vCPUs helfen nur, wenn die Threads mitwachsen.
- Ab Stufe 17 meldet Laya 503, die Anfragen werden degradiert.

Der Test soll das bestätigen oder widerlegen.

## 1. Lastmodell

- **Messachse:** gleichzeitige Prüfungen, nicht Nutzer. Jeder virtuelle Nutzer schickt die nächste Prüfung, sobald die vorige zurück ist, ohne Denkpause. Stufe 6 heißt also 6 Prüfungen gleichzeitig.
- **Treppe:** 1, 2, 4, 6, 8, 10, 12, 16, 20.
- **Stufe:**
  - Sie läuft, bis mindestens 30 Prüfungen fertig und mindestens 3 Minuten um sind.
  - Die erste Prüfung je virtuellem Nutzer zählt nicht mit, weil sie aufwärmt.
  - Zwischen zwei Stufen laufen alle offenen Anfragen leer, damit keine Wartezeit in die nächste Stufe überschwappt.
  - Nach einer fehlgeschlagenen Anfrage wartet der Nutzer 1 s. Ist die App weg, kommt der Fehler sofort zurück; ohne Pause liefen Tausende Anfragen ins Leere.
- **Abbruch:** nach der ersten Stufe jenseits der Bruchgrenze.
- **Texte:** die acht Beispiele aus `examples/` in fester Reihenfolge je virtuellem Nutzer (Seed). So macht jeder Lauf auf jeder Größe dieselbe Arbeit.
- **Body:** wie in der UI, also `text`, `gate_threshold` aus `/api/config`, `force: false`, `use_laya_check: true`. Das harmlose Beispiel 04 endet am Gate, wie im echten Betrieb.
- **Langtext:**
  - Nach der Treppe wiederholt das Skript die Stufe c* (Komfortgrenze, siehe 2).
  - Einer der c* virtuellen Nutzer schickt dabei statt der Mischung alle Beispiele aneinandergehängt (~8.000 Zeichen, derselbe Text wie in der Kalibrierung).
  - Gemessen wird das p95 der anderen, verglichen mit dem p95 aller Nutzer derselben Stufe aus der Treppe.
  - Bei c* < 2 entfällt die Wiederholung, weil es neben dem Langtext-Nutzer keine anderen gäbe.
- **Lauf über Caddy:** einmal am Ende der Messreihe, bei der Ziellast und eine Stufe lang. Er zeigt, ob der Proxy früher abbricht als die App.

## 2. Bewertung

- **Klassen je Anfrage:**
  - **ok:** HTTP 200, `gate.note` leer
  - **degradiert:** HTTP 200, `gate.note` gesetzt (Laya mit 503 oder Timeout, Gate oder Bestätigung übersprungen)
  - **fehlgeschlagen:** ein anderer Status, ein Verbindungsfehler oder der Client-Timeout von 180 s. Er liegt über den 120 s, die die App auf Laya wartet, damit wir sehen, was die App selbst tut.
- **Kennzahlen je Stufe:**
  - Client-Zeit: p50, p95, Maximum
  - Durchsatz in fertigen Prüfungen pro Minute; fertig sind ok und degradiert
  - Anteil jeder Klasse
  - Mediane der Server-Phasen aus `timing` (`gate_ms`, `detect_ms`, `laya_check_ms`). Eine Phase, die bei einer Prüfung nicht lief (Wert 0), zählt für diese Phase nicht mit, wie in `/auswertung`.
  - Rest = Client-Zeit minus `total_ms`
- **Perzentile:** Nearest-Rank wie in `/auswertung`, über alle gezählten Anfragen der Stufe. Fehlgeschlagene gehen mit ihrer gemessenen Zeit ein.
- **Komfortgrenze:** p95 ≤ 20 s, rund das Doppelte des schlechtesten Einzelwerts. c* ist die höchste Stufe, die die Komfortgrenze hält und keine Bruchbedingung erfüllt.
- **Bruchgrenze:** die erste Stufe mit einer dieser Bedingungen:
  - eine degradierte oder fehlgeschlagene Anfrage, auch beim Aufwärmen
  - ein Neustart oder OOM-Kill eines Containers, erkannt an `RestartCount`, `OOMKilled`, `StartedAt` oder einer neuen Container-ID
  - p95 > 60 s
- **Ziellast:** 4 gleichzeitige Prüfungen.
  - 10 aktive Nutzer mit je einer Prüfung alle 2 Minuten erzeugen bei 10 s je Prüfung im Mittel 0,8 gleichzeitige Prüfungen. Nach Poisson sind es in 99 % der Zeit höchstens 3, die vierte gibt Luft.
  - Im Bericht ist die Ziellast ein Parameter.
  - Stufe 10 bleibt als Worst-Case-Zahl im Bericht: Was passiert, wenn alle 10 im selben Moment klicken?
- **Sweet Spot:** die kleinste Größe (erst vCPU, dann RAM) mit c* ≥ Ziellast. Es zählen nur Läufe über den SSH-Tunnel; der Lauf über Caddy und Läufe ohne VM nicht. Der Bericht nennt sie mit Grund.
- **Echte Nutzung:** Der Bericht kann ein Request-Log einlesen (Download über `/api/request-log`). Aus den Einträgen mit `quelle: anfrage` rechnet er je Prüfung das Intervall [`zeit` − `gesamt_ms`, `zeit`] und daraus, wie viele Prüfungen gleichzeitig liefen: Maximum und p99. So lässt sich die Annahme hinter der Ziellast prüfen.

## 3. Messmatrix

| Lauf | vCPU | RAM | Threads | Zweck |
|---|---|---|---|---|
| 0 | 8 | 8 GB | 4 | Ist-Zustand, unverändert |
| 1 | 8 | 16 GB | 4 | prüft gegen Lauf 0, ob RAM ohne OOM etwas ändert |
| 2 | 4 | 16 GB | 2 | |
| 3 | 16 | 16 GB | 8 | |
| 4 | 16 | 16 GB | 4 | zeigt, was mitwachsende Threads bringen |

- **Threads:** `OMP_NUM_THREADS` in der `.env` auf der VM. Der Wert gilt für beide Container. Regel: vCPU/2, weil sich beide Container die CPUs teilen. Lauf 4 bricht die Regel absichtlich.
- **RAM:** Variiert wird nur die CPU. Der empfohlene RAM ist die höchste RAM-Spitze der VM (MemTotal − MemAvailable) über alle Läufe plus 25 %.
- **Steal-Zeit:** Die VM teilt sich den Host mit anderen. Damit ein Lauf erkennbar wird, den Nachbarn verfälscht haben, zeichnet der Sampler die steal-Zeit auf.
- **Zeitfenster:** abends, wenn niemand die Dev-VM nutzt. Echte Anfragen während eines Laufs würden lange warten und die Messung verfälschen.

## 4. Kennzeichnung im Request-Log

- **Header:** `X-Fidelius-Quelle: lasttest` an `/api/analyze` führt zu `quelle: "lasttest"` im Request-Log.
  - Andere Werte des Headers ignoriert die App.
  - Ohne Header bleibt es bei `anfrage`.
  - Die API-Antwort ändert sich nicht.
- **Auswertung:** `/api/report` zählt nur noch `quelle: anfrage` als Anfrage. Heute filtert es nur `kalibrierung` heraus. Der Abschnitt Kalibrierung bleibt, wie er ist.
- **Test-first:** Tests in `app/tests/`, lauffähig über `make test`.
- **Specs nachziehen:** `docs/specs/laufzeit-und-request-log.md` (Abschnitt 4, Quelle) und `docs/specs/request-log-auswertung.md` (Abschnitt 2, Quelle).

## 5. Lastskript

- **Ort:** `scripts/loadtest.py` mit PEP-723-Header (httpx), gestartet über `uv run` wie `run_examples.py`. Make-Ziele: `make loadtest` und `make loadtest-report`, Parameter über `ARGS`.
- **Zugang:**
  - Ohne `--url` öffnet das Skript selbst einen SSH-Tunnel auf `DEPLOY_BIND:8080`. Es nutzt dieselben Variablen wie `make deploy` und `make remote-login` (`DEPLOY_HOST`, `DEPLOY_JUMP`, `DEPLOY_BIND`).
  - Fehlt `DEPLOY_BIND`, nimmt es `APP_BIND` und `APP_PORT` aus der `.env` auf der VM, sonst `127.0.0.1:8080`. Aus `0.0.0.0` wird `127.0.0.1`.
  - Mit `--url` gibt es keinen Tunnel. Das dient für den Rauchlauf gegen `make up` und für den Lauf über Caddy.
  - Mit `--url` liest das Skript die VM nur mit, wenn `--vm` gesetzt ist.
- **Vor dem Start:**
  - `/api/health` prüfen und warten, bis `/api/config` eine Kalibrierung liefert (höchstens 5 Minuten).
  - Per ssh auf der VM lesen: `nproc`, MemTotal, `OMP_NUM_THREADS` aus der `.env` (Standard 4) und `RestartCount` sowie `OOMKilled` je Container aus `docker inspect`.
  - Weichen die Threads von vCPU/2 ab, warnt das Skript, bricht aber nicht ab.
- **Während des Laufs:** Alle 2 s schreibt der Sampler `docker stats` (CPU und RAM je Container), CPU-Anteile der VM inklusive steal und MemAvailable.
- **Nach jeder Stufe und nach dem Lauf:** `docker inspect` noch einmal lesen. Ein höherer `RestartCount`, ein neues `OOMKilled`, ein anderes `StartedAt` oder eine andere Container-ID zählen als Bruch der Stufe.
- **Auf der VM nur lesen:** Konfiguration und Neustart bleiben bei Felix (`make remote-login`, `make deploy`). Ein Lasttest ändert die Instanz nie unbemerkt.
- **Anfragen:** tragen den Header `X-Fidelius-Quelle: lasttest`.
- **Keine Auth:** Das Skript unterstützt keine Anmeldung. Kommt mit #19 Auth vor den Proxy, wird sie ergänzt.
- **Ablage:** `loadtest-results/<YYYY-MM-DD-HHMM>-<vcpu>cpu-<threads>t[-<label>]/`, ohne VM `…-ohne-vm[-<label>]/`. Gibt es den Namen schon, hängt das Skript `-2`, `-3` … an. Das Verzeichnis `loadtest-results/` steht in `.gitignore`.
  - `requests.jsonl`, eine Zeile je Anfrage: Stufe, Nutzer, Beispiel, Zeichen, Startzeit, Client-ms, HTTP-Status, Klasse, `timing`, `gate.note`, Fehlertext
  - `samples.jsonl`: die Messwerte des Samplers
  - `run.json`: Zeit, Zugang, vCPU, RAM, Threads, Build, Kalibrierung, Parameter, `docker inspect` vorher und nachher
- **Konsole:** am Ende eine Tabelle je Stufe mit p50, p95, Durchsatz und Klassen, dazu c* und die Bruchstufe.

## 6. Bericht

- **Erzeugung:** `make loadtest-report` liest die Läufe aus `loadtest-results/` und schreibt `loadtest-results/bericht.html`.
  - Optionen: Ziellast (Standard 4), Request-Log für die echte Nutzung, Auswahl der Läufe, Ablage der Läufe (`--results`).
- **Form:** eine einzelne HTML-Datei ohne Abhängigkeiten und ohne CDN. Die Grafiken sind Inline-SVG im Stil von `/auswertung`. Sie öffnet offline und lässt sich als Datei weitergeben.
- **Inhalt, von oben nach unten:**
  1. **Kopf:** der Sweet Spot in einem Satz, darunter eine Tabelle mit einer Zeile je Lauf: vCPU, RAM, Threads, c*, Bruchstufe, Durchsatz bei c*, p95 bei Stufe 10, RAM-Spitze. Dazu die echte Nutzung, falls ein Request-Log angegeben ist.
  2. **Antwortzeit je Stufe:** p50 und p95, eine Linie je Lauf, waagerechte Linien bei 20 s und 60 s. Das ist die Hauptgrafik.
  3. **Durchsatz je Stufe** in Prüfungen pro Minute, eine Linie je Lauf
  4. **Wo die Zeit hingeht:** Gate, Erkennung, Laya und Rest, gestapelt je Stufe und Lauf
  5. **Klassen je Stufe:** ok, degradiert, fehlgeschlagen
  6. **Langtext:** p95 der anderen mit und ohne Langtext, je Lauf
  7. **CPU, RAM und steal über die Zeit**, je Container und Lauf, mit den Stufengrenzen als senkrechte Linien
- **Ins Repo:**
  - Nach dem letzten Lauf die finale Fassung als `docs/lasttest-bericht.html`.
  - Daneben `docs/lasttest.md` mit Methode, Aufruf und dem Sweet Spot in Textform, mit Verweis auf den Bericht.

## 7. Tests

- **Unit-Tests ohne Netz** für die reine Auswertungslogik:
  - Klassifizierung
  - Perzentile und Kennzahlen je Stufe
  - c*, Bruchstufe, Sweet Spot
  - Gleichzeitigkeit aus dem Request-Log

  Sie laufen über `make test` mit.
- **Keine Unit-Tests** für die Lastschleife selbst. Ein Rauchlauf gegen die lokale App (`make up`, Stufen 1 und 2) zeigt, dass sie läuft.

## 8. Ablauf der Messreihe

1. Abends, wenn niemand die Dev-VM nutzt, Lauf 0 auf dem unveränderten Stand.
2. Für jeden weiteren Lauf aus Abschnitt 3:
   - VM-Größe anpassen
   - `OMP_NUM_THREADS` in der `.env` setzen
   - Compose neu starten
   - `make loadtest ARGS="--label …"`
3. Lauf über Caddy bei der Ziellast.
4. `make loadtest-report`, dann `docs/lasttest.md` schreiben und `docs/lasttest-bericht.html` committen.

## Nicht Teil dieses Tests

- **Architektur-Hebel:** mehrere uvicorn-Worker, ein größerer Detektor-Pool, mehrere Laya-Instanzen, ein anderes `LAYA_MAX_CONCURRENT`. Zeigt der Test ein Plateau, wird daraus ein eigenes Issue.
- **Szenario ohne Laya-Bestätigung:** Das wäre ein Produkt-Hebel, kein Größenthema.
- **Eigene RAM-Reihe:** siehe Abschnitt 3.
- **Auth im Skript:** siehe Abschnitt 5.

## Umsetzung in Tickets

Als Sub-Issues von #22:

1. **Kennzeichnung im Request-Log** (Abschnitt 4), `ready-for-agent`.
2. **Lastskript mit Auswertungslogik und Tests** (Abschnitte 1, 2, 5, 7), `ready-for-agent`, blockiert durch 1. Ohne Kennzeichnung würde schon der erste Lauf auf der Dev-VM die Auswertung verfälschen.
3. **HTML-Bericht** (Abschnitt 6), `ready-for-agent`, blockiert durch 2, weil er dessen Datenformat liest.
4. **Messreihe** (Abschnitte 3 und 8) mit `docs/lasttest.md` und dem finalen Bericht, `ready-for-human`, blockiert durch 1 bis 3. Sie braucht die VM-Anpassungen.
