#!/usr/bin/env bash
# pdf-sidecar — запуск в фоне
# Использование: ./start.sh [порт]
#
# Переменные окружения:
#   PDF_SIDECAR_PORT    — порт HTTP-сервера (по умолчанию: 8765)
#   LOG_LEVEL           — уровень логирования (по умолчанию: INFO)
#   RERANKER_FORCE_CPU  — принудительно использовать CPU для реранкера.
#                         По умолчанию: 1 на macOS (MPS даёт тихий fallback на CPU
#                         для bge-reranker и вешает систему через Metal/UI конкуренцию).
#                         Установите в 0 чтобы попробовать MPS вручную.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
PIDFILE="${SCRIPT_DIR}/sidecar.pid"
LOGFILE="${SCRIPT_DIR}/logs/sidecar.log"
APP_MODULE="app:app"

export PDF_SIDECAR_PORT="${1:-${PDF_SIDECAR_PORT:-8765}}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"

# На macOS MPS не даёт реального ускорения для bge-reranker (тихий CPU-fallback)
# и вызывает зависания системы из-за конкуренции с Metal UI-рендерингом.
# Принудительно используем CPU если явно не переопределено.
if [[ "$(uname -s)" == "Darwin" ]]; then
    export RERANKER_FORCE_CPU="${RERANKER_FORCE_CPU:-1}"
    if [[ "${RERANKER_FORCE_CPU}" == "1" ]]; then
        echo "[sidecar] macOS detected: reranker will use CPU (RERANKER_FORCE_CPU=1)"
        echo "[sidecar] To use MPS: RERANKER_FORCE_CPU=0 ./start.sh"
    fi
fi

# --- Проверки ---
if [[ ! -d "${VENV_DIR}" ]]; then
    echo "[sidecar] ERROR: venv not found at ${VENV_DIR}"
    echo "          Run: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    echo "          Then follow README.md for detectron2 installation."
    exit 1
fi

if [[ -f "${PIDFILE}" ]]; then
    OLD_PID=$(cat "${PIDFILE}")
    if kill -0 "${OLD_PID}" 2>/dev/null; then
        echo "[sidecar] Already running (PID ${OLD_PID}). Use ./stop.sh first."
        exit 1
    else
        rm -f "${PIDFILE}"
    fi
fi

mkdir -p "${SCRIPT_DIR}/logs"

# --- Активируем venv и запускаем ---
echo "[sidecar] Starting on port ${PDF_SIDECAR_PORT} (log: ${LOGFILE})"

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

cd "${SCRIPT_DIR}"

nohup python -m uvicorn "${APP_MODULE}" \
    --host 0.0.0.0 \
    --port "${PDF_SIDECAR_PORT}" \
    --log-level "$(echo "${LOG_LEVEL}" | tr '[:upper:]' '[:lower:]')" \
    >> "${LOGFILE}" 2>&1 &

SIDECAR_PID=$!
echo "${SIDECAR_PID}" > "${PIDFILE}"

# Проверяем что процесс не упал сразу
sleep 2
if ! kill -0 "${SIDECAR_PID}" 2>/dev/null; then
    echo "[sidecar] ERROR: process exited immediately. Check logs: ${LOGFILE}"
    rm -f "${PIDFILE}"
    exit 1
fi

echo "[sidecar] Started (PID ${SIDECAR_PID})"
echo "[sidecar] Health: http://localhost:${PDF_SIDECAR_PORT}/health"
echo "[sidecar] Logs:   tail -f ${LOGFILE}"
