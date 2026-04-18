import logging
import os
import subprocess
from pathlib import Path

from src.core.config import settings

logger = logging.getLogger(__name__)


class PushTask:
    """Отправка последнего пакета обновлений на сервер с фронтендом через rsync."""

    def __init__(self):
        self.dist_dir  = settings.paths.dist_dir
        self.host      = os.environ.get('DELIVERY_HOST', '')
        self.user      = os.environ.get('DELIVERY_USER', 'user')
        self.inbox     = os.environ.get('DELIVERY_INBOX', '/home/user/repikurr/inbox')
        self.ssh_key   = os.environ.get('DELIVERY_SSH_KEY', '/root/.ssh/id_rsa')

    def get_latest_package(self) -> Path | None:
        packages = sorted(self.dist_dir.glob('pikurr_update_*.zip'))
        return packages[-1] if packages else None

    def run(self):
        if not self.host:
            logger.warning("DELIVERY_HOST не задан — пропускаем отправку.")
            return

        package = self.get_latest_package()
        if not package:
            raise FileNotFoundError(f"Нет пакетов в {self.dist_dir}")

        dest = f"{self.user}@{self.host}:{self.inbox}/"
        logger.info(f"Отправка {package.name} → {dest}")

        cmd = [
            'rsync', '-avz', '--progress',
            '-e', f'ssh -i {self.ssh_key} -o StrictHostKeyChecking=no',
            str(package),
            dest,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            logger.info(result.stdout.strip())
        if result.returncode != 0:
            raise RuntimeError(f"rsync завершился с ошибкой:\n{result.stderr}")

        logger.info(f"Готово: {package.name} → {dest}")
        print(f"PUSHED: {package.name} → {dest}")


def task_push():
    PushTask().run()


if __name__ == "__main__":
    task_push()
