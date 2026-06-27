#!/usr/bin/env bash
# pdf-sidecar — установка зависимостей
#
# ВАЖНО: требует Python 3.11–3.13.
# unstructured-inference несовместим с Python 3.14+.
#
# Требования системы:
#   brew install ghostscript tesseract tesseract-lang poppler
#
# Запуск: chmod +x install.sh && ./install.sh
#         PYTHON=/usr/local/bin/python3.13 ./install.sh  # указать явно если нужно
#         SKIP_RERANKER=1 ./install.sh                   # пропустить загрузку reranker-модели
#         SKIP_EMBEDDER=1 ./install.sh                   # пропустить загрузку embedder-модели

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
PYTHON="${PYTHON:-python3.13}"
SKIP_RERANKER="${SKIP_RERANKER:-0}"
SKIP_EMBEDDER="${SKIP_EMBEDDER:-0}"

# ---------------------------------------------------------------------------
# Статусы шагов для итоговой таблицы
# Возможные значения: OK | WARN | ERROR | SKIP
# ---------------------------------------------------------------------------
STEP_PYTHON="OK"
STEP_VENV="OK"
STEP_DEPS="OK"
STEP_DETECTRON="OK"
STEP_SYSTEM="OK"
STEP_GPU="OK"
STEP_RERANKER="OK"
STEP_EMBEDDER="OK"

STEP_PYTHON_NOTE=""
STEP_VENV_NOTE=""
STEP_DEPS_NOTE=""
STEP_DETECTRON_NOTE=""
STEP_SYSTEM_NOTE=""
STEP_GPU_NOTE=""
STEP_RERANKER_NOTE=""
STEP_EMBEDDER_NOTE=""

# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

# Иконка для итоговой таблицы
step_icon() {
    case "$1" in
        OK)    echo "✅ OK   " ;;
        WARN)  echo "⚠️  WARN " ;;
        ERROR) echo "❌ ERROR" ;;
        SKIP)  echo "⏩ SKIP " ;;
        *)     echo "?      " ;;
    esac
}

# Печатаем итоговую таблицу
print_summary() {
    echo ""
    echo "┌─────────────────────────────────────────────────────────────┐"
    echo "│  Итог установки pdf-sidecar                              │"
    echo "├─────────────────────────────────────────────────────────────┤"
    printf "│  [1/8] Python          %s  %s\n" "$(step_icon "${STEP_PYTHON}")" "${STEP_PYTHON_NOTE}"
    printf "│  [2/8] venv            %s  %s\n" "$(step_icon "${STEP_VENV}")" "${STEP_VENV_NOTE}"
    printf "│  [3/8] requirements    %s  %s\n" "$(step_icon "${STEP_DEPS}")" "${STEP_DEPS_NOTE}"
    printf "│  [4/8] detectron2      %s  %s\n" "$(step_icon "${STEP_DETECTRON}")" "${STEP_DETECTRON_NOTE}"
    printf "│  [5/8] system deps     %s  %s\n" "$(step_icon "${STEP_SYSTEM}")" "${STEP_SYSTEM_NOTE}"
    printf "│  [6/8] GPU/accel       %s  %s\n" "$(step_icon "${STEP_GPU}")" "${STEP_GPU_NOTE}"
    printf "│  [7/8] reranker model  %s  %s\n" "$(step_icon "${STEP_RERANKER}")" "${STEP_RERANKER_NOTE}"
    printf "│  [8/8] embedder model  %s  %s\n" "$(step_icon "${STEP_EMBEDDER}")" "${STEP_EMBEDDER_NOTE}"
    echo "└─────────────────────────────────────────────────────────────┘"
}

# ---------------------------------------------------------------------------
# Проверка Python
# ---------------------------------------------------------------------------

if ! command -v "${PYTHON}" &>/dev/null; then
    echo "WARNING: ${PYTHON} not found, falling back to python3"
    PYTHON="python3"
    STEP_PYTHON="WARN"
    STEP_PYTHON_NOTE="фоллбэк на python3"
