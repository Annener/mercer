# =============================================================================
# Mercer — Makefile
# =============================================================================
# Цели:
#   make agent-setup     — полная первичная настройка host-agent (venv + launchd)
#   make agent-install   — только установить/обновить launchd plist (без venv)
#   make agent-uninstall — выгрузить агент из launchd и удалить plist
#   make agent-start     — запустить агент вручную (без launchd)
#   make agent-stop      — остановить агент вручную
#   make agent-status    — проверить статус агента
#   make agent-logs      — tail логов агента
#   make up              — docker compose up -d
#   make down            — docker compose down
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

# --- Цвета для вывода ---
GREEN  := \033[0;32m
YELLOW := \033[0;33m
RESET  := \033[0m

.PHONY: help agent-setup agent-install agent-uninstall agent-start agent-stop agent-status agent-logs up down

help:
	@echo ""
	@echo "$(GREEN)Mercer — доступные команды:$(RESET)"
	@echo ""
	@echo "  $(YELLOW)make agent-setup$(RESET)      Первичная настройка: venv + launchd (запускать один раз)"
	@echo "  $(YELLOW)make agent-install$(RESET)    Переустановить launchd plist (после изменения путей)"
	@echo "  $(YELLOW)make agent-uninstall$(RESET)  Выгрузить агент из launchd и удалить plist"
	@echo "  $(YELLOW)make agent-start$(RESET)      Запустить агент вручную (без launchd)"
	@echo "  $(YELLOW)make agent-stop$(RESET)       Остановить агент"
	@echo "  $(YELLOW)make agent-status$(RESET)     Проверить статус (launchctl + curl /health)"
	@echo "  $(YELLOW)make agent-logs$(RESET)       Tail логов агента"
	@echo "  $(YELLOW)make up$(RESET)               docker compose up -d"
	@echo "  $(YELLOW)make down$(RESET)             docker compose down"
	@echo ""

# =============================================================================
# agent-setup: venv + deps + launchd
# =============================================================================
agent-setup: _check-macos _venv-create agent-install
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
	@curl -sf http://localhost:9090/health | python3 -m json.tool || echo "(агент не отвечает)"

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
		python3 -m venv "$(VENV_DIR)"; \
	fi
	@echo "$(YELLOW)Устанавливаю зависимости host-agent...$(RESET)"
	@$(VENV_PYTHON) -m pip install -q --upgrade pip
	@$(VENV_PYTHON) -m pip install -q -r "$(AGENT_DIR)/requirements.txt"
	@echo "$(GREEN)✓ venv готов: $(VENV_DIR)$(RESET)"

_logs-dir:
	@mkdir -p "$(LOGS_DIR)"

_render-plist:
	@sed \
		-e 's|{{VENV_PYTHON}}|$(VENV_PYTHON)|g' \
		-e 's|{{AGENT_PY}}|$(AGENT_PY)|g' \
		-e 's|{{AGENT_DIR}}|$(AGENT_DIR)|g' \
		-e 's|{{SIDECAR_DIR}}|$(SIDECAR_DIR)|g' \
		"$(PLIST_TEMPLATE)" > "$(PLIST_DST)"
	@echo "$(GREEN)✓ plist сгенерирован: $(PLIST_DST)$(RESET)"
