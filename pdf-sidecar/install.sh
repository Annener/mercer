#!/usr/bin/env bash
# pdf-sidecar — установка зависимостей
#
# Создаёт venv, ставит requirements.txt, detectron2 и onnxruntime-silicon.
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
    echo "[1/6] Creating venv at ${VENV_DIR}…"
    "${PYTHON}" -m venv "${VENV_DIR}"
else
    echo "[1/6] venv already exists — skipping creation"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "[2/6] Upgrading pip…"
pip install --upgrade pip --quiet

echo "[3/6] Installing requirements.txt…"
# Сначала удаляем стандартный onnxruntime если он уже установлен —
# onnxruntime и onnxruntime-silicon конфликтуют (оба устанавливают onnxruntime).
pip uninstall -y onnxruntime 2>/dev/null || true
pip install -r "${SCRIPT_DIR}/requirements.txt"

# 4. onnxruntime-silicon — Apple Silicon CoreML Execution Provider
# Нужен для ускорения YOLO layout detection через ANE/GPU.
# Пробуем явно после requirements чтобы гарантировать что стандартный ORT не перезаписан.
echo "[4/6] Ensuring onnxruntime-silicon (CoreML EP for Apple Silicon)…"
if python -c "import onnxruntime; providers = onnxruntime.get_available_providers(); exit(0 if 'CoreMLExecutionProvider' in providers else 1)" 2>/dev/null; then
    echo "      CoreMLExecutionProvider already available — OK"
else
    echo "      Installing onnxruntime-silicon…"
    pip uninstall -y onnxruntime 2>/dev/null || true
    pip install onnxruntime-silicon
    echo "      onnxruntime-silicon installed"
fi

# 5. detectron2 — отдельная установка (нет wheel для arm64 на PyPI)
echo "[5/6] Installing detectron2…"
echo "      Trying from GitHub source (official method for Apple Silicon)…"
if pip install 'git+https://github.com/facebookresearch/detectron2.git' --quiet 2>/dev/null; then
    echo "      detectron2 installed from GitHub source."
else
    echo "      WARNING: detectron2 install failed."
    echo "      unstructured hi_res может не работать без detectron2."
    echo "      Попробуйте вручную:"
    echo "        pip install 'git+https://github.com/facebookresearch/detectron2.git'"
    echo "      или через conda:"
    echo "        conda install -c conda-forge detectron2"
fi

# 6. tesseract + poppler — проверка системных зависимостей
echo "[6/6] System dependencies check…"
if ! command -v tesseract &>/dev/null; then
    echo "      WARNING: tesseract not found. Install: brew install tesseract tesseract-lang"
else
    echo "      tesseract: $(tesseract --version 2>&1 | head -1)"
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

# Итоговая проверка ORT провайдеров
echo ""
echo "=== ONNX Runtime providers ==="
python -c "
import onnxruntime as ort
providers = ort.get_available_providers()
print('Available:', providers)
if 'CoreMLExecutionProvider' in providers:
    print('✓ CoreML (Apple Silicon GPU/ANE) — ACTIVE')
else:
    print('✗ CoreML not available — will use CPU')
    print('  To fix: pip install onnxruntime-silicon')
"

echo ""
echo "=== Installation complete ==="
echo "Start: ./start.sh"
echo "Stop:  ./stop.sh"
echo "Logs:  tail -f logs/sidecar.log"
