#!/usr/bin/env python3
"""
watchdog.py — следит за папкой inbox, запускает deliver.py при появлении ZIP.

Не требует системных зависимостей (inotify-tools не нужен).

Запуск:
    python3 watchdog.py                       # блокирующий режим
    nohup python3 watchdog.py &               # фоновый режим

Остановить:
    kill $(cat ~/repikurr/watchdog.pid)
"""

import os
import sys
import time
import subprocess
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
INBOX      = SCRIPT_DIR / "inbox"
ENV_FILE   = SCRIPT_DIR / "deliver.env"
DELIVER    = SCRIPT_DIR / "deliver.py"
PID_FILE   = SCRIPT_DIR / "watchdog.pid"
LOG_FILE   = SCRIPT_DIR / "watchdog.log"
POLL_SECS  = 10   # частота проверки

# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%F %T",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE),
    ],
)
logger = logging.getLogger(__name__)


def load_env(env_file: Path) -> dict:
    """Читает KEY=VALUE из файла, возвращает dict."""
    env = {}
    if not env_file.exists():
        return env
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def process_zip(zip_path: Path, extra_env: dict):
    logger.info(f"Processing: {zip_path.name}")
    env = {**os.environ, **extra_env}
    result = subprocess.run(
        [sys.executable, str(DELIVER), str(zip_path)],
        env=env,
        capture_output=False,  # лог deliver.py идёт прямо в stdout/stderr
    )
    if result.returncode == 0:
        logger.info(f"Delivery SUCCESS: {zip_path.name}")
    else:
        logger.error(f"Delivery FAILED (exit {result.returncode}): {zip_path.name}")


def main():
    INBOX.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    logger.info(f"Watchdog started (pid={os.getpid()}), watching {INBOX}, poll={POLL_SECS}s")

    # seen: имена пакетов, которые уже успешно доставлены в этом сеансе.
    # При старте НЕ добавляем сюда существующие файлы — deliver.py удаляет ZIP
    # после успешной доставки, поэтому любой файл в inbox при старте —
    # либо новый, либо ранее упавший → нужно попробовать снова.
    seen: set[str] = set()

    preexisting = sorted(INBOX.glob("pikurr_update_*.zip"))
    if preexisting:
        logger.info(f"Pre-existing packages (will process): {[f.name for f in preexisting]}")

    while True:
        extra_env = load_env(ENV_FILE)
        for zip_path in sorted(INBOX.glob("pikurr_update_*.zip")):
            if zip_path.name not in seen:
                seen.add(zip_path.name)
                try:
                    process_zip(zip_path, extra_env)
                except Exception as e:
                    logger.exception(f"Unexpected error: {e}")
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
