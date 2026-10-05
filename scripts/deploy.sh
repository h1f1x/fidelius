#!/usr/bin/env bash
# Überträgt den lokalen Arbeitsstand per rsync auf die VM und startet dort Compose. Dafür geht
# remote-deploy.sh per ssh hinüber und läuft dort; auf der VM muss nichts liegen außer rsync und
# Docker Compose. Anleitung: docs/deployen.md
#
#   DEPLOY_HOST=user@vm scripts/deploy.sh
#
# DEPLOY_JUMP Jumphost, über den ssh die VM erreicht, wie bei ssh -J (Default: keiner)
# DEPLOY_BIND Adresse, auf der die App auf der VM lauscht; Pflicht, solange die .env dort keine nennt
# DEPLOY_DIR  Verzeichnis auf der VM, relativ zum Home oder absolut (Default: fidelius)
set -euo pipefail

: "${DEPLOY_HOST:?DEPLOY_HOST fehlt, z. B. DEPLOY_HOST=user@vm scripts/deploy.sh}"
DEPLOY_JUMP=${DEPLOY_JUMP:-}
DEPLOY_BIND=${DEPLOY_BIND:-}
DEPLOY_DIR=${DEPLOY_DIR:-fidelius}
# Der erste Start lädt den Laya-Checkpoint, das kann bei langsamer Leitung dauern.
WAIT_TIMEOUT=${WAIT_TIMEOUT:-1800}

cd "$(dirname "$0")/.."

# ssh und rsync gehen beide über den Jumphost, falls einer gesetzt ist.
ssh_cmd="ssh${DEPLOY_JUMP:+ -J $DEPLOY_JUMP}"
remote() { $ssh_cmd "$DEPLOY_HOST" "$@"; }

# Deployt wird der Arbeitsstand, auch was nicht committet ist.
echo "Deploye $(git describe --always --dirty=' mit nicht committeten Änderungen') nach $DEPLOY_HOST:$DEPLOY_DIR${DEPLOY_JUMP:+ über $DEPLOY_JUMP}"

# Die Werte kommen von hier und sollen lokal expandieren; printf %q schützt sie für die Remote-Shell.
remote_dir=$(printf '%q' "$DEPLOY_DIR")
remote "command -v rsync >/dev/null || { echo 'rsync fehlt auf der VM.'; exit 1; }; mkdir -p $remote_dir"

# Was .gitignore ausschließt, geht nicht hinüber und wird drüben auch nicht gelöscht. So bleibt
# die .env auf der VM stehen, während --delete alles andere auf den lokalen Stand bringt.
rsync -az --delete --exclude=.git --exclude-from=.gitignore -e "$ssh_cmd" ./ "$DEPLOY_HOST:$remote_dir/"

# Auf der VM fehlt .git, deshalb kommt der Build-Stand von hier. Die Werte enthalten keine
# Leerzeichen oder Sonderzeichen und gehen unverändert durch die Remote-Shell.
build_env=$(scripts/build-info.sh | tr '\n' ' ')
remote "env $build_env bash -s -- $remote_dir $(printf '%q ' "$WAIT_TIMEOUT" "$DEPLOY_BIND")" < scripts/remote-deploy.sh
