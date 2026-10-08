# Lasttest: Ergebnis

Messreihe vom 07. und 08.10.2026 auf der Dev-VM, Build #21 (`0f629bd`). Methode und Bewertung
stehen in der [Spec](specs/lasttest.md), alle Grafiken im [Bericht](lasttest-bericht.html)
(eine HTML-Datei, öffnet offline). Issues: [#22](https://github.com/h1f1x/fidelius/issues/22),
[#26](https://github.com/h1f1x/fidelius/issues/26).

## Sweet Spot

**16 vCPU mit `OMP_NUM_THREADS=8`.** Das ist die einzige gemessene Größe, die die Ziellast von
4 gleichzeitigen Prüfungen unter der Komfortgrenze hält: p95 9,2 s bei Stufe 4, c* = 8.

**RAM: mindestens 8,5 GiB.** Die höchste RAM-Spitze der VM lag in allen Läufen bei 6,6 bis
6,8 GiB, plus 25 % ergibt 8,5 GiB. Gemessen wurde mit 16 GB; 8 GB liegen knapp darunter.

## Läufe

| Lauf | vCPU | RAM | Threads | c* | Bruchstufe | p95 Stufe 4 | p95 Stufe 10 | Durchsatz | RAM-Spitze |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 8 | 8 GB | 4 | 2 | 12 (p95) | 22,3 s | 52,3 s | 11–13 /min | 6,6 GiB |
| 1 | 8 | 16 GB | 4 | 2 | 16 (p95) | 20,6 s | 52,4 s | 10–14 /min | 6,6 GiB |
| 2 | 4 | 16 GB | 2 | 2 | 8 (p95) | 31,1 s | – | 7–10 /min | 6,6 GiB |
| 3 | 16 | 16 GB | 8 | **8** | 20 (Laya-503) | **9,2 s** | 22,6 s | 26–31 /min | 6,7 GiB |
| 4 | 16 | 16 GB | 4 | 2 | 12 (p95) | 21,0 s | 50,5 s | 11–14 /min | 6,8 GiB |
| Caddy | 16 | 16 GB | 8 | – | – | 10,0 s | – | 31 /min | 5,9 GiB |

Durchsatz in fertigen Prüfungen pro Minute über alle Stufen der Treppe. Der Caddy-Lauf hatte nur
Stufe 4 und zählt nicht für den Sweet Spot.

## Was die Messung zeigt

- **Die Threads entscheiden, nicht die Kerne.** Lauf 4 (16 vCPU, 4 Threads) liegt fast
  deckungsgleich auf Lauf 1 (8 vCPU, 4 Threads). Erst Lauf 3 mit 8 Threads verdoppelt den
  Durchsatz. Die Hypothese aus der Spec ist damit bestätigt.
- **Die Zeit steckt in Laya.** Gate und Laya-Bestätigung machen bei Stufe 4 rund 95 % der
  Serverzeit aus, die Erkennung liegt bei 0,4 bis 0,9 s. Mit 8 statt 4 Threads sinkt das Gate im
  Median von 1,9 s auf 0,9 s.
- **Mehr Gleichzeitigkeit bringt keinen Durchsatz.** In jedem Lauf bleibt der Durchsatz über die
  Treppe flach, p50 wächst linear mit der Stufe. Die Anfragen stehen in Laya hintereinander.
- **RAM begrenzt nicht.** Lauf 1 mit 16 GB unterscheidet sich von Lauf 0 mit 8 GB nur um 1 bis
  3 s. Die Bruchstufe 16 statt 12 ist Rauschen: p95 lag bei Stufe 12 einmal bei 62,0 s, einmal
  bei 59,0 s.
- **Ein langer Text bremst alle anderen.** Ein Nutzer mit dem Langtext (~8.000 Zeichen) hebt das
  p95 der anderen bei c* = 2 auf das Zweieinhalbfache, z. B. in Lauf 0 von 12,4 s auf 32,5 s. In
  Lauf 3 bei c* = 8 steigt es um 40 %, von 18,5 s auf 26,7 s.
- **Ausfälle gab es erst ab Stufe 20.** Bis dahin war jede Anfrage in jedem Lauf ok, ohne
  Container-Neustart oder OOM. Bei Stufe 20 in Lauf 3 wies Laya ab der 17. gleichzeitigen
  Anfrage mit 503 ab, 443 Prüfungen kamen degradiert zurück. In den anderen Läufen griff vorher
  die Zeitgrenze.
- **Caddy kostet nichts Messbares.** Der Rest zwischen Client- und Serverzeit liegt über Caddy
  wie über den Tunnel bei rund 50 ms. p95 10,0 s statt 9,2 s liegt im Rauschen.
- **Worst Case:** Klicken alle 10 Nutzer gleichzeitig, wartet jeder auf 16 vCPU rund 20 s, auf
  8 vCPU rund 50 s.

## Bewusst ausgelassen

- **8 vCPU mit 8 Threads** ist nicht gemessen. Die Regel vCPU/2 rät davon ab, weil sich App und
  Laya die Kerne teilen. Mit 16 vCPU ist die Frage beantwortet, die kleinere Größe wäre nur
  eine Einsparung.
- **Architektur-Hebel** werden kein eigenes Issue. Die Ziellast hält mit c* = 8 doppelte Reserve.
  Mehrere Laya-Instanzen teilen sich dieselben Kerne, und eine Inferenz skaliert schon gut mit
  den Threads. Ein größerer Detektor-Pool trifft nicht den Engpass, die Erkennung braucht unter
  1 s.

## Beobachten

- **Langtext:** Ein langer Text belegt Laya rund 50 s, alle anderen warten dahinter. Ob das im
  Betrieb stört, zeigt das Request-Log: `make loadtest-report ARGS="--request-log …"` rechnet
  die echte Gleichzeitigkeit aus. Erst dann lohnt eine eigene Laya-Instanz für lange Texte.

## Abweichungen von der Spec

- **Zeitfenster:** Nur Lauf 0 lief abends (07.10., 21:56). Die Läufe 1 bis 4 liefen am 08.10.
  ab 10:44, 15:12, 15:54 und 21:05, der Caddy-Lauf um 22:12. Die Dev-VM ist noch nicht bekannt,
  im Request-Log stand seit dem 07.10., 19:10, keine echte Anfrage.
- **Lauf 4 wiederholt:** Der erste Versuch brach bei Stufe 2 mit zwei fehlgeschlagenen Anfragen
  ab (`Server disconnected`). Die App hat zu ihnen nichts geloggt, und bei den Anfragen danach
  lagen Client- und Serverzeit bis zu 21 s auseinander: ein Aussetzer im SSH-Tunnel über den
  Jumphost. Das Verzeichnis
  ist gelöscht, gewertet ist die Wiederholung.
- **Threads auf der VM:** Für die Läufe 2 bis 4 und den Caddy-Lauf hat Claude auf Felix'
  Anweisung `OMP_NUM_THREADS` in der `.env` gesetzt und Compose neu gestartet. Die Spec sah das
  bei Felix.
- **Caddy-Lauf** auf der Sweet-Spot-Größe (16 vCPU, 8 Threads), weil er das spätere Verhalten im
  Betrieb zeigen soll.

## Aufruf

```bash
make loadtest ARGS="--label 16gb"                 # ein Lauf über den SSH-Tunnel
make loadtest ARGS="--url https://… --vm --stages 4 --no-longtext --label caddy"
make loadtest-report                              # loadtest-results/bericht.html
```

Der Lauf hängt am Rechner, der ihn startet, und an dessen SSH-Tunnel. Für einen langen Lauf, der
ohne offenes Terminal weiterläuft:

```bash
nohup caffeinate -i make loadtest ARGS="--label …" > loadtest-results/lauf.log 2>&1 &
```
