#!/usr/bin/env python3
"""host-agent — HTTP-агент для управления pdf-sidecar с хоста.

Запускается на хосте (вне Docker), слушает на localhost:9090.
Backend из Docker обращается через host.docker.internal:9090.

Эндпоинты:
  GET  /health                — статус агента и sidecar
  POST /sidecar/start         — запустить sidecar
  POST /sidecar/stop          — остановить sidecar
  POST /sidecar/restart       — перезапустить sidecar
  GET  /sidecar/status        — статус процесса sidecar
  GET  /sidecar/install/stream — SSE-поток вывода install.sh
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

AGENT_PORT: int = int(os.getenv("HOST_AGENT_PORT", "9090"))
AGENT_TOKEN: str | None = os.getenv("HOST_AGENT_TOKEN")  # если не задан — auth отключена

# Путь к директории pdf-sidecar: по умолчанию — родительская папка этого файла (pdf-sidecar/).
DEFAULT_SIDECAR_DIR = Path(__file__).parent.parent.resolve()
SIDECAR_DIR: Path = Path(os.getenv("SIDECAR_DIR", str(DEFAULT_SIDECAR_DIR))).resolve()

PIDFILE: Path = SIDECAR_DIR / "sidecar.pid"
LOGFILE: Path = SIDECAR_DIR / "logs" / "sidecar.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [host-agent] %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------

app = FastAPI(title="Mercer Host Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # backend обращается с docker-адреса, не из браузера
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def check_token(x_agent_token: str | None = Header(default=None)) -> None:
    """Проверяет токен, если HOST_AGENT_TOKEN задан в окружении."""
    if AGENT_TOKEN and x_agent_token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Agent-Token")


# ---------------------------------------------------------------------------
# Вспомогательные функции для работы с процессом
# ---------------------------------------------------------------------------

def _read_pid() -> int | None:
    """Читает PID из файла. Возвращает None если файл не существует или невалиден."""
    if not PIDFILE.exists():
        return None
    try:
        return int(PIDFILE.read_text().strip())
    except (ValueError, OSError):
        return None


def _is_running(pid: int | None) -> bool:
    """Проверяет жив ли процесс с данным PID."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _sidecar_status() -> dict:
    """Возвращает текущий статус sidecar."""
    pid = _read_pid()
    running = _is_running(pid)
    if not running and PIDFILE.exists():
        try:
            PIDFILE.unlink(missing_ok=True)
        except OSError:
            pass
        pid = None
    venv_exists = (SIDECAR_DIR / ".venv").exists()
    return {
        "running": running,
        "pid": pid if running else None,
        "installed": venv_exists,
        "sidecar_dir": str(SIDECAR_DIR),
    }


async def _run_script(script: str, timeout: int = 30) -> dict:
    """Запускает скрипт в SIDECAR_DIR, ждёт завершения, возвращает результат."""
    script_path = SIDECAR_DIR / script
    if not script_path.exists():
        raise HTTPException(status_code=500, detail=f"{script} not found in {SIDECAR_DIR}")

    proc = await asyncio.create_subprocess_exec(
        "bash", str(script_path),
        cwd=str(SIDECAR_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(status_code=504, detail=f"{script} timed out after {timeout}s")

    output = stdout.decode(errors="replace") if stdout else ""
    return {
        "exit_code": proc.returncode,
        "output": output,
        "ok": proc.returncode == 0,
    }


async def _stream_script(script: str) -> AsyncIterator[str]:
    """Запускает скрипт и стримит его вывод как SSE-события."""
    script_path = SIDECAR_DIR / script
    if not script_path.exists():
        yield f"data: ERROR: {script} not found in {SIDECAR_DIR}\n\n"
        return

    proc = await asyncio.create_subprocess_exec(
        "bash", str(script_path),
        cwd=str(SIDECAR_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    assert proc.stdout is not None
    try:
        async for raw_line in proc.stdout:
            line = raw_line.decode(errors="replace").rstrip()
            yield f"data: {line}\n\n"
            await asyncio.sleep(0)
    finally:
        await proc.wait()
        exit_code = proc.returncode
        yield f"data: [DONE] exit_code={exit_code}\n\n"
        logger.info("%s finished with exit_code=%d", script, exit_code)


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> JSONResponse:
    status = _sidecar_status()
    return JSONResponse({
        "status": "ok",
        "service": "host-agent",
        "sidecar": status,
    })


@app.get("/sidecar/status")
async def sidecar_status(x_agent_token: str | None = Header(default=None)) -> JSONResponse:
    check_token(x_agent_token)
    return JSONResponse(_sidecar_status())


@app.post("/sidecar/start")
async def sidecar_start(x_agent_token: str | None = Header(default=None)) -> JSONResponse:
    check_token(x_agent_token)
    pid = _read_pid()
    if _is_running(pid):
        return JSONResponse({"ok": False, "message": f"Already running (PID {pid})"})
    result = await _run_script("start.sh", timeout=15)
    logger.info("sidecar start: exit_code=%d", result["exit_code"])
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result["output"])
    return JSONResponse({"ok": True, "message": "Started", "output": result["output"]})


@app.post("/sidecar/stop")
async def sidecar_stop(x_agent_token: str | None = Header(default=None)) -> JSONResponse:
    check_token(x_agent_token)
    result = await _run_script("stop.sh", timeout=20)
    logger.info("sidecar stop: exit_code=%d", result["exit_code"])
    return JSONResponse({"ok": result["ok"], "output": result["output"]})


@app.post("/sidecar/restart")
async def sidecar_restart(x_agent_token: str | None = Header(default=None)) -> JSONResponse:
    check_token(x_agent_token)
    stop_result = await _run_script("stop.sh", timeout=20)
    logger.info("sidecar restart/stop: exit_code=%d", stop_result["exit_code"])
    start_result = await _run_script("start.sh", timeout=15)
    logger.info("sidecar restart/start: exit_code=%d", start_result["exit_code"])
    if not start_result["ok"]:
        raise HTTPException(status_code=500, detail=start_result["output"])
    return JSONResponse({
        "ok": True,
        "message": "Restarted",
        "stop_output": stop_result["output"],
        "start_output": start_result["output"],
    })


@app.get("/sidecar/install/stream")
async def sidecar_install_stream(
    request: Request,
    x_agent_token: str | None = Header(default=None),
) -> StreamingResponse:
    """SSE-поток вывода install.sh. Клиент читает его через EventSource."""
    check_token(x_agent_token)
    logger.info("Starting install.sh stream")

    async def event_stream() -> AsyncIterator[str]:
        yield "data: [START] Running install.sh...\n\n"
        async for chunk in _stream_script("install.sh"):
            if await request.is_disconnected():
                logger.info("Client disconnected during install stream")
                return
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting host-agent on 127.0.0.1:%d", AGENT_PORT)
    logger.info("SIDECAR_DIR: %s", SIDECAR_DIR)
    logger.info("Auth token: %s", "enabled" if AGENT_TOKEN else "disabled (set HOST_AGENT_TOKEN)")

    uvicorn.run(
        "agent:app",
        host="127.0.0.1",
        port=AGENT_PORT,
        log_level="info",
    )
