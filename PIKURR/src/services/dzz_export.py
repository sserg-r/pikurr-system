"""
Блочная загрузка geodzz.by через exportImage (ArcGIS ImageServer 10.2.2).
См. prompts/PROMPT_dzz_export_adapter.md.
"""
import json
import logging
from io import BytesIO
from typing import Iterator, Optional, Tuple

from PIL import Image

from ..utils.http_retry import request_with_policy

logger = logging.getLogger(__name__)


class CatalogUnavailableError(RuntimeError):
    """exportImage вернул ошибку каталога mosaic dataset (FDO error, Failed to
    execute query, Unable to complete operation) — недоступен сам каталог, а
    не только путь рендеринга (подтверждено query?returnCountOnly=true, тоже
    падает тем же кодом). См. инцидент 10.09.2026,
    docs/incident-2026-09-10-exportimage-fdo.md, и round5, п.2-3.

    В отличие от обычного RuntimeError (тайл забракован/не декодировался),
    это исключение НЕ гасится внутри fetch_block/fetch_tile_via_export —
    вызывающий код (download.py) должен его увидеть, чтобы считать отказы
    предохранителя."""


# Маркеры ответа каталога mosaic dataset, а не точечного отсутствия тайла.
# Пустой/бракованный тайл (например, "size больше maxImageWidth") в этот
# список не входит — такие ошибки предохранитель считать не должен.
_CATALOG_ERROR_MARKERS = (
    "FDO error",
    "Failed to execute query",
    "Unable to complete operation",
)

ORIGIN = 20037508.342787
RES17 = 1.1943285668550503   # level 11 сервиса == стандартный z17
TILE_SPAN = 256 * RES17       # 305.7481131149 м

# Referer читается из конфига (DZZ__REFERER), не хардкодится здесь: сервер его
# проверяет, значение — внешняя зависимость, может измениться без предупреждения.
# Подтверждено запросами (2026-09-09): без Referer geodzz отдаёт 401/403/520 с
# текущего диапазона IP. Referer вида "https://www.geodzz.by/" (голый origin, как
# в тексте первого ТЗ) при проверке НЕ сработал (401). Рабочее значение по
# умолчанию в .env_example — "https://www.geodzz.by/izuchdzz/".


def _tile_bbox(x: int, y: int) -> Tuple[float, float, float, float]:
    xmin = -ORIGIN + x * TILE_SPAN
    xmax = xmin + TILE_SPAN
    ymax = ORIGIN - y * TILE_SPAN
    ymin = ymax - TILE_SPAN
    return xmin, ymin, xmax, ymax


def _block_bbox(bcol: int, brow: int, block_tiles: int) -> Tuple[float, float, float, float]:
    span = block_tiles * TILE_SPAN
    xmin = -ORIGIN + bcol * span
    xmax = xmin + span
    ymax = ORIGIN - brow * span
    ymin = ymax - span
    return xmin, ymin, xmax, ymax


def _export_params(bbox: Tuple[float, float, float, float], size_px: int) -> dict:
    xmin, ymin, xmax, ymax = bbox
    return {
        "bbox": f"{xmin},{ymin},{xmax},{ymax}",
        "bboxSR": 3857,
        "imageSR": 3857,
        "size": f"{size_px},{size_px}",
        "format": "jpg",
        "compressionQuality": 75,
        "interpolation": "RSP_BilinearInterpolation",
        "f": "image",
    }


def _parse_image_response(response, context: str) -> Image.Image:
    """
    Content-Type заголовку доверять нельзя: при ошибке параметров (например,
    size больше maxImageWidth) сервер отвечает HTTP 200 с
    Content-Type: image/jpeg, но тело — JSON {"error": {...}}. Поэтому тело
    сначала пробуем декодировать как изображение и только при неудаче
    разбираем как JSON, чтобы дать содержательное сообщение об ошибке.
    """
    try:
        img = Image.open(BytesIO(response.content))
        img.load()
        return img.convert("RGB")
    except Exception as exc:
        try:
            payload = json.loads(response.content)
            message = payload.get("error", payload)
        except (json.JSONDecodeError, ValueError):
            message = response.content[:300]
        text = str(message)
        if any(marker in text for marker in _CATALOG_ERROR_MARKERS):
            raise CatalogUnavailableError(
                f"exportImage ({context}) — каталог мозаики недоступен: {message}"
            ) from exc
        raise RuntimeError(f"exportImage ({context}) вернул не-изображение: {message}") from exc


def fetch_block(
    session,
    export_base: str,
    referer: str,
    bcol: int,
    brow: int,
    z: int = 17,
    block_tiles: int = 16,
    timeout: float = 120,
    delay_range: Tuple[float, float] = (0.0, 0.0),
    max_retries: int = 4,
) -> Optional[Image.Image]:
    """
    Один блок block_tiles*256 x block_tiles*256 px одним запросом exportImage.
    None — блок недоступен (после ретраев/некритичной ошибки); лист целиком
    уходит в потайловый добор для этого блока.
    """
    bbox = _block_bbox(bcol, brow, block_tiles)
    size_px = block_tiles * 256
    response = request_with_policy(
        session,
        f"{export_base}/exportImage",
        params=_export_params(bbox, size_px),
        headers={"Referer": referer},
        timeout=timeout,
        max_retries=max_retries,
        delay_range=delay_range,
        source_name=f"dzz-block({bcol},{brow})",
    )
    if response is None:
        return None
    try:
        return _parse_image_response(response, f"block {bcol},{brow}")
    except CatalogUnavailableError:
        raise
    except RuntimeError as exc:
        logger.warning(str(exc))
        return None


def fetch_tile_via_export(
    session,
    export_base: str,
    referer: str,
    x: int,
    y: int,
    z: int = 17,
    timeout: float = 15,
    delay_range: Tuple[float, float] = (0.0, 0.0),
    max_retries: int = 4,
) -> Optional[Image.Image]:
    """exportImage на bbox одного тайла (size=256,256) — ветка 1 водопада фазы B."""
    bbox = _tile_bbox(x, y)
    response = request_with_policy(
        session,
        f"{export_base}/exportImage",
        params=_export_params(bbox, 256),
        headers={"Referer": referer},
        timeout=timeout,
        max_retries=max_retries,
        delay_range=delay_range,
        source_name=f"dzz-export-tile({x},{y})",
    )
    if response is None:
        return None
    try:
        return _parse_image_response(response, f"tile {x},{y}")
    except CatalogUnavailableError:
        raise
    except RuntimeError as exc:
        logger.warning(str(exc))
        return None


def slice_block(
    block_img: Image.Image,
    bcol: int,
    brow: int,
    block_tiles: int,
    min_x: int,
    max_x: int,
    min_y: int,
    max_y: int,
) -> Iterator[Tuple[int, int, Image.Image]]:
    """
    Нарезает блок на тайлы 256x256; отдаёт только те, что попадают в диапазон
    листа [min_x..max_x] x [min_y..max_y] (инвариант 5 из ТЗ — блок 16x16
    тайлов почти всегда выходит за границы листа).
    """
    base_x = bcol * block_tiles
    base_y = brow * block_tiles
    for iy in range(block_tiles):
        y = base_y + iy
        if y < min_y or y > max_y:
            continue
        for ix in range(block_tiles):
            x = base_x + ix
            if x < min_x or x > max_x:
                continue
            box = (ix * 256, iy * 256, (ix + 1) * 256, (iy + 1) * 256)
            yield x, y, block_img.crop(box)
