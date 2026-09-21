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

import fcntl
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
FAILED_DIR = SCRIPT_DIR / "failed"
ENV_FILE   = SCRIPT_DIR / "deliver.env"
DELIVER    = SCRIPT_DIR / "deliver.py"
PID_FILE   = SCRIPT_DIR / "watchdog.pid"
LOCK_FILE  = SCRIPT_DIR / "watchdog.lock"
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
        # deliver.py удаляет ZIP только при успехе, поэтому файл здесь ещё
        # существует. Раньше он оставался в inbox и заново проваливался при
        # каждом рестарте демона бесконечно (round19) — уносим его в failed/,
        # чтобы отравленный пакет не мешал обработке новых. Статус (ok=false)
        # deliver.py уже записал независимо от этого переноса.
        if zip_path.exists():
            FAILED_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            dest = FAILED_DIR / f"{ts}_{zip_path.name}"
            try:
                zip_path.rename(dest)
                logger.error(f"ZIP перенесён в {dest}")
            except OSError as e:
                logger.error(f"Не удалось перенести {zip_path} в failed/: {e}")


def _acquire_lock():
    """Файловый лок (round21, A4) — без него два экземпляра watchdog видят
    один и тот же файл в inbox независимо друг от друга и оба вызывают
    deliver.py почти одновременно (гонка, описана в round20, воспроизведена
    на живом сервере в начале round21). flock держится открытым дескриптором
    на весь срок жизни процесса — переменная возвращается наружу, чтобы GC
    не закрыл файл и не снял лок раньше времени."""
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        owner_pid = PID_FILE.read_text().strip() if PID_FILE.exists() else "неизвестен"
        logger.error(f"Уже запущен другой экземпляр watchdog (pid {owner_pid}) — выхожу.")
        sys.exit(1)
    lock_fd.write(str(os.getpid()))
    lock_fd.flush()
    return lock_fd


def _file_key(path: Path):
    """(имя, размер, mtime) вместо просто имени (round21, A1).

    Раньше `seen` хранил только имя файла: если доставка падала и ZIP уезжал
    в failed/ (round20, задача 4), а оператор чинил причину и отправлял тот
    же пакет с тем же именем заново — watchdog видел знакомое имя и не делал
    ничего, без единой строки в логе (штатный сценарий "починили — повторили"
    ломался молча). Размер/mtime у нового файла отличаются от того, что уже
    обработан, поэтому новый файл с тем же именем корректно распознаётся как
    новый."""
    try:
        st = path.stat()
    except OSError:
        return None
    return (path.name, st.st_size, st.st_mtime)


def main():
    INBOX.mkdir(parents=True, exist_ok=True)
    lock_fd = _acquire_lock()  # держим ссылку — см. docstring _acquire_lock
    PID_FILE.write_text(str(os.getpid()))
    logger.info(f"Watchdog started (pid={os.getpid()}), watching {INBOX}, poll={POLL_SECS}s")

    # seen: ключи (имя, размер, mtime) пакетов, уже обработанных в этом
    # сеансе (успешно или нет — при неуспехе ZIP уносится в failed/, и
    # повторно попадает под глоб inbox только если это НОВЫЙ файл).
    # При старте НЕ добавляем сюда существующие файлы — deliver.py удаляет
    # ZIP после успешной доставки, поэтому любой файл в inbox при старте —
    # либо новый, либо ранее упавший (и оставшийся, а не в failed/) → нужно
    # попробовать снова.
    seen: set[tuple] = set()

    preexisting = sorted(INBOX.glob("pikurr_update_*.zip"))
    if preexisting:
        logger.info(f"Pre-existing packages (will process): {[f.name for f in preexisting]}")

    while True:
        extra_env = load_env(ENV_FILE)
        for zip_path in sorted(INBOX.glob("pikurr_update_*.zip")):
            key = _file_key(zip_path)
            if key is not None and key not in seen:
                seen.add(key)
                try:
                    process_zip(zip_path, extra_env)
                except Exception as e:
                    logger.exception(f"Unexpected error: {e}")
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
