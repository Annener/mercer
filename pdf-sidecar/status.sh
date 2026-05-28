#!/usr/bin/env bash
# pdf-sidecar — проверка статуса

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDFILE="${SCRIPT_DIR}/sidecar.pid"
PORT="${PDF_SIDECAR_PORT:-8765}"

if [[ -f "${PIDFILE}" ]]; then
    PID=$(cat "${PIDFILE}")
    if kill -0 "${PID}" 2>/dev/null; then
        echo "[sidecar] RUNNING (PID ${PID})"
        curl -sf "http://localhost:${PORT}/health" && echo "" || echo "[sidecar] WARNING: health check failed"
    else
        echo "[sidecar] STOPPED (stale PID file)"
        rm -f "${PIDFILE}"
    fi
else
    echo "[sidecar] STOPPED"
fi
