#!/usr/bin/env python3
"""Mercer — интерактивный генератор .env при первом make setup.

Только stdlib. Идемпотентен: спрашивает только пустые/placeholder переменные.

Запускается через Makefile с уже найденным совместимым интерпретатором
(Python 3.11–3.13). Собственная проверка версии здесь не нужна.
"""
import sys
import base64
import getpass
import os
import platform
import re
import secrets
from pathlib import Path

# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

# ---------------------------------------------------------------------------
# Утилиты генерации
# ---------------------------------------------------------------------------

def generate_fernet_key() -> str:
    """urlsafe base64 от 32 байт → всегда ровно 44 символа."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def generate_password() -> str:
    return secrets.token_urlsafe(16)


# ---------------------------------------------------------------------------
# Чтение / запись .env
# ---------------------------------------------------------------------------

def read_env(path: Path) -> dict[str, str]:
    """Парсит KEY=VALUE, игнорирует комментарии и пустые строки."""
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def set_env_value(content: str, key: str, value: str) -> str:
    """Заменяет строку KEY=... в тексте. Если ключа нет — добавляет в конец."""
    pattern = rf"^{re.escape(key)}=.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        return re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
    # Ключа нет — добавляем
    if content and not content.endswith("\n"):
        content += "\n"
    return content + f"{key}={value}\n"


# ---------------------------------------------------------------------------
# Логика «переменная уже задана»
# ---------------------------------------------------------------------------

# Переменные, которые compute_env.py вычисляет автоматически —
# их наличие любого значения не считается «уже заданным» для диалога.
_AUTO_KEYS = {"INSTALL_MODE", "AGENT_MODE", "COMPOSE_PROFILES", "HOST_AGENT_URL"}

def is_set(key: str, val: str) -> bool:
    """True если значение считается «уже заданным» (не placeholder)."""
    if not val:
        return False
    # Авто-ключи: любое значение считается placeholder'ом — всегда вычисляются заново,
    # кроме INSTALL_MODE, который задаётся интерактивно один раз.
    # Для прочих авто-ключей пропускаем проверку здесь (обрабатываются в compute-блоке).
    placeholders = {
        "changeme",
        "<generate with: python -c \"import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())\">",  # noqa: E501
    }
    if val in placeholders:
        return False
    if val.startswith("<") and val.endswith(">"):
        return False
    if key == "ENCRYPTION_KEY" and len(val) != 44:
        return False
    return True


# ---------------------------------------------------------------------------
# Интерактивный диалог
# ---------------------------------------------------------------------------

COLOR_GREEN  = "\033[0;32m"
COLOR_YELLOW = "\033[0;33m"
COLOR_CYAN   = "\033[0;36m"
COLOR_RESET  = "\033[0m"


def cprint(color: str, msg: str) -> None:
    print(f"{color}{msg}{COLOR_RESET}")


def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    """Задаёт вопрос, возвращает ответ (или default при пустом вводе)."""
    display_default = f" [{default}]" if default else ""
    full_prompt = f"  {prompt}{display_default}: "
    while True:
        try:
            if secret:
                val = getpass.getpass(full_prompt)
            else:
                val = input(full_prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit("\nПрервано пользователем.")
        val = val.strip()
        if not val and default:
            return default
        if val:
            return val
        print("  Значение не может быть пустым.")


def ask_install_mode(current: str) -> str:
    """Интерактивный выбор INSTALL_MODE."""
    options = {"1": "full", "2": "no-db-api", "3": "db-api-only"}
    cprint(COLOR_CYAN, "\n  Режим установки:")
    print("    1) full        — все сервисы включая db-api-server (LanceDB HTTP)")
    print("    2) no-db-api   — без db-api-server (внешний STORAGE_API_URL)")
    print("    3) db-api-only — только db-api-server")
    default_num = {v: k for k, v in options.items()}.get(current, "1")
    while True:
        try:
            choice = input(f"  Выберите [1/2/3] [{default_num}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit("\nПрервано пользователем.")
        if not choice:
            choice = default_num
        if choice in options:
            return options[choice]
        print("  Введите 1, 2 или 3.")


def ask_password(current: str) -> str:
    """Предлагает сгенерировать пароль или ввести свой."""
    cprint(COLOR_CYAN, "\n  POSTGRES_PASSWORD:")
    print("    g) сгенерировать автоматически")
    print("    c) ввести свой")
    while True:
        try:
            choice = input("  Выберите [g/c] [g]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit("\nПрервано пользователем.")
        if not choice or choice == "g":
            pwd = generate_password()
            cprint(COLOR_GREEN, f"  ✓ Сгенерирован пароль (сохранён в .env)")
            return pwd
        if choice == "c":
            return ask("Введите пароль", secret=True)
        print("  Введите g или c.")


def ask_vaults_path(current: str) -> str:
    """Запрашивает абсолютный путь до папки-хранилища файлов."""
    cprint(COLOR_CYAN, "\n  VAULTS_PATH — путь до папки с файлами на хосте,")
    print("    где будут создаваться хранилища под индексируемые файлы.")
    print("    Эта папка будет примонтирована в rag-indexer как /data/vaults")
    print("    Укажите абсолютный путь, например: /home/user/mercer-vaults")
    default = current or str(Path.home() / "mercer-vaults")
    while True:
        val = ask("Абсолютный путь", default=default)
        if not os.path.isabs(val):
            print("  Путь должен быть абсолютным (начинаться с /).")
            continue
        if not os.path.exists(val):
            try:
                choice = input(f"  Папка не существует. Создать? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                sys.exit("\nПрервано пользователем.")
            if choice == "y":
                os.makedirs(val, exist_ok=True)
                cprint(COLOR_GREEN, f"  ✓ Создана папка: {val}")
        return val


# ---------------------------------------------------------------------------
# Вычисление авто-переменных
# ---------------------------------------------------------------------------

def compute_agent_mode() -> str:
    s = platform.system()
    if s == "Darwin":
        return "host"
    if s == "Linux":
        return "docker"
    return "host-win"  # Windows — предупреждение, не реализовано


def compute_compose_profiles(install_mode: str) -> str:
    return {
        "full": "with-db-api",
        "no-db-api": "core",
        "db-api-only": "db-api-only",
    }.get(install_mode, "with-db-api")


def compute_host_agent_url(agent_mode: str) -> str:
    if agent_mode in ("host", "host-win"):
        return "http://host.docker.internal:9090"
    return "http://host-agent:9090"


# ---------------------------------------------------------------------------
# Основной поток
# ---------------------------------------------------------------------------

def main() -> None:
    # 1. Проверяем .env.example
    if not ENV_EXAMPLE.exists():
        sys.exit(f"ERROR: {ENV_EXAMPLE} не найден. Убедитесь что вы запускаете из корня проекта.")

    # 2. Инициализируем .env из .env.example если его нет
    if not ENV_FILE.exists():
        ENV_FILE.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        cprint(COLOR_GREEN, f"✓ Создан {ENV_FILE} из .env.example")

    content = ENV_FILE.read_text(encoding="utf-8")
    current = read_env(ENV_FILE)

    # 3. Проверяем: все ли интерактивные переменные уже заданы?
    # INSTALL_MODE всегда проверяем через is_set — пустая строка запустит диалог.
    interactive_keys = ["INSTALL_MODE", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "VAULTS_PATH"]
    needs_dialog = any(not is_set(k, current.get(k, "")) for k in interactive_keys)

    # Если ещё и STORAGE_API_URL пуст при no-db-api
    if current.get("INSTALL_MODE") == "no-db-api" and not is_set("STORAGE_API_URL", current.get("STORAGE_API_URL", "")):
        needs_dialog = True

    # Авто-переменные — проверяем отдельно
    need_auto = (
        not is_set("ENCRYPTION_KEY", current.get("ENCRYPTION_KEY", ""))
        or not is_set("HOST_AGENT_TOKEN", current.get("HOST_AGENT_TOKEN", ""))
    )

    if not needs_dialog and not need_auto:
        # Всё уже задано — молча выходим
        return

    cprint(COLOR_GREEN, "\n=== Mercer — настройка окружения ===")

    # 4. Интерактивный диалог
    if needs_dialog:
        # INSTALL_MODE — спрашиваем всегда когда не задан (пустая строка = не задан)
        if not is_set("INSTALL_MODE", current.get("INSTALL_MODE", "")):
            install_mode = ask_install_mode(current.get("INSTALL_MODE", ""))
        else:
            install_mode = current["INSTALL_MODE"]
        content = set_env_value(content, "INSTALL_MODE", install_mode)

        # POSTGRES_USER
        if not is_set("POSTGRES_USER", current.get("POSTGRES_USER", "")):
            pg_user = ask("POSTGRES_USER", default="raguser")
            content = set_env_value(content, "POSTGRES_USER", pg_user)

        # POSTGRES_PASSWORD
        if not is_set("POSTGRES_PASSWORD", current.get("POSTGRES_PASSWORD", "")):
            pg_pwd = ask_password(current.get("POSTGRES_PASSWORD", ""))
            content = set_env_value(content, "POSTGRES_PASSWORD", pg_pwd)

        # POSTGRES_DB
        if not is_set("POSTGRES_DB", current.get("POSTGRES_DB", "")):
            pg_db = ask("POSTGRES_DB", default="ragplatform")
            content = set_env_value(content, "POSTGRES_DB", pg_db)

        # STORAGE_API_URL — только при no-db-api
        if install_mode == "no-db-api" and not is_set("STORAGE_API_URL", current.get("STORAGE_API_URL", "")):
            storage_url = ask("STORAGE_API_URL (URL внешнего LanceDB HTTP API)")
            content = set_env_value(content, "STORAGE_API_URL", storage_url)

        # VAULTS_PATH
        if not is_set("VAULTS_PATH", current.get("VAULTS_PATH", "")):
            vaults_path = ask_vaults_path(current.get("VAULTS_PATH", ""))
            content = set_env_value(content, "VAULTS_PATH", vaults_path)
        else:
            vaults_path = current["VAULTS_PATH"]
    else:
        install_mode = current.get("INSTALL_MODE", "full")
        vaults_path = current.get("VAULTS_PATH", "")

    # 5. Авто-переменные
    # ENCRYPTION_KEY — не перезаписывать если уже ровно 44 символа
    enc_key = current.get("ENCRYPTION_KEY", "")
    if not is_set("ENCRYPTION_KEY", enc_key):
        enc_key = generate_fernet_key()
        content = set_env_value(content, "ENCRYPTION_KEY", enc_key)
        cprint(COLOR_GREEN, "  ✓ ENCRYPTION_KEY сгенерирован")

    # HOST_AGENT_TOKEN — не перезаписывать если задан и не changeme
    token = current.get("HOST_AGENT_TOKEN", "")
    if not is_set("HOST_AGENT_TOKEN", token):
        token = generate_token()
        content = set_env_value(content, "HOST_AGENT_TOKEN", token)
        cprint(COLOR_GREEN, "  ✓ HOST_AGENT_TOKEN сгенерирован")

    # AGENT_MODE — всегда вычисляется из текущей ОС
    agent_mode = compute_agent_mode()
    content = set_env_value(content, "AGENT_MODE", agent_mode)

    # COMPOSE_PROFILES — из INSTALL_MODE
    profiles = compute_compose_profiles(install_mode)
    content = set_env_value(content, "COMPOSE_PROFILES", profiles)

    # HOST_AGENT_URL — из AGENT_MODE
    agent_url = compute_host_agent_url(agent_mode)
    content = set_env_value(content, "HOST_AGENT_URL", agent_url)

    # Windows — предупреждение
    if platform.system() == "Windows":
        cprint(COLOR_YELLOW, "\n  ⚠ Windows: host-agent не реализован. "
               "Запустите агент вручную перед make up.")

    # 6. Сохраняем
    ENV_FILE.write_text(content, encoding="utf-8")
    cprint(COLOR_GREEN, f"\n✓ .env сохранён ({ENV_FILE})")
    cprint(COLOR_GREEN, f"  INSTALL_MODE={install_mode}  →  COMPOSE_PROFILES={profiles}")
    cprint(COLOR_GREEN, f"  AGENT_MODE={agent_mode}  →  HOST_AGENT_URL={agent_url}")
    cprint(COLOR_GREEN, f"  VAULTS_PATH={vaults_path}")
    print()


if __name__ == "__main__":
    main()
