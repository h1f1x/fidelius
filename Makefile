# Lokaler Betrieb: Tools prüfen und installieren, Compose starten, Tests ausführen.
# Läuft auf macOS (Homebrew, Colima als Runtime, falls keine andere läuft) und unter
# Linux bzw. Windows mit WSL2 (apt, Docker Engine). Anleitung: docs/lokal-aufsetzen.md
SHELL := /bin/bash
.DEFAULT_GOAL := help

OS := $(shell uname -s)

APP_PORT ?= 8080
COLIMA_CPU ?= 4
COLIMA_MEMORY ?= 8
COLIMA_DISK ?= 40
MIN_DOCKER_MEM_GB ?= 7
# Der erste Start lädt den Laya-Checkpoint, das kann bei langsamer Leitung dauern.
WAIT_TIMEOUT ?= 1800
# Die Unit-Tests brauchen keine Modelle, deshalb nur diese Pakete statt aller Abhängigkeiten.
TEST_DEPS := --with pydantic --with httpx --with fastapi --with pytest --with google-re2

.PHONY: help init up down logs status test examples loadtest loadtest-report deploy remote-login \
        _tools-Darwin _tools-Linux _runtime-Darwin _runtime-Linux _start-Darwin _start-Linux \
        _compose _memory

help: ## Diese Übersicht
	@grep -E '^[a-z][a-z-]*:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-15s %s\n", $$1, $$2}'

init: _tools-$(OS) _runtime-$(OS) _compose _memory ## Tools prüfen und fehlende installieren, Runtime starten
	@echo "Fertig. Weiter mit: make up"

up: _start-$(OS) ## Container bauen und starten, wartet bis alles bereit ist
	env $$(scripts/build-info.sh) docker compose up --build -d --wait --wait-timeout $(WAIT_TIMEOUT)
	@echo "Web-UI: http://localhost:$(APP_PORT)"

down: ## Container stoppen (das Laya-Modell bleibt im Volume)
	docker compose down

logs: ## Logs beider Container verfolgen
	docker compose logs -f

status: ## Zustand der Container
	docker compose ps

test: ## Unit-Tests ohne Modelle (Regex, Zusammenführen, Platzhalter, Laya-Regeln)
	cd app && uv run --no-project --python 3.12 $(TEST_DEPS) python -m pytest -q

examples: ## Beispielmails gegen die laufende App prüfen, z. B. make examples ARGS="-q 05"
	@curl -fsS -o /dev/null http://localhost:$(APP_PORT)/api/health \
	  || { echo "App antwortet nicht auf Port $(APP_PORT). Erst: make up"; exit 1; }
	uv run --no-project --python 3.12 scripts/run_examples.py --url http://localhost:$(APP_PORT) $(ARGS)

# Ohne --url in ARGS geht der Test per SSH-Tunnel an die VM, mit denselben Variablen wie deploy.
loadtest: ## Lasttest, Ergebnis in loadtest-results/, z. B. make loadtest ARGS="--label 16gb"
	uv run --no-project --python 3.12 scripts/loadtest.py $(ARGS)

loadtest-report: ## Bericht über die Läufe als loadtest-results/bericht.html, z. B. ARGS="--target 3"
	uv run --no-project --python 3.12 scripts/loadtest_report.py $(ARGS)

deploy: ## Arbeitsstand per rsync auf die VM bringen und starten, z. B. make deploy DEPLOY_HOST=user@vm
	scripts/deploy.sh

# Gleiche Variablen wie scripts/deploy.sh. Vor dem ersten Deploy gibt es das Verzeichnis noch
# nicht, dann landet die Shell im Home.
remote-login: ## Shell auf der VM im Deploy-Verzeichnis öffnen
	@: "$${DEPLOY_HOST:?DEPLOY_HOST fehlt, siehe docs/deployen.md}"
	ssh -t $${DEPLOY_JUMP:+-J "$$DEPLOY_JUMP"} "$$DEPLOY_HOST" \
	  "cd \"$${DEPLOY_DIR:-fidelius}\" 2>/dev/null; exec \"\$$SHELL\" -l"

# --- macOS ------------------------------------------------------------------------------

_tools-Darwin:
	@command -v brew >/dev/null || { echo "Homebrew fehlt. Installation: https://brew.sh"; exit 1; }
	@command -v uv >/dev/null || brew install uv
	@echo "uv: $$(uv --version)"

# Eine laufende Runtime (Docker Desktop, OrbStack, Colima) wird genommen, wie sie ist. Nur wenn
# keine da ist, kommt Colima dazu.
_runtime-Darwin:
	@if docker info >/dev/null 2>&1; then \
	  echo "Docker-Runtime läuft (Kontext: $$(docker context show))"; \
	elif command -v colima >/dev/null; then \
	  $(MAKE) --no-print-directory _start-Darwin; \
	elif [ -n "$$(ls -d {,$$HOME}/Applications/{Docker,OrbStack}.app 2>/dev/null)" ]; then \
	  echo "Docker Desktop oder OrbStack ist installiert, läuft aber nicht. Bitte starten und make init wiederholen."; \
	  exit 1; \
	else \
	  echo "Keine Docker-Runtime gefunden, installiere Colima."; \
	  brew install colima docker docker-compose && $(MAKE) --no-print-directory _start-Darwin; \
	fi

