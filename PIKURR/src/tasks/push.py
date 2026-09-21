import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path, PurePosixPath

from src.core.config import settings

logger = logging.getLogger(__name__)

# pikurr_update_{years_tag}_{YYYY-MM-DD_HH-MM}.zip — years_tag сам может
# содержать подчёркивания (напр. "2023_2024_2025"), поэтому имя разбирается
# не сплитом по "_", а по дате в конце.
_PACKAGE_DATE_RE = re.compile(r'^pikurr_update_.+_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2})\.zip$')


def _package_sort_key(path: Path) -> datetime:
    match = _PACKAGE_DATE_RE.match(path.name)
    if not match:
        raise ValueError(f"Не удалось разобрать дату из имени пакета: {path.name}")
    return datetime.strptime(match.group(1), '%Y-%m-%d_%H-%M')


class PushTask:
    """Отправка последнего пакета обновлений на сервер с фронтендом через rsync."""

    def __init__(self):
        self.dist_dir  = settings.paths.dist_dir
        self.host      = os.environ.get('DELIVERY_HOST', '')
        self.user      = os.environ.get('DELIVERY_USER', 'user')
        self.ssh_key   = os.environ.get('DELIVERY_SSH_KEY', '/root/.ssh/id_rsa')
        self.status_timeout = int(os.environ.get('DELIVERY_STATUS_TIMEOUT', '600'))
        # round22, задача 7: канал через rrsync (ограниченный ключ,
        # command=-диспетчер) — путь назначения фиксирован сервером, задавать
        # его с клиента бессмысленно (и rrsync создаст лишний подкаталог,
        # если его всё же передать — проверено на живом сервере). Пустой
        # DELIVERY_INBOX означает именно такой канал.
        self.inbox = os.environ.get('DELIVERY_INBOX', '/home/user/repikurr/inbox')
        # status/ у ограниченного пользователя доставки живёт в другом дереве
        # каталогов (не рядом с его inbox/, у него нет доступа к остальному
        # дереву watchdog) — нужен отдельный путь, а не "сосед inbox".
        self.status_dir = os.environ.get('DELIVERY_STATUS_DIR')
        # Раньше — всегда StrictHostKeyChecking=no (снимает защиту от подмены
        # хоста, round19/21 B3). DELIVERY_KNOWN_HOSTS — путь к файлу с
        # зафиксированным отпечатком; без него — старое поведение
        # (совместимость с уже настроенными целями типа 192.168.251.190).
        self.known_hosts = os.environ.get('DELIVERY_KNOWN_HOSTS')

    def get_latest_package(self) -> Path | None:
        packages = list(self.dist_dir.glob('pikurr_update_*.zip'))
        if not packages:
            return None
        # Сортировка по дате, разобранной из имени, а не лексикографически —
        # лексикографическая сортировка ломается, когда years_tag меняет длину
        # между прогонами (напр. "2023_2024" → "2023_2024_2025").
        return max(packages, key=_package_sort_key)

    def _ssh_opts(self) -> list[str]:
        if self.known_hosts:
            return ['-o', f'UserKnownHostsFile={self.known_hosts}', '-o', 'StrictHostKeyChecking=yes']
        return ['-o', 'StrictHostKeyChecking=no']

    def _ssh_base_cmd(self) -> list[str]:
        return ['ssh', '-i', self.ssh_key, *self._ssh_opts(), f'{self.user}@{self.host}']

    def _status_path(self, package_name: str) -> str:
        if self.status_dir:
            return str(PurePosixPath(self.status_dir) / f'{package_name}.json')
        # Старое поведение (без DELIVERY_STATUS_DIR) — status/ как сосед
        # inbox/ (deliver.py пишет туда же на целях без ограниченного
        # пользователя доставки, напр. 192.168.251.190).
        inbox_parent = PurePosixPath(self.inbox).parent
        return str(inbox_parent / 'status' / f'{package_name}.json')

    def _poll_status(self, package: Path, not_before: datetime) -> dict:
        """Опрашивает файл статуса, который deliver.py пишет на удалённой
        стороне после обработки пакета (успешной или нет). Без этого
        PushTask.run() считался успешным сразу после rsync, даже если
        доставка на сервере фактически проваливалась (см. round19).

        `not_before` отфильтровывает файл статуса, оставшийся от прошлой
        доставки пакета с тем же именем (при повторной отправке того же
        файла имя совпадает, и без проверки времени старый статус выглядит
        как подтверждение новой доставки — найдено на живом сервере при
        проверке идемпотентности, round20)."""
        status_path = self._status_path(package.name)
        deadline = time.monotonic() + self.status_timeout
        poll_interval = 5
        cmd = self._ssh_base_cmd() + [f'cat {status_path}']

        while time.monotonic() < deadline:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                try:
                    status = json.loads(result.stdout)
                except json.JSONDecodeError:
                    time.sleep(poll_interval)
                    continue
                if status.get('zip') == package.name:
                    try:
                        started_at = datetime.fromisoformat(status['started_at'])
                    except (KeyError, ValueError):
                        started_at = None
                    if started_at is None or started_at >= not_before:
                        return status
            time.sleep(poll_interval)

        raise TimeoutError(
            f"Не получено подтверждение доставки {package.name} за "
            f"{self.status_timeout}с (файл статуса {status_path} не появился, "
            f"не содержит нужный пакет, либо остался от прошлой доставки)."
        )

    def run(self):
        if not self.host:
            logger.warning("DELIVERY_HOST не задан — пропускаем отправку.")
            return

        package = self.get_latest_package()
        if not package:
            raise FileNotFoundError(f"Нет пакетов в {self.dist_dir}")

        dest = f"{self.user}@{self.host}:{self.inbox}/" if self.inbox else f"{self.user}@{self.host}:"
        logger.info(f"Отправка {package.name} → {dest}")
        push_started = datetime.now()

        cmd = [
            'rsync', '-avz', '--progress',
            '-e', 'ssh -i ' + self.ssh_key + ' ' + ' '.join(self._ssh_opts()),
            str(package),
            dest,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            logger.info(result.stdout.strip())
        if result.returncode != 0:
            raise RuntimeError(f"rsync завершился с ошибкой:\n{result.stderr}")

        logger.info(f"Передано: {package.name} → {dest}")
        logger.info(f"Ожидание подтверждения доставки (таймаут {self.status_timeout}с)...")

        status = self._poll_status(package, not_before=push_started)
        if not status.get('ok'):
            raise RuntimeError(
                f"Доставка {package.name} на сервере завершилась с ошибкой "
                f"(шаг: {status.get('step_failed')}): {status.get('error')}"
            )

        logger.info(
            f"Доставка подтверждена: {package.name}, гранул в мозаике после "
            f"обработки: {status.get('granules_after')}"
        )
        print(f"PUSHED: {package.name} → {dest}")


def task_push():
    PushTask().run()


if __name__ == "__main__":
    # См. пояснение в src/tasks/classify.py — без этого вызова
    # logger.info() при прямом запуске уходит в никуда.
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    task_push()
