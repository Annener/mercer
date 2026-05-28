#!/usr/bin/env bash
# pdf-sidecar — остановка

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDFILE="${SCRIPT_DIR}/sidecar.pid"

if [[ ! -f "${PIDFILE}" ]]; then
    echo "[sidecar] Not running (no PID file)."
    exit 0
fi

PID=$(cat "${PIDFILE}")

if kill -0 "${PID}" 2>/dev/null; then
    echo "[sidecar] Stopping PID ${PID}…"
    kill -TERM "${PID}"
    # Ждём до 10 секунд
    for i in $(seq 1 10); do
        sleep 1
        if ! kill -0 "${PID}" 2>/dev/null; then
            echo "[sidecar] Stopped."
            rm -f "${PIDFILE}"
            exit 0
        fi
    done
    echo "[sidecar] Did not stop gracefully, sending KILL…"
    kill -KILL "${PID}" 2>/dev/null || true
    rm -f "${PIDFILE}"
    echo "[sidecar] Killed."
else
    echo "[sidecar] Process ${PID} not found (already stopped)."
    rm -f "${PIDFILE}"
fi
