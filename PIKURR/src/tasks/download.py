"""
Модуль загрузки тайлов с проверкой качества.

Обработка листа двухфазная:
  Фаза A — блоки geodzz через exportImage (fetch_block + slice_block).
  Фаза B — потайловый водопад для тайлов, которых нет после фазы A:
           geodzz exportImage (по тайлу) -> geodzz тайловый кэш -> Esri -> Google.

См. prompts/PROMPT_dzz_export_adapter.md.
"""
import json
import logging
import os
import random
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from PIL import Image

from src.core.config import settings
from ..services.db import DatabaseService
from ..services.dzz_export import (
    CatalogUnavailableError,
    fetch_block,
    fetch_tile_via_export,
    slice_block,
)
from ..utils.geo import getTileIndex
from ..utils.http_retry import SourceBannedError, request_with_policy
from ..utils.progress import ProgressReporter

logger = logging.getLogger(__name__)

thread_local = threading.local()

GRAY_RATIO_THRESHOLD = 0.7


def passes_quality(img: Image.Image) -> bool:
    """Тайл цветной (не залит одним оттенком серого/чёрным/белым)."""
    arr = np.array(img)
    if arr.ndim != 3:
        return False
    h, w, _ = arr.shape
    gray_ratio = np.sum(arr[:, :, 0] == arr[:, :, 1]) / (h * w)
    return gray_ratio < GRAY_RATIO_THRESHOLD


class DownloadBanned(Exception):
    """Источник вернул 403 — задача остановлена, ретраи не выполнялись."""


# Проба exportImage перед фазой A (round5, п.3). Тайл 17/75920/40800 — точка
# в границах покрытия, успешно получена через exportImage в прогоне
# 10.09.2026 до инцидента (файл сохранился в _pool/17_75920_40800.jpg).
_PROBE_X, _PROBE_Y, _PROBE_Z = 75920, 40800, 17


