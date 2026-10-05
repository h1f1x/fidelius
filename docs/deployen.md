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
| `DEPLOY_DIR` | `fidelius` | Verzeichnis auf der VM, relativ zum Home oder absolut |
| `WAIT_TIMEOUT` | `1800` | Sekunden, die Compose auf gesunde Container wartet |

## Was passiert

1. rsync überträgt alles außer `.git` und dem, was `.gitignore` ausschließt (`.envrc`, `.env`,
   `.venv`, Caches). Deployt wird der Arbeitsstand, auch nicht committete Änderungen; das Skript
   zeigt an, welcher Commit es ist und ob Änderungen dazukommen. Dateien, die lokal nicht mehr
   existieren, löscht rsync auch auf der VM.
2. Fehlt `.env` im Verzeichnis auf der VM, legt das Skript sie mit `APP_BIND=0.0.0.0` an. Dann
   lauscht die App auf allen Interfaces, sodass der Reverse-Proxy sie auf Port 8080 erreicht. Eine
   vorhandene `.env` bleibt unangetastet; dort lassen sich auch die anderen Variablen aus
   `.envrc.example` setzen (ohne `export`).
3. `docker compose up --build -d --wait` baut und startet beide Container und kommt zurück, wenn
   beide gesund sind. Der erste Start lädt den Laya-Checkpoint und kann einige Minuten dauern.

## Zugang

Die App hat keinen Login, den Schutz übernimmt der Reverse-Proxy. Mit `APP_BIND=0.0.0.0` ist Port
8080 aber auf jedem Interface der VM offen. Wer die VM direkt erreicht, umgeht damit den Proxy.
Entweder sperrt eine Firewall den Port für alles außer dem Proxy, oder `APP_BIND` in der `.env`
nennt nur die Adresse des Interfaces, über das der Proxy kommt.

## Auf der VM nachsehen

```bash
ssh user@vm 'cd fidelius && docker compose ps'
ssh user@vm 'cd fidelius && docker compose logs -f'
```
