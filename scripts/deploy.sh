#!/usr/bin/env bash
# Überträgt den lokalen Arbeitsstand per rsync auf die VM und startet dort Compose. Dafür geht
# remote-deploy.sh per ssh hinüber und läuft dort; auf der VM muss nichts liegen außer rsync und
# Docker Compose. Anleitung: docs/deployen.md
#
#   DEPLOY_HOST=user@vm scripts/deploy.sh
#
# DEPLOY_DIR  Verzeichnis auf der VM, relativ zum Home oder absolut (Default: fidelius)
set -euo pipefail

: "${DEPLOY_HOST:?DEPLOY_HOST fehlt, z. B. DEPLOY_HOST=user@vm scripts/deploy.sh}"
DEPLOY_DIR=${DEPLOY_DIR:-fidelius}
# Der erste Start lädt den Laya-Checkpoint, das kann bei langsamer Leitung dauern.
WAIT_TIMEOUT=${WAIT_TIMEOUT:-1800}

cd "$(dirname "$0")/.."

# Deployt wird der Arbeitsstand, auch was nicht committet ist.
echo "Deploye $(git describe --always --dirty=' mit nicht committeten Änderungen') nach $DEPLOY_HOST:$DEPLOY_DIR"

# Die Werte kommen von hier und sollen lokal expandieren; printf %q schützt sie für die Remote-Shell.
remote_dir=$(printf '%q' "$DEPLOY_DIR")
# shellcheck disable=SC2029
ssh "$DEPLOY_HOST" "command -v rsync >/dev/null || { echo 'rsync fehlt auf der VM.'; exit 1; }; mkdir -p $remote_dir"

# Was .gitignore ausschließt, geht nicht hinüber und wird drüben auch nicht gelöscht. So bleibt
# die .env auf der VM stehen, während --delete alles andere auf den lokalen Stand bringt.
rsync -az --delete --exclude=.git --exclude-from=.gitignore ./ "$DEPLOY_HOST:$remote_dir/"

# shellcheck disable=SC2029
ssh "$DEPLOY_HOST" "bash -s -- $remote_dir $(printf '%q' "$WAIT_TIMEOUT")" < scripts/remote-deploy.sh
