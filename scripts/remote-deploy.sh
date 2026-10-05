#!/usr/bin/env bash
# Läuft auf der VM, gestartet von scripts/deploy.sh über ssh, nachdem rsync den Stand übertragen
# hat. Baut beide Images und startet Compose. Argumente: Verzeichnis, Wartezeit in Sekunden.
set -euo pipefail

dir=$1 wait_timeout=$2

docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 fehlt auf der VM."; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker läuft nicht oder $(id -un) darf es nicht nutzen (Gruppe docker)."; exit 1; }

cd "$dir"

# Der Reverse-Proxy kommt von außen auf die VM, deshalb lauscht die App hier auf allen
# Interfaces statt nur auf localhost.
if [ ! -f .env ]; then
  echo "APP_BIND=0.0.0.0" > .env
  echo ".env angelegt mit APP_BIND=0.0.0.0"
fi

# Der erste Start lädt den Laya-Checkpoint, das kann dauern.
docker compose up --build -d --wait --wait-timeout "$wait_timeout"
docker compose ps
echo "App lauscht auf $(docker compose port app 8080)"
