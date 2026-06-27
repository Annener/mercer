# Блок C — Makefile: мультиплатформенный `agent-setup`

> Зависит от: Блок B (`.env` с `AGENT_MODE` должен создаваться до `agent-setup`).

---

## C1. Диспетчер по `AGENT_MODE`

Заменить текущую цель `agent-setup: _check-macos ...` на диспетчерскую цель `_agent-setup-dispatch`.

**Новые цели в Makefile:**

```makefile
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

# Переименовать текущий agent-setup:
_agent-setup-launchd: _venv-create agent-install
```

**Обновить `setup`:**

```makefile
setup: init-env _agent-setup-dispatch up seed
```

**Примечание:** `scripts/install-service.ps1` не существует. При `AGENT_MODE=host-win` диспетчер печатает предупреждение и завершается без ошибки.

---

## C2. Прокинуть `HOST_AGENT_TOKEN` в plist

**Проблема:** `HOST_AGENT_TOKEN` в plist-шаблоне закомментирован → host-agent запускается без токена → авторизация де-факто отключена.

### Шаг 1 — Обновить plist-шаблон

Файл: `pdf-sidecar/agent/com.mercer.host-agent.plist.template`

Раскомментировать и добавить placeholder:

```xml
<key>HOST_AGENT_TOKEN</key>
<string>{{HOST_AGENT_TOKEN}}</string>
```

### Шаг 2 — Обновить `_render-plist` в Makefile

Добавить строку подстановки токена:

```makefile
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
```

**Важно:** разделитель `|` в `sed` безопасен, так как `HOST_AGENT_TOKEN` содержит только alphanumeric символы и `-_`.

**Порядок выполнения:** `init-env` → `_agent-setup-dispatch` строго соблюдать — plist рендерится уже с финальным токеном из `.env`.