# Die Größen gelten nur beim Anlegen: colima start mit Flags überschreibt die Konfiguration
# eines bestehenden Profils, auch wenn sie dort bewusst größer gesetzt ist. colima stop löscht
# den Docker-Kontext; läuft Colima wieder, ohne ihn neu angelegt zu haben, legt make ihn an.
_start-Darwin:
	@if docker info >/dev/null 2>&1; then exit 0; fi; \
	if command -v colima >/dev/null; then \
	  if colima status >/dev/null 2>&1; then \
	    docker context inspect colima >/dev/null 2>&1 || docker context create colima --docker \
	      "host=$$(colima status --json | sed -E 's/.*"docker_socket":"([^"]*)".*/\1/')" >/dev/null; \
	    docker context use colima >/dev/null; \
	  elif colima list --json 2>/dev/null | grep -q '"name":"default"'; then colima start; \
	  else colima start --cpu $(COLIMA_CPU) --memory $(COLIMA_MEMORY) --disk $(COLIMA_DISK); fi; \
	else \
	  echo "Keine Docker-Runtime erreichbar. Erst: make init"; exit 1; \
	fi

# --- Linux / WSL2 -----------------------------------------------------------------------

_tools-Linux:
	@command -v curl >/dev/null || { echo "curl fehlt: sudo apt-get install -y curl"; exit 1; }
	@if ! command -v uv >/dev/null; then \
	  curl -LsSf https://astral.sh/uv/install.sh | sh; \
	  echo "uv ist installiert. Terminal neu öffnen, damit es im PATH liegt, dann make init wiederholen."; \
	  exit 1; \
	fi
	@echo "uv: $$(uv --version)"

_runtime-Linux:
	@if docker info >/dev/null 2>&1; then \
	  echo "Docker-Runtime läuft (Kontext: $$(docker context show))"; exit 0; \
	fi; \
	if ! command -v docker >/dev/null; then \
	  command -v apt-get >/dev/null || { echo "Kein apt gefunden. Docker Engine bitte von Hand installieren."; exit 1; }; \
	  echo "Keine Docker-Runtime gefunden, installiere Docker Engine aus apt."; \
	  sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 docker-buildx \
	    && sudo usermod -aG docker "$$USER"; \
	fi; \
	$(MAKE) --no-print-directory _start-Linux

_start-Linux:
	@if docker info >/dev/null 2>&1; then exit 0; fi; \
	command -v docker >/dev/null || { echo "Docker fehlt. Erst: make init"; exit 1; }; \
	sudo docker info >/dev/null 2>&1 || sudo service docker start; \
	if ! docker info >/dev/null 2>&1; then \
	  if sudo docker info >/dev/null 2>&1; then \
	    echo "Docker läuft, aber dein Benutzer ist noch nicht in der Gruppe docker aktiv."; \
	    echo "Terminal schließen und neu öffnen. Hilft das nicht: in PowerShell 'wsl --shutdown'."; \
	  else \
	    echo "Docker startet nicht. Siehe: sudo service docker status"; \
	  fi; \
	  exit 1; \
	fi

# Alles andere, etwa Git Bash unter Windows (uname: MINGW64_NT-…).
_tools-% _runtime-% _start-%:
	@echo "System $(OS) wird nicht unterstützt. Unter Windows bitte in WSL2 ausführen, siehe docs/lokal-aufsetzen.md."; exit 1

# --- gemeinsam --------------------------------------------------------------------------

# Homebrews docker-compose legt sich nicht selbst als CLI-Plugin ab, daher der Link.
_compose:
	@if ! docker compose version >/dev/null 2>&1; then \
	  if [ "$(OS)" = Darwin ]; then \
	    brew list docker-compose >/dev/null 2>&1 || brew install docker-compose; \
	    plugins="$${DOCKER_CONFIG:-$$HOME/.docker}/cli-plugins"; mkdir -p "$$plugins"; \
	    ln -sfn "$$(brew --prefix)/opt/docker-compose/bin/docker-compose" "$$plugins/docker-compose"; \
	  else \
	    sudo apt-get install -y docker-compose-v2; \
	  fi; \
	fi
	@docker compose version

_memory:
	@mem=$$(docker info --format '{{.MemTotal}}') || exit 1; \
	gb=$$(awk -v m="$$mem" 'BEGIN { printf "%.1f", m / 1024 / 1024 / 1024 }'); \
	if awk -v g="$$gb" -v min=$(MIN_DOCKER_MEM_GB) 'BEGIN { exit !(g < min) }'; then \
	  echo "WARNUNG: Docker hat nur $$gb GB RAM, gebraucht werden rund 8 GB."; \
	  echo "  Colima:         colima stop && colima start --memory $(COLIMA_MEMORY)  (merkt sich den Wert)"; \
	  echo "  WSL2:           memory=10GB in %UserProfile%\\.wslconfig, dann wsl --shutdown"; \
	  echo "  Docker Desktop: Settings > Resources > Memory"; \
	else \
	  echo "Docker-RAM: $$gb GB"; \
	fi
