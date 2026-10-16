"""Проверки индикаторов боковой панели «Статус системы» (round61, блок B).

Индикаторы GEE и инференса раньше не проверяли работоспособность (GEE — всегда
«✅», инференс — только наличие файла и сборку CUDA-провайдера в onnxruntime).
Здесь они проверяются тем же путём, что и рабочие шаги:

- GEE — `GEEService()` (тот же код инициализации, что в шаге 4) + минимальный
  серверный запрос `ee.Number(1).getInfo()`;
- инференс — `InferenceService()` (те же провайдеры и опции, что в шаге 3;
  сам он падает, если первый активный провайдер не CUDA) — берётся фактический
  провайдер созданной сессии.

Результат кэшируется на 10 минут на процесс (общий для всех сессий Streamlit);
`reset_cache()` сбрасывает кэш (кнопка «Перепроверить»). Сбой самой проверки
не роняет панель: любое исключение превращается в состояние «error»/«unverified».
В текст не попадают содержимое ключа и значения переменных окружения.
"""
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

CACHE_TTL_S = 600
CACHE_TTL_UNVERIFIED_S = 60  # «не проверено» (нет сети) не держим 10 минут
GEE_TIMEOUT_S = 20
INFERENCE_TIMEOUT_S = 30
MAX_MESSAGE_LEN = 200

OK, ERROR, UNVERIFIED = "ok", "error", "unverified"

_SECRET_RX = re.compile(r"-----BEGIN|private_key|BEGIN PRIVATE|input_value", re.I)


@dataclass
class Status:
    state: str          # ok | error | unverified
    text: str           # готовая строка для панели (без markdown-ловушек)
    checked_at: str     # ЧЧ:ММ (Europe/Minsk)
    hint: str = ""


def sanitize(text: str) -> str:
    """Обрезает сообщение до 200 символов; если оно похоже на содержимое ключа —
    заменяет целиком (ключ не должен попасть ни в панель, ни в журнал)."""
    text = " ".join(str(text).split())
    if _SECRET_RX.search(text):
        return "<сообщение скрыто: возможно содержит данные ключа>"
    return text[:MAX_MESSAGE_LEN]


def _now_hm() -> str:
    return datetime.now(ZoneInfo("Europe/Minsk")).strftime("%H:%M")


def _run_with_timeout(fn, timeout_s):
    """fn() в отдельном потоке. Возвращает ('ok', результат) | ('exc', исключение) |
    ('timeout', None). Поток по таймауту не прерывается (daemon), но панель не ждёт."""
    box = {}

    def target():
        try:
            box["v"] = fn()
        except BaseException as e:  # noqa: BLE001 — сбой проверки не должен ронять панель
            box["e"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        return "timeout", None
    if "e" in box:
        return "exc", box["e"]
    return "ok", box.get("v")


def _is_network_error(exc: BaseException) -> bool:
    names = {c.__name__ for c in type(exc).__mro__}
    if names & {"ConnectionError", "Timeout", "TransportError", "TimeoutError",
                "ConnectTimeout", "ReadTimeout", "gaierror"}:
        return True
    msg = str(exc).lower()
    return any(k in msg for k in ("timed out", "name resolution", "connection", "network is unreachable"))


# --- зонды (подменяются в тестах) -------------------------------------------
def _gee_probe():
    from src.services.gee import GEEService  # тот же путь, что и шаг 4
    GEEService()
    import ee
    return ee.Number(1).getInfo()


def _inference_probe():
    """Возвращает фактический первый провайдер созданной сессии."""
    from src.core.config import settings
    path = settings.inference.onnx_model_path
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    from src.services.inference import InferenceService
    svc = InferenceService()
    try:
        return svc.session.get_providers()[0]
    finally:
        del svc  # сессия освобождается сразу


# --- проверки ---------------------------------------------------------------
def check_gee() -> Status:
    at = _now_hm()
    kind, val = _run_with_timeout(_gee_probe, GEE_TIMEOUT_S)
    if kind == "timeout":
        return Status(UNVERIFIED, "⚠️ GEE: не проверено — таймаут/нет сети", at)
    if kind == "exc":
        if _is_network_error(val):
            return Status(UNVERIFIED, "⚠️ GEE: не проверено — таймаут/нет сети", at)
        return Status(ERROR, f"❌ GEE: ошибка — {type(val).__name__}: {sanitize(val)}", at)
    if val != 1:
        return Status(ERROR, f"❌ GEE: ошибка — неожиданный ответ сервера: {sanitize(val)}", at)
    return Status(OK, f"✅ GEE: авторизация подтверждена (проверено {at})", at)


def check_inference() -> Status:
    at = _now_hm()
    kind, val = _run_with_timeout(_inference_probe, INFERENCE_TIMEOUT_S)
    hint = "Пересоздать контейнер etl (см. руководство оператора), затем «Перепроверить»."
    if kind == "timeout":
        return Status(UNVERIFIED, "⚠️ Инференс: не проверено — таймаут создания сессии", at)
    if kind == "exc":
        if isinstance(val, FileNotFoundError):
            return Status(ERROR, "❌ Инференс: модель не найдена", at)
        m = re.search(r"получили \[([^\]]*)\]", str(val))
        if m:
            return Status(ERROR, f"❌ Инференс: CUDA не инициализирована (фактический провайдер: "
                                 f"{m.group(1).replace(chr(39), '')})", at, hint)
        return Status(ERROR, f"❌ Инференс: ошибка — {type(val).__name__}: {sanitize(val)}", at, hint)
    if val != "CUDAExecutionProvider":
        return Status(ERROR, f"❌ Инференс: CUDA не инициализирована (фактический провайдер: {val})", at, hint)
    return Status(OK, f"✅ Инференс: CUDA активна (проверено {at})", at)


# --- кэш --------------------------------------------------------------------
_CHECKS = {"gee": check_gee, "inference": check_inference}
_cache: dict = {}
_lock = threading.Lock()


def get_status(name: str, now=time.monotonic) -> Status:
    with _lock:
        hit = _cache.get(name)
        if hit:
            ttl = CACHE_TTL_UNVERIFIED_S if hit[1].state == UNVERIFIED else CACHE_TTL_S
            if now() - hit[0] < ttl:
                return hit[1]
    try:
        st = _CHECKS[name]()
    except BaseException as e:  # noqa: BLE001
        st = Status(ERROR, f"❌ {name}: сбой проверки — {type(e).__name__}", _now_hm())
    with _lock:
        _cache[name] = (now(), st)
    return st


def reset_cache() -> None:
    with _lock:
        _cache.clear()
