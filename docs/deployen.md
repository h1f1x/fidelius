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

## Was passiert

1. rsync überträgt alles außer `.git` und dem, was `.gitignore` ausschließt (`.envrc`, `.env`,
   `.venv`, Caches). Deployt wird der Arbeitsstand, auch nicht committete Änderungen; das Skript
   zeigt an, welcher Commit es ist und ob Änderungen dazukommen. Dateien, die lokal nicht mehr
   existieren, löscht rsync auch auf der VM.
2. Ist `DEPLOY_BIND` gesetzt, schreibt das Skript den Wert als `APP_BIND` in die `.env` im
   Verzeichnis auf der VM. Fehlt beides, bricht es ab, denn einen Default gibt es bewusst nicht
   (siehe Zugang). Andere Zeilen der `.env` bleiben unangetastet; dort lassen sich auch die
   Variablen aus `.envrc.example` setzen (ohne `export`).
3. `docker compose up --build -d --wait` baut und startet beide Container und kommt zurück, wenn
   beide gesund sind. Der erste Start lädt den Laya-Checkpoint und kann einige Minuten dauern.

## Zugang

Die App hat keinen Login, den Schutz übernimmt der Reverse-Proxy. Deshalb sollte Port 8080 nur
für den Proxy erreichbar sein. Am engsten ist `DEPLOY_BIND` mit der Adresse des Interfaces, über
das der Proxy kommt. `0.0.0.0` öffnet den Port auf jedem Interface der VM; das passt nur, wenn
eine Firewall ihn für alles außer dem Proxy sperrt.

Unabhängig davon lehnt die App zu große Anfragen ab: Texte über `MAX_TEXT_CHARS` Zeichen,
Request-Bodys über 2 MB und mehr als 2000 Stellen auf einmal.

## Auf der VM nachsehen

`make remote-login` öffnet eine Shell auf der VM im Deploy-Verzeichnis, mit denselben Variablen
wie `make deploy`. Dort dann:

```bash
docker compose ps
docker compose logs -f
```
