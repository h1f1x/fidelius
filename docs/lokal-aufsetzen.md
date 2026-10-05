# Lokal aufsetzen

Die App läuft als zwei Docker-Container (`app` und `laya`). Gebraucht werden eine Docker-Runtime
mit Compose v2, rund 8 GB RAM für Docker, 10 GB freier Platz, `make` und für die Tests `uv`.
`make init` prüft das alles und installiert, was fehlt.

```bash
make init   # Tools prüfen und installieren, Runtime starten
make up     # bauen und starten, kommt zurück, wenn beide Container bereit sind
make test   # Unit-Tests
make        # alle Targets
```

Der erste `make up` dauert einige Minuten: Die Images laden PyTorch, GLiNER2-PII und spaCy, Laya
lädt seinen Checkpoint beim ersten Start in ein Docker-Volume. Danach läuft alles ohne Internet.

## macOS

Voraussetzung: [Homebrew](https://brew.sh) und Git (kommt mit den Xcode Command Line Tools, die
macOS beim ersten `git`-Aufruf anbietet).

```bash
git clone https://github.com/h1f1x/fidelius.git
cd fidelius
make init
make up
open http://localhost:8080
```

Was `make init` auf dem Mac macht:

- **Läuft schon eine Docker-Runtime** (Docker Desktop, OrbStack, Colima), wird sie genommen.
- **Ist Docker Desktop oder OrbStack installiert, aber gestoppt**, bricht `init` ab und bittet
  darum, sie zu starten. Es installiert dann nicht zusätzlich Colima.
- **Ist Colima installiert, aber gestoppt**, startet es Colima mit dessen gespeicherten Werten und
  legt den Docker-Kontext `colima` neu an, falls er fehlt (`colima stop` löscht ihn).
- **Ist keine Runtime da**, installiert es `colima`, `docker` und `docker-compose` per Homebrew und
  legt Colima mit 4 CPUs, 8 GB RAM und 40 GB Platte an. Andere Werte beim ersten Mal:
  `make init COLIMA_MEMORY=12 COLIMA_CPU=6`. Später ändern: `colima stop && colima start --memory 12`,
  Colima merkt sich den Wert.
- Es verlinkt `docker-compose` als CLI-Plugin, damit `docker compose` funktioniert.
- Es installiert `uv` und warnt, wenn Docker weniger als 7 GB RAM hat.

Colima startet nach einem Neustart des Macs nicht von selbst. `make up` startet es bei Bedarf mit.
Wer es dauerhaft im Hintergrund haben will: `brew services start colima`.

## Windows (WSL2)

Unter Windows läuft alles in WSL2, einem Linux im Windows. Ohne WSL2 gibt es auf Windows keine
Docker-Runtime, auch Docker Desktop, Rancher Desktop und Podman setzen darauf auf. Das Makefile
läuft in WSL genauso wie auf Linux; in PowerShell oder Git Bash läuft es nicht.

### 1. WSL2 prüfen

In PowerShell:

```powershell
wsl --list --verbose
```

Steht dort eine Ubuntu-Distribution mit `VERSION 2`, weiter bei Schritt 2. Kommt eine Fehlermeldung
oder die Liste ist leer, braucht es auf einem verwalteten Rechner meist die IT. Textbaustein für das
Ticket:

> Bitte WSL2 mit der Distribution Ubuntu 24.04 freigeben bzw. installieren
> (`wsl --install -d Ubuntu-24.04`, benötigt die Windows-Features „Windows-Subsystem für Linux“ und
> „VM-Plattform“). Zweck: lokale Docker-Container für eine Anonymisierungs-App, Daten verlassen den
> Rechner nicht.

### 2. WSL mehr Speicher geben

WSL bekommt standardmäßig die Hälfte des RAMs. Bei 16 GB ist das knapp. Datei
`%UserProfile%\.wslconfig` anlegen oder ergänzen:

```ini
[wsl2]
memory=10GB
processors=4
```

Danach in PowerShell `wsl --shutdown`, dann Ubuntu wieder öffnen.

### 3. Repo in WSL holen und starten

Im Ubuntu-Terminal:

```bash
sudo apt-get update && sudo apt-get install -y make git curl
git clone https://github.com/h1f1x/fidelius.git ~/fidelius
cd ~/fidelius
make init
```

Das Repo gehört ins Linux-Dateisystem (`~/…`), nicht nach `/mnt/c/…`. Dort ist Docker deutlich
langsamer, und Git auf Windows-Seite kann die Zeilenenden auf CRLF umstellen.

`make init` installiert unter WSL Docker Engine aus apt (`docker.io`, `docker-compose-v2`,
`docker-buildx`) und `uv`. Zweimal hält es dabei bewusst an:

- Nach der Installation von `uv`: Terminal schließen, neu öffnen, `make init` wiederholen.
- Nach der Aufnahme in die Gruppe `docker`: ebenso. Hilft das nicht, in PowerShell `wsl --shutdown`.

Dann:

```bash
make up
```

Die Web-UI ist im Windows-Browser unter <http://localhost:8080> erreichbar.

### Variante: Docker Desktop ist schon da

Ist Docker Desktop installiert und lizenziert, unter *Settings → Resources → WSL Integration* die
Ubuntu-Distribution einschalten. `make init` findet die laufende Runtime dann über `docker info`
und installiert keine zweite. Den Speicher regelt in diesem Fall *Settings → Resources*.

## Targets

| Target | Wirkung |
|---|---|
| `make init` | Tools prüfen, fehlende installieren, Runtime starten, RAM prüfen |
| `make up` | `docker compose up --build -d --wait`, kommt zurück, wenn beide Container healthy sind |
| `make down` | Container stoppen; das Laya-Modell bleibt im Volume |
| `make logs` | Logs beider Container verfolgen |
| `make status` | `docker compose ps` |
| `make test` | Unit-Tests ohne Modelle, in einer temporären Umgebung über `uv` |
| `make examples` | Beispielmails gegen die laufende App, Argumente über `ARGS="-q 05"` |

Ports und Schwellwerte kommen aus `.envrc` (Vorlage `.envrc.example`), wenn sie in der Shell
geladen ist, etwa über direnv. Sonst gelten die Defaults aus `compose.yaml`.

## Wenn etwas hakt

| Symptom | Ursache und Abhilfe |
|---|---|
| `make up` wartet sehr lange auf `laya` | Erster Start lädt den Checkpoint. `make logs` zeigt den Fortschritt. Das Zeitlimit ist 30 Minuten (`WAIT_TIMEOUT`). |
| Laya startet neu oder wird nie healthy | Zu wenig RAM. `make init` zeigt den Docker-RAM und die Abhilfe je Runtime. |
| Build bricht mit `CERTIFICATE_VERIFY_FAILED` oder `SSL` ab | Firmen-Proxy mit TLS-Inspektion. Die Container kennen das Firmen-Zertifikat nicht. Den ersten Build außerhalb des Proxys machen (anderes Netz, ohne VPN), danach braucht es kein Internet mehr. Dauerhafte Lösung: Zertifikat von der IT. |
| `docker compose` unbekannt | `make init` erneut ausführen, es legt das Plugin an. |
| `permission denied … docker.sock` (WSL) | Gruppe `docker` noch nicht aktiv. Terminal neu öffnen oder `wsl --shutdown`. |
| Port 8080 belegt | `APP_PORT=8081 make up` |
