#!/usr/bin/env bash
# pdf-sidecar — установка зависимостей
#
# Создаёт venv, ставит requirements.txt и detectron2.
# Требует: Python 3.11+, tesseract (brew install tesseract tesseract-lang),
#           poppler (brew install poppler)
#
# Запуск: chmod +x install.sh && ./install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
PYTHON="${PYTHON:-python3}"

echo "=== pdf-sidecar install ==="
echo "Python: $("${PYTHON}" --version)"

# 1. Создаём venv
if [[ ! -d "${VENV_DIR}" ]]; then
    echo "[1/5] Creating venv at ${VENV_DIR}…"
    "${PYTHON}" -m venv "${VENV_DIR}"
else
    echo "[1/5] venv already exists — skipping creation"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "[2/5] Upgrading pip…"
pip install --upgrade pip --quiet

echo "[3/5] Installing requirements.txt…"
pip install -r "${SCRIPT_DIR}/requirements.txt"

# 4. detectron2 — отдельная установка (нет wheel для arm64 на PyPI)
echo "[4/5] Installing detectron2…"
echo "      Trying pre-built wheel for Apple Silicon (Python 3.11)…"

# Пробуем detectron2 через pip install git+https (официальный способ)
if pip install 'git+https://github.com/facebookresearch/detectron2.git' --quiet 2>/dev/null; then
    echo "      detectron2 installed from GitHub source."
else
    echo "      WARNING: detectron2 install failed."
    echo "      unstructured hi_res может не работать без detectron2."
    echo "      Попробуйте вручную:"
    echo "        pip install 'git+https://github.com/facebookresearch/detectron2.git'"
    echo "      или установите через conda:"
    echo "        conda install -c conda-forge detectron2"
fi

# 5. tesseract + poppler — напоминание (должны быть установлены через brew)
echo "[5/5] System dependencies check…"
if ! command -v tesseract &>/dev/null; then
    echo "      WARNING: tesseract not found. Install: brew install tesseract tesseract-lang"
else
    echo "      tesseract: $(tesseract --version 2>&1 | head -1)"
    # Проверяем наличие русского языка
    if ! tesseract --list-langs 2>/dev/null | grep -q "rus"; then
        echo "      WARNING: Russian language pack not found."
        echo "      Install: brew install tesseract-lang"
    else
        echo "      Russian OCR: OK"
    fi
fi

if ! command -v pdftoppm &>/dev/null; then
    echo "      WARNING: poppler not found. Install: brew install poppler"
else
    echo "      poppler: OK"
fi

echo ""
echo "=== Installation complete ==="
echo "Start: ./start.sh"
echo "Stop:  ./stop.sh"
echo "Logs:  tail -f logs/sidecar.log"
