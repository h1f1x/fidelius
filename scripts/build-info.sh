#!/usr/bin/env bash
# Gibt den Git-Stand als KEY=value-Zeilen aus, für die Build-Args des App-Images. Auf der VM gibt
# es kein .git, deshalb entstehen die Werte lokal: make up und scripts/deploy.sh rufen dieses
# Skript. Ohne Git-Repo gibt es nichts aus, die UI zeigt dann "Build unbekannt".
set -euo pipefail

cd "$(dirname "$0")/.."
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

echo "BUILD_NUMBER=$(git rev-list --count HEAD)"
echo "BUILD_COMMIT=$(git rev-parse --short HEAD)"
# deploy.sh überträgt auch nicht committete Änderungen; dann beschreibt der Commit allein den
# Stand nicht.
echo "BUILD_DIRTY=$([ -n "$(git status --porcelain)" ] && echo 1 || echo 0)"
echo "BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