fi

PYTHON_VERSION=$("${PYTHON}" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$("${PYTHON}" -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$("${PYTHON}" -c "import sys; print(sys.version_info.minor)")

echo "=== pdf-sidecar install ==="
echo "Python: $("${PYTHON}" --version) at $(command -v "${PYTHON}")"

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
    STEP_PYTHON="ERROR"
    STEP_PYTHON_NOTE="Python ${PYTHON_VERSION} не поддерживается (3.11–3.13 требуется)"
    STEP_VENV="SKIP" ; STEP_DEPS="SKIP" ; STEP_DETECTRON="SKIP"
    STEP_SYSTEM="SKIP" ; STEP_GPU="SKIP" ; STEP_RERANKER="SKIP" ; STEP_EMBEDDER="SKIP"
    print_summary
    exit 1
fi

if [[ "${PYTHON_MAJOR}" -eq 3 && "${PYTHON_MINOR}" -lt 11 ]]; then
    echo "WARNING: Python ${PYTHON_VERSION} < 3.11, могут быть проблемы совместимости."
    STEP_PYTHON="WARN"
    STEP_PYTHON_NOTE="Python ${PYTHON_VERSION} < 3.11, могут быть проблемы"
fi

[[ "${STEP_PYTHON}" == "OK" ]] && STEP_PYTHON_NOTE="Python ${PYTHON_VERSION}"
echo "Python ${PYTHON_VERSION} — OK"

# ---------------------------------------------------------------------------
# [1/8] venv
# ---------------------------------------------------------------------------
if [[ -d "${VENV_DIR}" ]]; then
    VENV_PYTHON_VER=$("${VENV_DIR}/bin/python" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "unknown")
    if [[ "${VENV_PYTHON_VER}" != "${PYTHON_VERSION}" ]]; then
        echo "[1/8] venv существует но использует Python ${VENV_PYTHON_VER}."
        echo "      Пересоздаём с Python ${PYTHON_VERSION}…"
        rm -rf "${VENV_DIR}"
        "${PYTHON}" -m venv "${VENV_DIR}"
        STEP_VENV_NOTE="пересоздан (${VENV_PYTHON_VER} → ${PYTHON_VERSION})"
    else
        echo "[1/8] venv уже существует (Python ${VENV_PYTHON_VER}) — пропускаем"
        STEP_VENV_NOTE="существует (Python ${VENV_PYTHON_VER})"
    fi
else
    echo "[1/8] Создаём venv в ${VENV_DIR}…"
    "${PYTHON}" -m venv "${VENV_DIR}"
    STEP_VENV_NOTE="создан (Python ${PYTHON_VERSION})"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
echo "      Active Python: $(python --version) at $(command -v python)"

# ---------------------------------------------------------------------------
# [2/8] pip upgrade (отдельного шага нет, входит в venv)
# ---------------------------------------------------------------------------
echo "[2/8] Upgrading pip…"
pip install --upgrade pip --quiet

# ---------------------------------------------------------------------------
# [3/8] requirements.txt
# ---------------------------------------------------------------------------
echo "[3/8] Installing requirements.txt…"
if pip install -r "${SCRIPT_DIR}/requirements.txt"; then
    STEP_DEPS_NOTE="requirements.txt"
else
    STEP_DEPS="ERROR"
    STEP_DEPS_NOTE="ошибка установки"
fi

# ---------------------------------------------------------------------------
# [4/8] detectron2
# ---------------------------------------------------------------------------
echo "[4/8] Installing detectron2…"
if python -c "import detectron2" 2>/dev/null; then
    echo "      detectron2 already installed — OK"
    STEP_DETECTRON_NOTE="already installed"
else
    echo "      Compiling from GitHub source (займёт 3–5 минут)…"
    if pip install --no-build-isolation 'git+https://github.com/facebookresearch/detectron2.git'; then
        echo "      detectron2 installed OK"
        STEP_DETECTRON_NOTE="установлен"
    else
        echo "      WARNING: detectron2 не установился."
        echo "      unstructured hi_res требует detectron2 или yolox."
        echo "      yolox (ONNX-based) используется по умолчанию — продолжаем."
        echo "      Если нужен detectron2, запустите вручную:"
        echo "        pip install --no-build-isolation 'git+https://github.com/facebookresearch/detectron2.git'"
        STEP_DETECTRON="WARN"
        STEP_DETECTRON_NOTE="не установился, используется yolox"
    fi
fi

# ---------------------------------------------------------------------------
# [5/8] Системные зависимости
# ---------------------------------------------------------------------------
echo "[5/8] Checking system dependencies…"
SYSTEM_MISSING=()

if ! command -v gs &>/dev/null; then
    echo "      ✗ ghostscript не найден"
    SYSTEM_MISSING+=("ghostscript")
else
    echo "      ✓ ghostscript: $(gs --version 2>/dev/null || echo unknown)"
fi

if ! command -v tesseract &>/dev/null; then
    echo "      ✗ tesseract не найден"
    SYSTEM_MISSING+=("tesseract")
else
    echo "      ✓ tesseract: $(tesseract --version 2>&1 | head -1)"
    if ! tesseract --list-langs 2>/dev/null | grep -q "rus"; then
        echo "      ✗ Русский язык OCR отсутствует (пакет tesseract-lang)"
        SYSTEM_MISSING+=("tesseract-lang")
    else
        echo "      ✓ Russian OCR: OK"
    fi
fi

if ! command -v pdftoppm &>/dev/null; then
    echo "      ✗ poppler не найден"
    SYSTEM_MISSING+=("poppler")
else
    echo "      ✓ poppler: OK"
fi

if [[ ${#SYSTEM_MISSING[@]} -gt 0 ]]; then
    echo ""
    echo "      Отсутствуют системные зависимости: ${SYSTEM_MISSING[*]}"
    echo ""

    if command -v brew &>/dev/null; then
        # Формируем список пакетов для brew
        # tesseract-lang — это отдельный brew-пакет
        BREW_PKGS=()
        for pkg in "${SYSTEM_MISSING[@]}"; do
            case "${pkg}" in
                ghostscript)  BREW_PKGS+=("ghostscript") ;;
                tesseract)    BREW_PKGS+=("tesseract") ;;
                tesseract-lang) BREW_PKGS+=("tesseract-lang") ;;
                poppler)      BREW_PKGS+=("poppler") ;;
            esac
        done

        echo "      Установить через Homebrew?"
        echo "        brew install ${BREW_PKGS[*]}"
        echo ""
        printf "      Продолжить установку? [y/N] "
        # Читаем ответ даже если stdin не терминал (запуск из UI)
        if [ -t 0 ]; then
            read -r BREW_ANSWER
        else
            BREW_ANSWER="n"
            echo "(не интерактивный режим — пропускаю)"
        fi

        if [[ "${BREW_ANSWER}" == "y" || "${BREW_ANSWER}" == "Y" ]]; then
            echo "      → brew install ${BREW_PKGS[*]}"
            if brew install "${BREW_PKGS[@]}"; then
                echo "      ✓ Системные зависимости установлены."
                STEP_SYSTEM_NOTE="ghostscript, tesseract+rus, poppler"
                # Перепроверяем после установки
                SYSTEM_MISSING=()
                command -v gs &>/dev/null       || SYSTEM_MISSING+=("ghostscript")
                command -v tesseract &>/dev/null || SYSTEM_MISSING+=("tesseract")
                command -v pdftoppm &>/dev/null  || SYSTEM_MISSING+=("poppler")
                if [[ ${#SYSTEM_MISSING[@]} -gt 0 ]]; then
                    STEP_SYSTEM="WARN"
                    STEP_SYSTEM_NOTE="всё ещё нет: ${SYSTEM_MISSING[*]}"
                fi
            else
                echo "      ✗ brew install завершился с ошибкой."
                echo "        Установите вручную и запустите install.sh повторно."
                STEP_SYSTEM="ERROR"
                STEP_SYSTEM_NOTE="brew install не удался"
            fi
        else
            echo "      Пропускаю установку системных зависимостей."
            echo "      Установите вручную и запустите install.sh повторно:"
            echo "        brew install ${BREW_PKGS[*]}"
            STEP_SYSTEM="ERROR"
            STEP_SYSTEM_NOTE="нет: $(IFS=', '; echo "${SYSTEM_MISSING[*]}")"
        fi
    else
        # brew недоступен — просто сообщаем что делать
        echo "      Homebrew не найден. Установите зависимости вручную:"
        echo "        ghostscript, tesseract, tesseract-lang, poppler"
        STEP_SYSTEM="ERROR"
        STEP_SYSTEM_NOTE="нет: $(IFS=', '; echo "${SYSTEM_MISSING[*]}")"
    fi
else
    STEP_SYSTEM_NOTE="ghostscript, tesseract+rus, poppler"
fi

# ---------------------------------------------------------------------------
# [6/8] GPU/акселерация
# ---------------------------------------------------------------------------
echo "[6/8] Checking GPU/acceleration…"
GPU_RESULT=$(python - << 'PYCHECK'
import sys, json
result = {"mps": False, "coreml": False, "torch_ver": "", "ort_ver": ""}

try:
    import torch
    result["mps"] = torch.backends.mps.is_available()
    result["torch_ver"] = torch.__version__
    print(f"  {'\u2713' if result['mps'] else '\u2717'} PyTorch MPS: {'\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d' if result['mps'] else '\u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d'} (torch {result['torch_ver']})", file=sys.stderr)
except ImportError:
    print("  PyTorch не установлен", file=sys.stderr)

try:
    import onnxruntime as ort
    providers = ort.get_available_providers()
    result["coreml"] = 'CoreMLExecutionProvider' in providers
    result["ort_ver"] = ort.__version__
    print(f"  {'\u2713' if result['coreml'] else '\u25cb'} ONNX CoreML: {'\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d' if result['coreml'] else '\u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d (CPU)'} (ort {result['ort_ver']})", file=sys.stderr)
    if not result["coreml"]:
        print("  Для CoreML нужна кастомная сборка onnxruntime --use_coreml", file=sys.stderr)
except ImportError:
    print("  onnxruntime не установлен", file=sys.stderr)

import json
print(json.dumps(result))
PYCHECK
)

MPS=$(echo "${GPU_RESULT}" | python3 -c "import sys,json; d=json.load(sys.stdin); print('yes' if d.get('mps') else 'no')" 2>/dev/null || echo "no")
COREML=$(echo "${GPU_RESULT}" | python3 -c "import sys,json; d=json.load(sys.stdin); print('yes' if d.get('coreml') else 'no')" 2>/dev/null || echo "no")

if [[ "${MPS}" == "yes" && "${COREML}" == "yes" ]]; then
    STEP_GPU_NOTE="MPS ✓  CoreML ✓"
elif [[ "${MPS}" == "yes" ]]; then
    STEP_GPU_NOTE="MPS ✓  CoreML — (CPU)"
    STEP_GPU="WARN"
elif [[ "${COREML}" == "yes" ]]; then
    STEP_GPU_NOTE="MPS —  CoreML ✓"
    STEP_GPU="WARN"
else
    STEP_GPU_NOTE="MPS —  CoreML — (всё CPU)"
    STEP_GPU="WARN"
fi

# ---------------------------------------------------------------------------
# [7/8] reranker-модель
# ---------------------------------------------------------------------------
if [[ "${SKIP_RERANKER}" == "1" ]]; then
    echo "[7/8] Reranker model download — пропущено (SKIP_RERANKER=1)"
    STEP_RERANKER="SKIP"
    STEP_RERANKER_NOTE="SKIP_RERANKER=1"
else
    RERANKER_MODEL_ID="${RERANKER_MODEL_ID:-BAAI/bge-reranker-v2-m3}"
    echo "[7/8] Pre-downloading reranker model '${RERANKER_MODEL_ID}'…"
    echo "      (первая загрузка — ~1.1 GB, последующие берутся из кэша)"
    if python - << PYRERANKER
import sys, os
os.environ.setdefault("RERANKER_MODEL_ID", "${RERANKER_MODEL_ID}")
try:
    from sentence_transformers import CrossEncoder
    model_id = os.environ["RERANKER_MODEL_ID"]
    print(f"  Loading {model_id}...")
    CrossEncoder(model_id)
    print(f"  ✓ Reranker model ready: {model_id}")
except Exception as e:
    print(f"  ✗ Reranker model download failed: {e}", file=sys.stderr)
    sys.exit(1)
PYRERANKER
    then
        echo "      Reranker — OK"
        STEP_RERANKER_NOTE="${RERANKER_MODEL_ID}"
    else
        echo "      WARNING: не удалось загрузить reranker-модель."
        echo "      Проверьте интернет и HuggingFace Hub."
        echo "      /rerank endpoint будет возвращать 503 пока модель не загружена."
        STEP_RERANKER="WARN"
        STEP_RERANKER_NOTE="не загрузилась, /rerank вернёт 503"
    fi
fi

# ---------------------------------------------------------------------------
# [8/8] embedder-модель
# ---------------------------------------------------------------------------
if [[ "${SKIP_EMBEDDER}" == "1" ]]; then
    echo "[8/8] Embedder model download — пропущено (SKIP_EMBEDDER=1)"
    STEP_EMBEDDER="SKIP"
    STEP_EMBEDDER_NOTE="SKIP_EMBEDDER=1"
else
    EMBEDDER_MODEL_ID="${EMBEDDER_MODEL_ID:-BAAI/bge-m3}"
    echo "[8/8] Pre-downloading embedder model '${EMBEDDER_MODEL_ID}'…"
    echo "      (первая загрузка — ~570 MB, последующие берутся из кэша HuggingFace)"
    if python - << PYEMBEDDER
import sys, os
os.environ.setdefault("EMBEDDER_MODEL_ID", "${EMBEDDER_MODEL_ID}")
try:
    from sentence_transformers import SentenceTransformer
    model_id = os.environ["EMBEDDER_MODEL_ID"]
    print(f"  Loading {model_id}...")
    m = SentenceTransformer(model_id, device="cpu")
    dim = m.get_sentence_embedding_dimension()
    print(f"  ✓ Embedder model ready: {model_id} dim={dim}")
except Exception as e:
    print(f"  ✗ Embedder model download failed: {e}", file=sys.stderr)
    sys.exit(1)
PYEMBEDDER
    then
        echo "      Embedder — OK"
        STEP_EMBEDDER_NOTE="${EMBEDDER_MODEL_ID}"
    else
        echo "      WARNING: не удалось загрузить embedder-модель."
        echo "      Проверьте интернет и HuggingFace Hub."
        echo "      /embeddings endpoint будет возвращать 503 пока модель не загружена."
        STEP_EMBEDDER="WARN"
        STEP_EMBEDDER_NOTE="не загрузилась, /embeddings вернёт 503"
    fi
fi

# ---------------------------------------------------------------------------
# Итоговая таблица
# ---------------------------------------------------------------------------
print_summary

# Дополнительная инфо
 echo ""
echo "Запуск:  ./start.sh"
echo "Статус:  ./status.sh"
echo "Логи:    tail -f logs/sidecar.log"
echo ""
echo "Проверка reranker endpoint:"
echo "  curl -X POST http://localhost:8765/rerank \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"query\": \"тест\", \"documents\": [\"doc1\", \"doc2\"]}'"
echo ""
echo "Проверка embedder endpoint:"
echo "  curl -X POST http://localhost:8765/embeddings \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"model\": \"BAAI/bge-m3\", \"input\": \"тестовый текст\"}'"
