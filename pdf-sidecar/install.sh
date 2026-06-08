#!/usr/bin/env bash
# =============================================================================
# pdf-sidecar / install.sh
# Устанавливает системные зависимости и Python-пакеты для pdf-sidecar.
# Запускать от имени пользователя с правами sudo (или root).
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Цвета
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[install]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}   $*"; }
err()  { echo -e "${RED}[error]${NC}  $*" >&2; }

# ---------------------------------------------------------------------------
# Определяем пакетный менеджер
# ---------------------------------------------------------------------------
detect_pkg_manager() {
    if command -v apt-get &>/dev/null; then
        echo "apt"
    elif command -v brew &>/dev/null; then
        echo "brew"
    elif command -v dnf &>/dev/null; then
        echo "dnf"
    elif command -v yum &>/dev/null; then
        echo "yum"
    else
        echo "unknown"
    fi
}

PKG_MGR=$(detect_pkg_manager)
log "Package manager detected: ${PKG_MGR}"

# ---------------------------------------------------------------------------
# Системные зависимости
# ---------------------------------------------------------------------------
install_system_deps() {
    log "Installing system dependencies..."

    case "${PKG_MGR}" in
        apt)
            sudo apt-get update -qq
            sudo apt-get install -y --no-install-recommends \
                ghostscript \
                tesseract-ocr \
                tesseract-ocr-rus \
                tesseract-ocr-eng \
                libpoppler-cpp-dev \
                poppler-utils \
                libmagic1 \
                libgl1 \
                libglib2.0-0
            ;;
        brew)
            # macOS — ghostscript обязателен для _normalize_with_ghostscript
            brew install ghostscript tesseract tesseract-lang poppler
            ;;
        dnf|yum)
            sudo ${PKG_MGR} install -y \
                ghostscript \
                tesseract \
                tesseract-langpack-rus \
                poppler-utils \
                file-libs
            ;;
        *)
            warn "Unknown package manager. Install manually: ghostscript, tesseract, poppler-utils"
            ;;
    esac

    log "System dependencies installed."
}

# ---------------------------------------------------------------------------
# Проверка наличия ghostscript после установки
# ---------------------------------------------------------------------------
check_ghostscript() {
    if command -v gs &>/dev/null; then
        GS_VER=$(gs --version 2>/dev/null || echo "unknown")
        log "Ghostscript OK: ${GS_VER}"
    else
        err "ghostscript (gs) not found in PATH after installation!"
        err "PDF normalization fallback will not work."
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Python-окружение
# ---------------------------------------------------------------------------
setup_python_env() {
    VENV_DIR="${SCRIPT_DIR}/.venv"

    if [ ! -d "${VENV_DIR}" ]; then
        log "Creating Python virtual environment at ${VENV_DIR}..."
        python3 -m venv "${VENV_DIR}"
    else
        log "Virtual environment already exists: ${VENV_DIR}"
    fi

    # Активируем
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"

    log "Upgrading pip..."
    pip install --upgrade pip --quiet

    log "Installing Python dependencies from requirements.txt..."
    pip install -r "${SCRIPT_DIR}/requirements.txt"

    log "Python environment ready."
}

# ---------------------------------------------------------------------------
# Загрузка языковых данных для spaCy
# ---------------------------------------------------------------------------
download_spacy_models() {
    VENV_DIR="${SCRIPT_DIR}/.venv"
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"

    log "Downloading spaCy language models..."
    python3 -m spacy download en_core_web_sm  2>/dev/null || warn "en_core_web_sm already installed or failed"
    python3 -m spacy download ru_core_news_sm 2>/dev/null || warn "ru_core_news_sm already installed or failed"
    log "spaCy models OK."
}

# ---------------------------------------------------------------------------
# Загрузка NLTK-данных (нужны unstructured)
# ---------------------------------------------------------------------------
download_nltk_data() {
    VENV_DIR="${SCRIPT_DIR}/.venv"
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"

    log "Downloading NLTK data..."
    python3 - <<'PYEOF'
import nltk
for pkg in ["punkt", "punkt_tab", "averaged_perceptron_tagger", "averaged_perceptron_tagger_eng"]:
    try:
        nltk.download(pkg, quiet=True)
    except Exception as e:
        print(f"NLTK warning: {pkg}: {e}")
PYEOF
    log "NLTK data OK."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    log "=== pdf-sidecar install ==="
    install_system_deps
    check_ghostscript
    setup_python_env
    download_spacy_models
    download_nltk_data
    log "=== Installation complete ==="
    log "Run: ./start.sh"
}

main "$@"
