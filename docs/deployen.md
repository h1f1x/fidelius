# Auf eine VM deployen

Der lokale Arbeitsstand geht per rsync auf die VM, dort bauen beide Images und Compose startet.
Vom eigenen Rechner aus braucht es dafür nur einen ssh-Zugang.

```bash
make deploy DEPLOY_HOST=user@vm
```

`scripts/deploy.sh` überträgt das Repo und schickt dann `scripts/remote-deploy.sh` per ssh an die
VM, wo es Compose startet. Auf der VM muss vorher nichts liegen außer `rsync`, Docker und
Compose v2. Der ssh-Benutzer muss Docker ohne `sudo` nutzen dürfen (Gruppe `docker`).

| Variable | Standard | Bedeutung |
|---|---|---|
| `DEPLOY_HOST` | – | ssh-Ziel, `user@host` oder ein Alias aus `~/.ssh/config` |
| `DEPLOY_JUMP` | – | Jumphost wie bei `ssh -J`, z. B. `user@jumphost`; gilt für ssh und rsync |
| `DEPLOY_BIND` | – | Adresse, auf der die App auf der VM lauscht; beim ersten Deploy Pflicht |
| `DEPLOY_DIR` | `fidelius` | Verzeichnis auf der VM, relativ zum Home oder absolut |
| `WAIT_TIMEOUT` | `1800` | Sekunden, die Compose auf gesunde Container wartet |
| `DEPLOY_ALLOW_DIRTY` | – | `1` deployt auch nicht committete Änderungen, sonst bricht das Skript ab |

## Was passiert

1. Das Skript bricht ab, wenn `git status` nicht committete oder nicht verfolgte Dateien zeigt,
   außer mit `DEPLOY_ALLOW_DIRTY=1`. Dann laufen die Unit-Tests (`make test`); schlagen sie fehl,
   geht nichts auf die VM. So entspricht der Stand auf der VM einem getesteten Commit, und eine
   Änderung daran, was die App protokolliert, fällt auf (siehe
   [ki-systembeschreibung.md](ki-systembeschreibung.md)).
2. rsync überträgt alles außer `.git` und dem, was `.gitignore` ausschließt (`.envrc`, `.env`,
   `.venv`, Caches). Das Skript zeigt an, welcher Commit es ist und ob Änderungen dazukommen.
   Dateien, die lokal nicht mehr existieren, löscht rsync auch auf der VM.
3. Ist `DEPLOY_BIND` gesetzt, schreibt das Skript den Wert als `APP_BIND` in die `.env` im
   Verzeichnis auf der VM. Fehlt beides, bricht es ab, denn einen Default gibt es bewusst nicht
   (siehe Zugang). Andere Zeilen der `.env` bleiben unangetastet; dort lassen sich auch die
   Variablen aus `.envrc.example` setzen (ohne `export`).
4. `docker compose up --build -d --wait` baut und startet beide Container und kommt zurück, wenn
   beide gesund sind. Der erste Start lädt den Laya-Checkpoint und kann einige Minuten dauern.
   Den Git-Stand bekommt das App-Image als Build-Args mit; die Fußzeile der UI zeigt Version,
   Build-Nummer und Commit, auch ob nicht committete Änderungen dabei waren.

## Zugang

Die App hat keinen Login, den Schutz übernimmt der Reverse-Proxy. Kommt dort eine Anmeldung dazu,
prüft sie nur, ob jemand zum GDV gehört, und gibt keine Identität an die App weiter (#19,
[ki-systembeschreibung.md](ki-systembeschreibung.md)). Port 8080 sollte nur für den Proxy
erreichbar sein. Am engsten ist `DEPLOY_BIND` mit der Adresse des Interfaces, über das der Proxy
kommt. `0.0.0.0` öffnet den Port auf jedem Interface der VM; das passt nur, wenn eine Firewall ihn
für alles außer dem Proxy sperrt.

Unabhängig davon lehnt die App zu große Anfragen ab: Texte über `MAX_TEXT_CHARS` Zeichen,
Request-Bodys über 2 MB und mehr als 2000 Stellen auf einmal.

## Auf der VM nachsehen

`make remote-login` öffnet eine Shell auf der VM im Deploy-Verzeichnis, mit denselben Variablen
wie `make deploy`. Dort dann:

```bash
docker compose ps
docker compose logs -f
```

## Request-Log bleibt leer

Das Request-Log liegt im Volume `request-log`. Docker übernimmt den Eigentümer aus dem Image nur,
wenn es das Volume neu anlegt. Gibt es das Volume schon, etwa von einem Stand vor dem Log, und
gehört es `root`, darf die App (Benutzer 10001) nicht hineinschreiben. Prüfungen laufen trotzdem;
im App-Log steht nur `Request-Log nicht schreibbar`, eine Warnung je Prüfung.

Beheben lässt es sich auf der VM auf zwei Wegen. Der Eigentümer lässt sich umstellen, das Log
bleibt erhalten:

```bash
docker compose run --rm --no-deps --user root --entrypoint chown app -R 10001:10001 /var/log/fidelius
docker compose restart app
```

Oder das Volume wird neu angelegt, ein bisheriges Log geht dabei verloren:

```bash
docker compose down
docker volume rm "$(basename "$PWD")_request-log"
docker compose up -d --wait
```
