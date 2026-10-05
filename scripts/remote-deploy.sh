#!/usr/bin/env bash
# Läuft auf der VM, gestartet von scripts/deploy.sh über ssh, nachdem rsync den Stand übertragen
# hat. Baut beide Images und startet Compose. Argumente: Verzeichnis, Wartezeit in Sekunden,
# Bind-Adresse (leer: die aus der .env).
set -euo pipefail

dir=$1 wait_timeout=$2 bind=${3:-}

docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 fehlt auf der VM."; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker läuft nicht oder $(id -un) darf es nicht nutzen (Gruppe docker)."; exit 1; }

cd "$dir"

# Der Reverse-Proxy kommt von außen auf die VM, deshalb reicht localhost hier nicht. Welche
# Adresse stattdessen, ist eine bewusste Entscheidung: 0.0.0.0 öffnet den Port auf jedem
# Interface und umgeht den Proxy, wenn keine Firewall davor steht. Deshalb gibt es keinen Default.
touch .env
if [ -n "$bind" ]; then
  { grep -v '^APP_BIND=' .env || true; echo "APP_BIND=$bind"; } > .env.new && mv .env.new .env
elif ! grep -q '^APP_BIND=' .env; then
  echo "Keine Bind-Adresse: DEPLOY_BIND setzen, z. B. auf die Adresse, über die der Proxy kommt."
  exit 1
fi
echo "App bindet an $(sed -n 's/^APP_BIND=//p' .env)"

# Der erste Start lädt den Laya-Checkpoint, das kann dauern.
docker compose up --build -d --wait --wait-timeout "$wait_timeout"
docker compose ps
echo "App lauscht auf $(docker compose port app 8080)"
