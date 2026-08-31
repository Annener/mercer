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
#   DRIFT_MODEL_PATH    — абсолютный путь к .gguf файлу drift-модели
#                         (по умолчанию: pdf-sidecar/models/<DRIFT_MODEL_NAME>.gguf).
#   DRIFT_MODEL_NAME    — имя файла drift-модели без расширения
#                         (по умолчанию: qwen2.5-3b-instruct-q4_k_m).
#   DRIFT_MODEL_CTX     — размер контекста llama.cpp (по умолчанию: 4096).
#   DRIFT_MODEL_THREADS — количество CPU-потоков llama.cpp (по умолчанию: cpu_count).
#   DRIFT_FORCE_CPU     — принудительно использовать CPU (0 = GPU если доступен).

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

# Drift-модель по умолчанию тоже форсируем в CPU на macOS — Metal под llama-cpp
# часто ведёт себя непредсказуемо на M-серии, и drift-модель на 3B токенизируется
# за миллисекунды даже на CPU. Переопределите DRIFT_FORCE_CPU=0 для экспериментов.
if [[ "$(uname -s)" == "Darwin" ]]; then
    export DRIFT_FORCE_CPU="${DRIFT_FORCE_CPU:-1}"
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

# shared_contracts импортируется через sys.path при cwd == родительской
# директории репо, но при `python -m uvicorn` из pdf-sidecar cwd = pdf-sidecar
# и shared_contracts не находится. Добавляем родителя в PYTHONPATH.
export PYTHONPATH="${SCRIPT_DIR}/..:${PYTHONPATH:-}"

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

DRIFT_MODEL_PATH="${DRIFT_MODEL_PATH:-${SCRIPT_DIR}/models/${DRIFT_MODEL_NAME:-qwen2.5-3b-instruct-q4_k_m}.gguf}"
if [[ -f "${DRIFT_MODEL_PATH}" ]]; then
    echo "[sidecar] Drift model: ${DRIFT_MODEL_PATH}"
else
    echo "[sidecar] Drift model not found at ${DRIFT_MODEL_PATH} — POST /drift will return 503 until model is installed"
fi
