#!/usr/bin/env bash
# pdf-sidecar — установка зависимостей
#
# ВАЖНО: требует Python 3.11–3.13.
# unstructured-inference несовместим с Python 3.14+.
#
# Требования системы:
#   brew install tesseract tesseract-lang poppler
#
# Запуск: chmod +x install.sh && ./install.sh
#         PYTHON=/usr/local/bin/python3.13 ./install.sh  # указать явно если нужно

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
PYTHON="${PYTHON:-python3.13}"

# Проверяем что Python существует, иначе пробуем python3
if ! command -v "${PYTHON}" &>/dev/null; then
    echo "WARNING: ${PYTHON} not found, falling back to python3"
    PYTHON="python3"
fi

PYTHON_VERSION=$("${PYTHON}" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$("${PYTHON}" -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$("${PYTHON}" -c "import sys; print(sys.version_info.minor)")

echo "=== pdf-sidecar install ==="
echo "Python: $("${PYTHON}" --version) at $(command -v "${PYTHON}")"

# Проверяем совместимость версии Python
if [[ "${PYTHON_MAJOR}" -eq 3 && "${PYTHON_MINOR}" -ge 14 ]]; then
    echo ""
    echo "ERROR: Python ${PYTHON_VERSION} не поддерживается."
    echo "  unstructured-inference требует Python 3.11–3.13."
    echo ""
    echo "  Установите Python 3.13:"
    echo "    brew install python@3.13"
    echo ""
    echo "  Затем запустите:"
    echo "    PYTHON=python3.13 ./install.sh"
    echo "  или:"
    echo "    PYTHON=/opt/homebrew/bin/python3.13 ./install.sh"
    exit 1
fi

if [[ "${PYTHON_MAJOR}" -eq 3 && "${PYTHON_MINOR}" -lt 11 ]]; then
    echo "WARNING: Python ${PYTHON_VERSION} < 3.11, могут быть проблемы совместимости."
fi

echo "Python ${PYTHON_VERSION} — OK"

# 1. Создаём или пересоздаём venv
if [[ -d "${VENV_DIR}" ]]; then
    # Проверяем что venv создан с нужной версией Python
    VENV_PYTHON_VER=$("${VENV_DIR}/bin/python" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "unknown")
    if [[ "${VENV_PYTHON_VER}" != "${PYTHON_VERSION}" ]]; then
        echo "[1/5] venv существует но использует Python ${VENV_PYTHON_VER}."
        echo "      Пересоздаём с Python ${PYTHON_VERSION}…"
        rm -rf "${VENV_DIR}"
        "${PYTHON}" -m venv "${VENV_DIR}"
    else
        echo "[1/5] venv уже существует (Python ${VENV_PYTHON_VER}) — пропускаем"
    fi
else
    echo "[1/5] Создаём venv в ${VENV_DIR}…"
    "${PYTHON}" -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
echo "      Active Python: $(python --version) at $(command -v python)"

echo "[2/5] Upgrading pip…"
pip install --upgrade pip --quiet

echo "[3/5] Installing requirements.txt…"
pip install -r "${SCRIPT_DIR}/requirements.txt"

# 4. detectron2 — нет wheel для arm64/PyPI, нужна сборка из исходников
echo "[4/5] Installing detectron2…"
if python -c "import detectron2" 2>/dev/null; then
    echo "      detectron2 already installed — OK"
else
    echo "      Compiling from GitHub source (займёт 3–5 минут)…"
    if pip install 'git+https://github.com/facebookresearch/detectron2.git' 2>/dev/null; then
        echo "      detectron2 installed OK"
    else
        echo "      WARNING: detectron2 не установился."
        echo "      unstructured hi_res требует detectron2 или yolox."
        echo "      yolox (ONNX-based) используется по умолчанию — продолжаем."
        echo "      Если нужен detectron2, запустите вручную:"
        echo "        pip install 'git+https://github.com/facebookresearch/detectron2.git'"
    fi
fi

# 5. Системные зависимости
echo "[5/5] Checking system dependencies…"
ALL_OK=true

if ! command -v tesseract &>/dev/null; then
    echo "      ✗ tesseract не найден. Установите: brew install tesseract tesseract-lang"
    ALL_OK=false
else
    echo "      ✓ tesseract: $(tesseract --version 2>&1 | head -1)"
    if ! tesseract --list-langs 2>/dev/null | grep -q "rus"; then
        echo "      ✗ Русский язык OCR отсутствует. Установите: brew install tesseract-lang"
        ALL_OK=false
    else
        echo "      ✓ Russian OCR: OK"
    fi
fi

if ! command -v pdftoppm &>/dev/null; then
    echo "      ✗ poppler не найден. Установите: brew install poppler"
    ALL_OK=false
else
    echo "      ✓ poppler: OK"
fi

# Итоговая проверка
echo ""
echo "=== Проверка GPU/ускорения ==="
python - << 'PYCHECK'
import sys

# PyTorch MPS (Table Transformer)
try:
    import torch
    mps = torch.backends.mps.is_available()
    print(f"{'✓' if mps else '✗'} PyTorch MPS (Table Transformer GPU): {'доступен' if mps else 'недоступен'}")
    print(f"  torch version: {torch.__version__}")
except ImportError:
    print("  PyTorch не установлен (ставится как зависимость unstructured)")

# ONNX Runtime (YOLO layout detection)
try:
    import onnxruntime as ort
    providers = ort.get_available_providers()
    has_coreml = 'CoreMLExecutionProvider' in providers
    print(f"{'✓' if has_coreml else '○'} ONNX CoreML (YOLO GPU): {'доступен' if has_coreml else 'недоступен (будет CPU)'}")
    print(f"  onnxruntime version: {ort.__version__}")
    print(f"  available providers: {providers}")
    if not has_coreml:
        print("  Для CoreML нужна кастомная сборка onnxruntime с --use_coreml")
        print("  (готовых wheel для Python 3.12/3.13 не существует)")
except ImportError:
    print("  onnxruntime не установлен")

PYCHECK

echo ""
if [[ "${ALL_OK}" == "true" ]]; then
    echo "=== Установка завершена успешно ==="
else
    echo "=== Установка завершена с предупреждениями (см. выше) ==="
fi
echo ""
echo "Запуск:  ./start.sh"
echo "Статус:  ./status.sh"
echo "Логи:    tail -f logs/sidecar.log"
