"""
Общая политика обработки HTTP-ответов для источников тайлов.
См. prompts/PROMPT_dzz_export_adapter.md, шаг 1.2.
"""
import logging
import random
import time
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)


class SourceBannedError(Exception):
    """403/401 от источника — сигнал остановить всю задачу немедленно.

    403: ретраи продлевают бан. 401: отвалился гейт доступа целиком (обычно —
    неверный/изменившийся Referer), а не «этого тайла нет» — тихий переход к
    следующему источнику замаскировал бы полную недоступность geodzz."""


def request_with_policy(
    session: requests.Session,
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = 10,
    max_retries: int = 4,
    delay_range: Tuple[float, float] = (0.0, 0.0),
    source_name: str = "",
) -> Optional[requests.Response]:
    """
    HTTP 200 -> Response.
    404/400, исчерпанные ретраи 429/503, повторный сбой прочих 5xx -> None
    (штатный переход к следующему источнику в водопаде).
    403 -> SourceBannedError (вызывающий код обязан остановить задачу).

    Пауза delay_range применяется перед КАЖДЫМ запросом, включая повторные —
    иначе при провале источника несколько попыток подряд уходят без задержки.
    """
    attempt = 0
    retried_other_5xx = False
    while True:
        time.sleep(random.uniform(*delay_range))
        try:
            response = session.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            if retried_other_5xx:
                logger.error(f"{source_name}: сетевая ошибка после повтора: {exc}")
                return None
            retried_other_5xx = True
            logger.warning(f"{source_name}: сетевая ошибка {exc}, одна повторная попытка")
            continue

        code = response.status_code
        if code == 200:
            return response
        if code == 403:
            raise SourceBannedError(
                f"{source_name}: 403 от {url} — остановка задачи (ретраи по 403 продлевают бан)"
            )
        if code == 401:
            referer = (headers or {}).get("Referer")
            raise SourceBannedError(
                f"{source_name}: 401 от {url} — вероятная причина: неверный или "
                f"изменившийся Referer (текущее значение из конфига: {referer!r}); "
                "это отказ гейта доступа целиком, а не отсутствие конкретного тайла"
            )
        if code in (404, 400):
            return None
        if code in (429, 503):
            if attempt >= max_retries:
                logger.warning(
                    f"{source_name}: {code}, исчерпаны {max_retries} попыток — "
                    "переход к следующему источнику"
                )
                return None
            retry_after = response.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else float(2 ** attempt)
            except ValueError:
                wait = float(2 ** attempt)
            wait += random.uniform(0, wait * 0.3)
            logger.warning(
                f"{source_name}: {code}, backoff {wait:.1f}s "
                f"(попытка {attempt + 1}/{max_retries})"
            )
            time.sleep(wait)
            attempt += 1
            continue
        if 500 <= code < 600:
            if retried_other_5xx:
                return None
            retried_other_5xx = True
            time.sleep(1)
            continue
        # прочие коды — тайл/блок недоступен на этом источнике
        return None
