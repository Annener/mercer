# =============================================================================
# Mercer — Makefile
# =============================================================================
# Цели:
#   make setup           — полный первичный деплой: init-env + agent-setup + up + seed
#   make init-env        — создать/дополнить .env интерактивно (идемпотентно)
#   make agent-setup     — полная первичная настройка host-agent (venv + launchd/docker)
#   make agent-install   — только установить/обновить launchd plist (без venv, macOS)
#   make agent-uninstall — выгрузить агент из launchd и удалить plist
#   make agent-start     — запустить агент вручную (без launchd)
#   make agent-stop      — остановить агент вручную
#   make agent-status    — проверить статус агента
#   make agent-logs      — tail логов агента
#   make up              — docker compose up -d
#   make down            — docker compose down
#   make seed            — создать дефолтные embedding и rerank модели в БД
#   make help            — этот экран
# =============================================================================

# --- Пути ---
ROOT_DIR       := $(shell pwd)
AGENT_DIR      := $(ROOT_DIR)/pdf-sidecar/agent
SIDECAR_DIR    := $(ROOT_DIR)/pdf-sidecar
VENV_DIR       := $(AGENT_DIR)/.venv
VENV_PYTHON    := $(VENV_DIR)/bin/python
AGENT_PY       := $(AGENT_DIR)/agent.py
LOGS_DIR       := $(AGENT_DIR)/logs

# --- launchd ---
PLIST_LABEL    := com.mercer.host-agent
PLIST_DST      := $(HOME)/Library/LaunchAgents/$(PLIST_LABEL).plist
PLIST_TEMPLATE := $(AGENT_DIR)/com.mercer.host-agent.plist.template

# --- Seed ---
# URL rag-backend для seed-скрипта. Можно переопределить: make seed BACKEND_URL=http://...
BACKEND_URL    := http://localhost:8000