class DownloadTilesTask:
    def __init__(self):
        self.config = settings
        self.db = DatabaseService(settings)

        self.tile_services = settings.tileservices
        self.dzz_cfg = settings.dzz

        self.block_workers = self.dzz_cfg.block_workers
        self.block_delay = (self.dzz_cfg.block_delay_min, self.dzz_cfg.block_delay_max)
        self.tile_workers = self.dzz_cfg.tile_workers
        self.tile_delay = (self.dzz_cfg.tile_delay_min, self.dzz_cfg.tile_delay_max)

        # Выставляется при 403 от любого источника — новые запросы не стартуют.
        self._stop = threading.Event()

        # --- Предохранитель на систематический отказ каталога exportImage
        # (round5, п.2). Считаются только отказы на различающихся
        # координатах подряд; любой успешный ответ exportImage сбрасывает
        # счётчик. Отключение действует до конца прогона (не сбрасывается).
        self._export_disabled = threading.Event()
        self._export_lock = threading.Lock()
        self._export_fail_coords: set = set()
        self._export_fail_count = 0

        # --- Отдых по времени непрерывной работы + лимит длительности сессии
        # (уточнённое ТЗ round5(1), п.5).
        self._rest_lock = threading.Lock()
        self._work_window_start = time.monotonic()
        self._rest_after_seconds: Optional[float] = None  # выбирается лениво

        self._session_start = time.monotonic()
        self._session_stop = threading.Event()

        # Индикация прогресса (round6) — создаётся в run(), где известно total
        # листов; None при вызове process_block/process_tile напрямую (тесты).
        self.progress: Optional[ProgressReporter] = None

    def get_session(self) -> requests.Session:
        """Сессия requests, своя для потока. Host/Referer больше не подменяются
        на уровне сессии (баг: Host: gismap.by уходил на все хосты, включая
        server.arcgisonline.com и mt1.google.com) — Referer выставляется
        per-request под конкретный источник."""
        if not hasattr(thread_local, "session"):
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            })
            thread_local.session = session
        return thread_local.session

    # ---------- предохранитель exportImage (round5, п.2) ----------

    def _register_export_success(self) -> None:
        """Любой успешный ответ exportImage сбрасывает счётчик отказов
        (но не возвращает уже отключённый источник в строй)."""
        with self._export_lock:
            self._export_fail_coords.clear()
            self._export_fail_count = 0

    def _register_export_failure(self, coord_key: tuple, message: str, sheet_name: str) -> None:
        """Засчитывает отказ каталога exportImage, только если координата
        ещё не учтена — иначе реальная дыра в покрытии копила бы счётчик
        сама на себя и роняла источник без систематической причины."""
        with self._export_lock:
            if self._export_disabled.is_set():
                return
            if coord_key in self._export_fail_coords:
                return
            self._export_fail_coords.add(coord_key)
            self._export_fail_count += 1
            threshold = self.dzz_cfg.export_failure_threshold
            if self._export_fail_count >= threshold:
                self._export_disabled.set()
                logger.error(
                    f"exportImage отключён до конца прогона: {self._export_fail_count} "
                    f"отказов каталога на разных координатах подряд (порог {threshold}); "
                    f"лист {sheet_name}; последняя ошибка: {message}; оставшийся объём "
                    "будет получен через тайловый кэш geodzz, Esri и Google"
                )

    # ---------- отдых по времени непрерывной работы (round5(1), п.5) ----------

    def _pick_rest_after_seconds(self) -> float:
        return random.uniform(
            self.dzz_cfg.block_rest_after_min, self.dzz_cfg.block_rest_after_max
        ) * 60

    def _pick_rest_duration_seconds(self) -> float:
        return random.uniform(self.dzz_cfg.block_rest_min, self.dzz_cfg.block_rest_max)

    def _maybe_rest_after_block(self) -> None:
        """Отдых меряется временем непрерывной работы, а не числом блоков:
        время рендера блока плавает в разы в зависимости от того, сколько
        сцен мозаики он задевает, поэтому счёт блоками даёт непредсказуемый
        интервал в реальном времени — а для стороннего сервиса значение имеет
        именно оно."""
        with self._rest_lock:
            if self._rest_after_seconds is None:
                self._rest_after_seconds = self._pick_rest_after_seconds()
            elapsed = time.monotonic() - self._work_window_start
            if elapsed < self._rest_after_seconds:
                return
            rest_seconds = self._pick_rest_duration_seconds()

        logger.info(
            f"Отдых {rest_seconds:.0f}с после {elapsed / 60:.1f} мин непрерывной "
            "работы exportImage (снижение нагрузки на сторонний сервис, не "
            "связано с инцидентом 10.09 — см. "
            "prompts/PROMPT_dzz_export_round5(1).md, п.5)"
        )
        time.sleep(rest_seconds)
        if self.progress is not None:
            self.progress.note_idle(rest_seconds)

        with self._rest_lock:
            self._work_window_start = time.monotonic()
            self._rest_after_seconds = self._pick_rest_after_seconds()

    # ---------- лимит длительности сессии (round5(1), п.5) ----------

    def _session_limit_reached(self) -> bool:
        """По достижении DZZ__SESSION_MAX_MINUTES прогон завершается штатно —
        новые блоки/тайлы не начинаются, уже начатые дорабатываются. 0
        отключает ограничение."""
        max_minutes = self.dzz_cfg.session_max_minutes
        if not max_minutes:
            return False
        if self._session_stop.is_set():
            return True
        if time.monotonic() - self._session_start >= max_minutes * 60:
            self._session_stop.set()
        return self._session_stop.is_set()

    # ---------- проба перед фазой A (round5, п.3) ----------

    def _probe_export(self) -> None:
        """Один пробный запрос exportImage перед первым листом. Если каталог
        уже недоступен на старте — фаза A не выполняется ни для одного листа
        (экономит часы бесполезных запросов на сценарии «сервис лежал ещё до
        запуска»)."""
        session = self.get_session()
        try:
            img = fetch_tile_via_export(
                session, self.dzz_cfg.export_base, self.dzz_cfg.referer,
                _PROBE_X, _PROBE_Y, z=_PROBE_Z, delay_range=self.tile_delay,
            )
        except SourceBannedError as exc:
            # 401/403 — тот же сигнал остановки всей задачи, что и в фазах A/B.
            # Выставляем self._stop сами: run() увидит флаг перед первым
            # листом и завершится через штатный DownloadBanned.
            logger.error(str(exc))
            self._stop.set()
            return
        except CatalogUnavailableError as exc:
            logger.error(
                f"Проба exportImage перед фазой A не прошла: {exc}. exportImage "
                "отключён на весь прогон, используется потайловый водопад."
            )
            self._export_disabled.set()
            return

        if img is None:
            logger.error(
                "Проба exportImage перед фазой A не прошла (пустой ответ). "
                "exportImage отключён на весь прогон, используется потайловый водопад."
            )
            self._export_disabled.set()
        else:
            logger.info("Проба exportImage перед фазой A прошла успешно.")

    def get_trapezes(self) -> pd.DataFrame:
        """Получение списка трапеций из БД с подтягиванием геометрии из разграфки"""
        t_task = self.config.dbtables.trap
        t_geom = self.config.dbtables.razgr

        query = f"""
            SELECT
                t.name,
                ST_AsGeoJSON(r.geom) AS geojson
            FROM {t_task} t
            JOIN {t_geom} r ON t.name = r.n10000
        """
        return self.db.execute_query(query)

    def calculate_tile_ranges(self, trapeze_geojson: str, zoom: int = 17) -> Tuple[int, int, int, int]:
        """Расчет диапазона тайлов для трапеции"""
        geom = json.loads(trapeze_geojson)
        if geom['type'] == 'Polygon':
            coordinates = geom['coordinates'][0]
        elif geom['type'] == 'MultiPolygon':
            coordinates = geom['coordinates'][0][0]
        else:
            return (0, 0, 0, 0)

        lons, lats = zip(*coordinates)
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)

        min_x, min_y, _, _ = getTileIndex(max_lat, min_lon, zoom)  # Top-Left
        max_x, max_y, _, _ = getTileIndex(min_lat, max_lon, zoom)  # Bottom-Right

        return (min_x, max_x, min_y, max_y)

    # ---------- пути на диске ----------

    def _tile_path(self, trapeze_name: str, z: int, x: int, y: int) -> Path:
        save_dir = self.config.paths.tiles_dir / trapeze_name
        save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir / f"{z}_{x}_{y}.jpg"

    def _tile_exists(self, trapeze_name: str, z: int, x: int, y: int) -> bool:
        path = self.config.paths.tiles_dir / trapeze_name / f"{z}_{x}_{y}.jpg"
        return path.exists() and path.stat().st_size > 0

    def _save_tile(self, img: Image.Image, trapeze_name: str, z: int, x: int, y: int) -> None:
        img.save(self._tile_path(trapeze_name, z, x, y))

    # ---------- общий пул нарезанных тайлов между листами (round3, п.1) ----------
    #
    # Блок 16x16 почти всегда выходит за границы листа (инвариант 5). Без пула
    # соседний лист, чьи тайлы лежат в том же блоке, запрашивает его заново.
    # Пул хранит ВСЕ тайлы блока, прошедшие проверку качества (не только те, что
    # попали в текущий лист) — вне папок листов, поэтому merge_tiles его не видит.
    # Отбракованные по качеству тайлы в пул не кладутся: иначе брак попал бы в
    # соседний лист в обход водопада фазы B.

    def _pool_dir(self) -> Path:
        d = self.config.paths.tiles_dir / "_pool"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _pool_tile_path(self, z: int, x: int, y: int) -> Path:
        return self._pool_dir() / f"{z}_{x}_{y}.jpg"

    def _pool_tile_exists(self, z: int, x: int, y: int) -> bool:
        p = self._pool_tile_path(z, x, y)
        return p.exists() and p.stat().st_size > 0

    # ---------- маркер обработанного блока (round5, п.4) ----------
    #
    # Пропуск блока раньше определялся условием «все 256 тайлов блока уже в
    # пуле» — но тайлы, отбракованные по качеству, в пул не попадают никогда,
    # поэтому блок с хотя бы одним таким тайлом никогда не станет «полным» и
    # перезапрашивался бы при обработке каждого соседнего листа. Маркер —
    # факт обработки, а не подсчёт тайлов.

    def _pool_blocks_dir(self) -> Path:
        d = self._pool_dir() / "_blocks"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _block_marker_path(self, z: int, bcol: int, brow: int) -> Path:
        return self._pool_blocks_dir() / f"{z}_{bcol}_{brow}.done"

    def _block_marker_exists(self, z: int, bcol: int, brow: int) -> bool:
        return self._block_marker_path(z, bcol, brow).exists()

    def _link_from_pool(self, trapeze_name: str, z: int, x: int, y: int) -> bool:
        """Жёсткая ссылка (с фоллбэком на копию) из пула в папку листа.
        True — тайл в итоге есть на диске у листа."""
        if self._tile_exists(trapeze_name, z, x, y):
            return True
        src = self._pool_tile_path(z, x, y)
        if not (src.exists() and src.stat().st_size > 0):
            return False
        dst = self._tile_path(trapeze_name, z, x, y)
        try:
            os.link(src, dst)
        except OSError:
            try:
                shutil.copyfile(src, dst)
            except OSError:
                return False
        return True

    # ---------- Фаза A: блоки geodzz ----------

    def process_block(
        self, bcol: int, brow: int, trapeze_name: str,
        min_x: int, max_x: int, min_y: int, max_y: int, z: int = 17,
    ) -> Dict[str, int]:
        """Один блок фазы A. Возвращает счётчики
        requested/fetched/saved/rejected/from_pool/already_on_disk."""
        stats = {
            "requested": 0, "fetched": 0, "saved": 0, "rejected": 0,
            "from_pool": 0, "already_on_disk": 0,
        }
        if self._stop.is_set() or self._export_disabled.is_set() or self._session_limit_reached():
            return stats

        block_tiles = self.dzz_cfg.block_tiles
        use_pool = self.dzz_cfg.use_pool
        base_x, base_y = bcol * block_tiles, brow * block_tiles
        needed = [
            (x, y)
            for y in range(max(base_y, min_y), min(base_y + block_tiles, max_y + 1))
            for x in range(max(base_x, min_x), min(base_x + block_tiles, max_x + 1))
        ]
        if needed and all(self._tile_exists(trapeze_name, z, x, y) for x, y in needed):
            stats["already_on_disk"] = len(needed)
            return stats  # весь нужный кусок блока уже на диске — не запрашиваем

        if use_pool:
            for x, y in needed:
                if not self._tile_exists(trapeze_name, z, x, y) and self._link_from_pool(trapeze_name, z, x, y):
                    stats["from_pool"] += 1
            still_needed = [(x, y) for x, y in needed if not self._tile_exists(trapeze_name, z, x, y)]
            if not still_needed:
                stats["already_on_disk"] = len(needed) - stats["from_pool"]
                return stats  # весь нужный кусок нашёлся в пуле — сети не касаемся

            if self._block_marker_exists(z, bcol, brow):
                # Блок уже обработан другим листом (маркер round5, п.4) —
                # недостающие тайлы это те, что тогда не прошли проверку
                # качества. Тот же блок при повторном запросе даст тот же
                # результат — сеть не трогаем, добор уйдёт в водопад фазы B.
                return stats

        stats["requested"] = 1
        session = self.get_session()
        try:
            block_img = fetch_block(
                session, self.dzz_cfg.export_base, self.dzz_cfg.referer, bcol, brow, z=z,
                block_tiles=block_tiles, delay_range=self.block_delay,
            )
        except SourceBannedError as exc:
            logger.error(str(exc))
            self._stop.set()
            raise
        except CatalogUnavailableError as exc:
            self._register_export_failure(("block", bcol, brow), str(exc), trapeze_name)
            block_img = None

        if block_img is None:
            logger.debug(f"Блок ({bcol},{brow}) листа {trapeze_name}: не получен, добор потайлово в фазе B")
            return stats
        self._register_export_success()
        stats["fetched"] = 1

        # Нарезаем блок целиком (без обрезки по листу) — пул должен получить все
        # прошедшие проверку тайлы, включая чужие для текущего листа.
        full_min_x, full_max_x = base_x, base_x + block_tiles - 1
        full_min_y, full_max_y = base_y, base_y + block_tiles - 1
        for x, y, tile_img in slice_block(block_img, bcol, brow, block_tiles, full_min_x, full_max_x, full_min_y, full_max_y):
            in_leaf = min_x <= x <= max_x and min_y <= y <= max_y
            ok = passes_quality(tile_img)

            if use_pool and ok and not self._pool_tile_exists(z, x, y):
                tile_img.save(self._pool_tile_path(z, x, y))

            if not in_leaf or self._tile_exists(trapeze_name, z, x, y):
                continue
            if ok:
                if not (use_pool and self._link_from_pool(trapeze_name, z, x, y)):
                    self._save_tile(tile_img, trapeze_name, z, x, y)
                stats["saved"] += 1
            else:
                stats["rejected"] += 1

        # Маркер — только при полном успехе (блок получен, нарезан, все
        # тайлы проверены/сохранены без исключения). Если что-то выше кинуло
        # исключение, до этой строки выполнение не дойдёт — повторный запуск
        # блок дозапросит.
        if use_pool:
            self._block_marker_path(z, bcol, brow).touch()

        self._maybe_rest_after_block()
        return stats

    # ---------- Фаза B: потайловый водопад ----------

    def process_tile(self, x: int, y: int, z: int, trapeze_name: str) -> Optional[str]:
        """Водопад для одного тайла. Возвращает имя источника, откуда сохранён
        тайл, либо None, если тайл не добыт ни с одного."""
        if self._tile_exists(trapeze_name, z, x, y) or self._stop.is_set() or self._session_limit_reached():
            return None

        session = self.get_session()

        dzz_cache = ("dzz-tile", lambda: self._fetch_dzz_tile_cache(session, x, y, z))
        # USE_EXPORT=false или предохранитель, сработавший до конца прогона
        # (round5, п.2), исключают уровень exportImage из водопада целиком
        # (путь отката к прежним трём источникам: dzz-tile -> esri -> google).
        if self.dzz_cfg.use_export and not self._export_disabled.is_set():
            dzz_export = ("dzz-export", lambda: self._fetch_dzz_export_tile(session, x, y, z))
            dzz_sources = [dzz_export, dzz_cache] if self.dzz_cfg.prefer_export else [dzz_cache, dzz_export]
        else:
            dzz_sources = [dzz_cache]

        sources = dzz_sources + [
            ("esri", lambda: self._fetch_generic_tile(session, "esri", x, y, z)),
            ("google", lambda: self._fetch_generic_tile(session, "google", x, y, z)),
        ]

        for name, fetcher in sources:
            try:
                img = fetcher()
            except SourceBannedError as exc:
                logger.error(str(exc))
                self._stop.set()
                raise
            except CatalogUnavailableError as exc:
                self._register_export_failure(("tile", x, y), str(exc), trapeze_name)
                continue

            if name == "dzz-export" and img is not None:
                self._register_export_success()

            if img is None:
                continue
            if passes_quality(img):
                self._save_tile(img, trapeze_name, z, x, y)
                logger.debug(f"Тайл {x},{y} сохранён из {name}")
                return name
            logger.debug(f"Тайл {x},{y}: низкое качество с {name}")

        logger.error(f"Тайл {x},{y} не добыт ни с одного источника")
        return None

    def _fetch_dzz_export_tile(self, session, x: int, y: int, z: int) -> Optional[Image.Image]:
        return fetch_tile_via_export(
            session, self.dzz_cfg.export_base, self.dzz_cfg.referer, x, y, z=z,
            delay_range=self.tile_delay,
        )

    def _fetch_dzz_tile_cache(self, session, x: int, y: int, z: int) -> Optional[Image.Image]:
        url_template = self.tile_services.dzz
        z_val = z - 6
        if '{z-6}' in url_template:
            url = url_template.replace('{z-6}', str(z_val)).format(x=x, y=y)
        else:
            url = url_template.format(x=x, y=y, z=z_val)

        response = request_with_policy(
            session, url, headers={"Referer": self.dzz_cfg.referer},
            timeout=15, delay_range=self.tile_delay, source_name="dzz-tile-cache",
        )
        return self._decode(response, "dzz-tile", x, y)

    def _fetch_generic_tile(self, session, service_name: str, x: int, y: int, z: int) -> Optional[Image.Image]:
        url_template = getattr(self.tile_services, service_name)
        url = url_template.format(x=x, y=y, z=z)
        # Esri и Google — без Referer (см. ТЗ 1.1)
        response = request_with_policy(
            session, url, headers=None,
            timeout=15, delay_range=self.tile_delay, source_name=service_name,
        )
        return self._decode(response, service_name, x, y)

    @staticmethod
    def _decode(response, service_name: str, x: int, y: int) -> Optional[Image.Image]:
        if response is None:
            return None
        content_type = response.headers.get('Content-Type', '').lower()
        if 'image' not in content_type and 'application/octet-stream' not in content_type:
            return None  # прокси/сервер вернул HTML/JSON-ошибку под видом 200
        try:
            return Image.open(BytesIO(response.content)).convert('RGB')
        except Exception:
            logger.debug(f"{service_name}: битая картинка {x},{y}")
            return None

    # ---------- полнота сетки листа (ТЗ 1.5) ----------

    def _check_completeness(self, trapeze_name: str, z: int, min_x: int, max_x: int, min_y: int, max_y: int) -> None:
        missing = [
            [x, y]
            for x in range(min_x, max_x + 1)
            for y in range(min_y, max_y + 1)
            if not self._tile_exists(trapeze_name, z, x, y)
        ]
        # Файл — РЯДОМ с папкой листа, не внутри: merge_tiles глобит все файлы
        # в папке листа для подсчёта сетки (rows_count по уникальным X из имён
        # файлов), и посторонний файл внутри ломает reshape ниже по пайплайну.
        missing_path = self.config.paths.tiles_dir / f"{trapeze_name}_missing.json"
        if missing:
            # tiles_dir мог не создаться на диске вовсе: если проба отключила
            # exportImage до фазы A (round5, п.3), а фаза B не сохранила ни
            # одного тайла листа, ни _tile_path, ни _pool_dir ещё не вызывались.
            missing_path.parent.mkdir(parents=True, exist_ok=True)
            preview = missing[:20]
            logger.warning(
                f"Лист {trapeze_name}: недостаёт {len(missing)} тайлов из "
                f"{(max_x - min_x + 1) * (max_y - min_y + 1)}: {preview}"
                f"{'...' if len(missing) > len(preview) else ''}"
            )
            with open(missing_path, "w") as f:
                json.dump({"z": z, "missing": missing}, f)
        elif missing_path.exists():
            missing_path.unlink()

    # ---------- обработка одного листа ----------

    def _process_trapeze(self, trapeze_name: str, geojson: str, z: int = 17) -> None:
        min_x, max_x, min_y, max_y = self.calculate_tile_ranges(geojson, z)
        tile_total = (max_x - min_x + 1) * (max_y - min_y + 1)
        logger.info(f"Лист {trapeze_name}: {max_x - min_x + 1}x{max_y - min_y + 1} тайлов")

        if self.progress is not None:
            self.progress.start_outer(trapeze_name, total_inner=tile_total)

        block_stats = {
            "requested": 0, "fetched": 0, "saved": 0, "rejected": 0,
            "from_pool": 0, "already_on_disk": 0,
        }
        block_tiles = self.dzz_cfg.block_tiles

        if self.dzz_cfg.use_export and not self._export_disabled.is_set():
            bcol_list = list(range(min_x // block_tiles, max_x // block_tiles + 1))
            brow_list = list(range(min_y // block_tiles, max_y // block_tiles + 1))
            blocks_total = len(bcol_list) * len(brow_list)
            blocks_done = 0
            if self.progress is not None:
                self.progress.set_extra("блоки", f"0/{blocks_total}")

            with ThreadPoolExecutor(max_workers=self.block_workers) as executor:
                futures = [
                    executor.submit(
                        self.process_block, bcol, brow, trapeze_name, min_x, max_x, min_y, max_y, z
                    )
                    for bcol in bcol_list for brow in brow_list
                ]
                for future in futures:
                    try:
                        stats = future.result()
                    except SourceBannedError:
                        continue
                    for k in block_stats:
                        block_stats[k] += stats[k]
                    blocks_done += 1
                    if self.progress is not None:
                        self.progress.set_extra("блоки", f"{blocks_done}/{blocks_total}")
                        self.progress.tick(stats["saved"])
                        self.progress.tick_skipped(stats["from_pool"] + stats["already_on_disk"])

        logger.info(
            f"Лист {trapeze_name}: блоков запрошено {block_stats['requested']}, "
            f"получено {block_stats['fetched']}, тайлов сохранено из блоков "
            f"{block_stats['saved']}, отбраковано по качеству {block_stats['rejected']}, "
            f"взято из пула без сети {block_stats['from_pool']}, "
            f"уже на диске {block_stats['already_on_disk']}"
        )

        if self._stop.is_set():
            return

        missing_before_b = [
            (x, y)
            for x in range(min_x, max_x + 1)
            for y in range(min_y, max_y + 1)
            if not self._tile_exists(trapeze_name, z, x, y)
        ]
        logger.info(f"Лист {trapeze_name}: потайловый добор для {len(missing_before_b)} тайлов")

        source_counts: Dict[str, int] = {}
        failed = 0
        with ThreadPoolExecutor(max_workers=self.tile_workers) as executor:
            futures = [
                executor.submit(self.process_tile, x, y, z, trapeze_name)
                for x, y in missing_before_b
            ]
            for future in futures:
                try:
                    source = future.result()
                except SourceBannedError:
                    continue
                if source is None:
                    failed += 1
                    if self.progress is not None:
                        self.progress.tick_failed(1)
                else:
                    source_counts[source] = source_counts.get(source, 0) + 1
                    if self.progress is not None:
                        self.progress.tick(1)

        logger.info(f"Лист {trapeze_name}: добрано потайлово {source_counts}, не получено {failed}")

        if self.progress is not None:
            self.progress.add_source_counts(source_counts)
            self.progress.finish_outer()

        if self._stop.is_set():
            return

        self._check_completeness(trapeze_name, z, min_x, max_x, min_y, max_y)

    def run(self) -> None:
        """Основной метод выполнения задачи"""
        trapezes_df = self.get_trapezes()
        total = len(trapezes_df)
        logger.info(f"Found {total} trapezes for processing")

        session_deadline = None
        if self.dzz_cfg.session_max_minutes:
            session_deadline = self._session_start + self.dzz_cfg.session_max_minutes * 60
        self.progress = ProgressReporter(
            name="download", total_outer=total, logger=logger,
            outer_name="лист", inner_name="тайлы", rate_unit="тайл",
            session_deadline=session_deadline, session_unit_name="лист",
        )

        if self.dzz_cfg.use_export:
            self._probe_export()

        processed = 0
        current_leaf = None
        for _, row in trapezes_df.iterrows():
            if self._stop.is_set() or self._session_stop.is_set():
                break
            current_leaf = row['name']
            self._process_trapeze(current_leaf, row['geojson'])
            if self._stop.is_set():
                break
            processed += 1
            if self._session_limit_reached():
                remaining = total - processed
                logger.info(
                    f"Лимит сессии ({self.dzz_cfg.session_max_minutes} мин) достигнут "
                    f"после листа {current_leaf}: обработано {processed}/{total}, "
                    f"осталось {remaining}. Прогон завершается штатно, следующий "
                    "запуск продолжит с этого места (резюмируемость)."
                )
                break

        self.progress.finish()

        if self._stop.is_set():
            # Уже скачанное на диске (в т.ч. в _pool) не трогаем — резюмируемость
            # и пул сами доберут остаток при повторном запуске после устранения причины.
            logger.error(
                f"Остановка на листе {current_leaf} ({processed}/{total} листов "
                f"обработано до него) — источник вернул 401/403, см. лог выше"
            )
            raise DownloadBanned(
                f"Источник вернул 401/403 на листе {current_leaf} "
                f"({processed}/{total} листов обработано) — задача остановлена"
            )


def task_download():
    DownloadTilesTask().run()

if __name__ == "__main__":
    task_download()