# --- Цвета для вывода ---
GREEN  := \033[0;32m
YELLOW := \033[0;33m
RESET  := \033[0m

# =============================================================================
# _find_python: найти максимальную установленную версию Python из диапазона 3.11–3.13
#
# Проверяет кандидатов в порядке убывания: python3.13, python3.12, python3.11,
# затем python3 / python3 как fallback с проверкой версии.
# Экспортирует MERCER_PYTHON для использования в рецептах.
# Завершает make с ошибкой если подходящий интерпретатор не найден.
# =============================================================================
export MERCER_PYTHON := $(shell \
	for candidate in python3.13 python3.12 python3.11; do \
		if command -v $$candidate >/dev/null 2>&1; then \
			echo $$candidate; \
			exit 0; \
		fi; \
	done; \
	for candidate in python3 python; do \
		if command -v $$candidate >/dev/null 2>&1; then \
			minor=$$($$candidate -c 'import sys; print(sys.version_info.minor)' 2>/dev/null); \
			major=$$($$candidate -c 'import sys; print(sys.version_info.major)' 2>/dev/null); \
			if [ "$$major" = "3" ] && [ "$$minor" -ge 11 ] && [ "$$minor" -le 13 ] 2>/dev/null; then \
				echo $$candidate; \
				exit 0; \
			fi; \
		fi; \
	done \
)

# Проверка: MERCER_PYTHON найден — иначе hard-fail при первом использовании
_check_python:
	@if [ -z "$(MERCER_PYTHON)" ]; then \
		echo ""; \
		echo "$(YELLOW)ERROR: Python 3.11–3.13 не найден.$(RESET)"; \
		echo ""; \
		echo "Установлены кандидаты:"; \
		for v in python3.13 python3.12 python3.11 python3; do \
			path=$$(command -v $$v 2>/dev/null || echo ''); \
			if [ -n "$$path" ]; then \
				echo "  $$v  →  $$($$v --version 2>&1)"; \
			fi; \
		done; \
		echo ""; \
		echo "Установите Python 3.13:  brew install python@3.13"; \
		echo ""; \
		exit 1; \
	fi
	@echo "$(GREEN)✓ Python: $(MERCER_PYTHON) ($$($(MERCER_PYTHON) --version))$(RESET)"

.PHONY: help init-env agent-setup agent-install agent-uninstall agent-start agent-stop \
        agent-status agent-logs up down seed setup _check-macos _check_python _venv-create \
        _logs-dir _render-plist _agent-setup-dispatch _agent-setup-launchd

help:
	@echo ""
	@echo "$(GREEN)Mercer — доступные команды:$(RESET)"
	@echo ""
	@echo "  $(YELLOW)make setup$(RESET)            Полный первичный деплой: init-env + agent-setup + up + seed"
	@echo "  $(YELLOW)make init-env$(RESET)         Создать/дополнить .env интерактивно (идемпотентно)"
	@echo "  $(YELLOW)make agent-setup$(RESET)      Первичная настройка: venv + launchd (macOS) / Docker (Linux)"
	@echo "  $(YELLOW)make agent-install$(RESET)    Переустановить launchd plist (после изменения путей, macOS)"
	@echo "  $(YELLOW)make agent-uninstall$(RESET)  Выгрузить агент из launchd и удалить plist"
	@echo "  $(YELLOW)make agent-start$(RESET)      Запустить агент вручную (без launchd)"
	@echo "  $(YELLOW)make agent-stop$(RESET)       Остановить агент"
	@echo "  $(YELLOW)make agent-status$(RESET)     Проверить статус (launchctl + curl /health)"
	@echo "  $(YELLOW)make agent-logs$(RESET)       Tail логов агента"
	@echo "  $(YELLOW)make up$(RESET)               docker compose up -d"
	@echo "  $(YELLOW)make down$(RESET)             docker compose down"
	@echo "  $(YELLOW)make seed$(RESET)             Создать дефолтные embedding и rerank модели"
	@echo "                        (переопределить URL: make seed BACKEND_URL=http://...)"
	@echo ""

# =============================================================================
# init-env: создать/дополнить .env (первый шаг в setup)
# =============================================================================
init-env: _check_python
	@$(MERCER_PYTHON) scripts/generate_env.py

# =============================================================================
# setup: полный первичный деплой одной командой
# =============================================================================
setup: init-env _agent-setup-dispatch up seed
	@echo ""
	@echo "$(GREEN)✓ Mercer готов к работе.$(RESET)"
	@echo "  UI: http://localhost:8000"

# =============================================================================
# seed: создать дефолтные модели в rag-backend
# =============================================================================
seed: _check_python
	@echo "$(YELLOW)→ Provisioning default models (backend: $(BACKEND_URL))...$(RESET)"
	@$(MERCER_PYTHON) scripts/seed_models.py --base-url "$(BACKEND_URL)"

# =============================================================================
# agent-setup: публичный алиас — диспетчеризует по AGENT_MODE
# =============================================================================
agent-setup: _agent-setup-dispatch

# =============================================================================
# _agent-setup-dispatch: диспетчер по AGENT_MODE из .env
# =============================================================================
_agent-setup-dispatch:
	@AGENT_MODE=$$(grep '^AGENT_MODE=' .env | cut -d= -f2); \
	if [ "$$AGENT_MODE" = "host" ]; then \
		$(MAKE) _agent-setup-launchd; \
	elif [ "$$AGENT_MODE" = "docker" ]; then \
		echo "Linux: host-agent запускается в Docker, пропускаю agent-setup"; \
	else \
		echo "WARNING: AGENT_MODE=host-win — установка Windows-сервиса не реализована."; \
		echo "Продолжаю без установки host-agent."; \
	fi

# =============================================================================
# _agent-setup-launchd: venv + deps + launchd (macOS only)
# =============================================================================
_agent-setup-launchd: _venv-create agent-install
	@echo "$(GREEN)✓ host-agent готов.$(RESET)"
	@echo "  Агент запустится автоматически при следующем логине."
	@echo "  Запустить сейчас: launchctl start $(PLIST_LABEL)"
	@echo "  Проверить:        curl http://localhost:9090/health"

# =============================================================================
# Установить / обновить plist
# =============================================================================
agent-install: _check-macos _logs-dir _render-plist
	@# Выгружаем старую версию если есть (ошибку игнорируем)
	@launchctl unload "$(PLIST_DST)" 2>/dev/null || true
	@launchctl load -w "$(PLIST_DST)"
	@echo "$(GREEN)✓ launchd plist установлен: $(PLIST_DST)$(RESET)"

# =============================================================================
# Удалить из launchd
# =============================================================================
agent-uninstall: _check-macos
	@launchctl unload "$(PLIST_DST)" 2>/dev/null || true
	@rm -f "$(PLIST_DST)"
	@echo "$(GREEN)✓ host-agent выгружен из launchd.$(RESET)"

# =============================================================================
# Запуск / остановка вручную
# =============================================================================
agent-start: _check-macos
	@launchctl start $(PLIST_LABEL) || (\
		echo "$(YELLOW)launchd plist не найден, запускаю напрямую...$(RESET)" && \
		$(VENV_PYTHON) $(AGENT_PY) & \
	)

agent-stop: _check-macos
	@launchctl stop $(PLIST_LABEL) 2>/dev/null || \
		pkill -f "agent.py" 2>/dev/null || \
		echo "$(YELLOW)Агент не запущен.$(RESET)"

agent-status: _check-macos
	@echo "--- launchctl ---"
	@launchctl list | grep mercer || echo "(не зарегистрирован в launchd)"
	@echo "--- /health ---"
	@curl -sf http://localhost:9090/health | $(MERCER_PYTHON) -m json.tool || echo "(агент не отвечает)"

agent-logs:
	@tail -f "$(LOGS_DIR)/agent.log" "$(LOGS_DIR)/agent.err" 2>/dev/null || \
		echo "$(YELLOW)Лог-файлы ещё не созданы.$(RESET)"

# =============================================================================
# Docker
# =============================================================================
up:
	docker compose up -d

down:
	docker compose down

# =============================================================================
# Внутренние цели
# =============================================================================
_check-macos:
	@if [ "$$(uname -s)" != "Darwin" ]; then \
		echo "Эта цель только для macOS (launchd)."; \
		exit 1; \
	fi

_venv-create:
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "$(YELLOW)Создаю venv для host-agent...$(RESET)"; \
		$(MERCER_PYTHON) -m venv "$(VENV_DIR)"; \
	fi
	@echo "$(YELLOW)Устанавливаю зависимости host-agent...$(RESET)"
	@$(VENV_PYTHON) -m pip install -q --upgrade pip
	@$(VENV_PYTHON) -m pip install -q -r "$(AGENT_DIR)/requirements.txt"
	@echo "$(GREEN)✓ venv готов: $(VENV_DIR)$(RESET)"

_logs-dir:
	@mkdir -p "$(LOGS_DIR)"

_render-plist:
	@HOST_AGENT_TOKEN=$$(grep '^HOST_AGENT_TOKEN=' .env | cut -d= -f2); \
	sed \
		-e 's|{{VENV_PYTHON}}|$(VENV_PYTHON)|g' \
		-e 's|{{AGENT_PY}}|$(AGENT_PY)|g' \
		-e 's|{{AGENT_DIR}}|$(AGENT_DIR)|g' \
		-e 's|{{SIDECAR_DIR}}|$(SIDECAR_DIR)|g' \
		-e 's|{{PATH}}|$(PATH)|g' \
		-e "s|{{HOST_AGENT_TOKEN}}|$$HOST_AGENT_TOKEN|g" \
		"$(PLIST_TEMPLATE)" > "$(PLIST_DST)"
	@echo "$(GREEN)✓ plist сгенерирован: $(PLIST_DST)$(RESET)"
