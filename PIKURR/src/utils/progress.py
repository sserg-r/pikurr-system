"""
Индикация прогресса длительных задач без tqdm — вывод в docker compose logs
не TTY, возврат каретки дал бы либо кашу, либо тысячи строк. Строки пишутся
дросселированно по времени. См. prompts/PROMPT_progress_round6.md.
"""
import logging
import threading
import time
from collections import deque
from typing import Deque, Optional, Tuple

from src.core.config import settings

PREFIX = "PROGRESS"


def _format_hms(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


class ProgressReporter:
    """Один экземпляр на задачу. Потокобезопасен — tick()/tick_skipped()
    вызываются из воркеров ThreadPoolExecutor (download.py, фазы A/B).

    outer — крупная единица (лист, год); inner — единица внутри неё (тайл,
    фрагмент). Скорость и ETA считаются по накопленным за весь прогон inner-
    событиям, а не по одному outer, поэтому переживают границы start_outer().
    """

    def __init__(
        self,
        name: str,
        total_outer: int,
        logger: logging.Logger,
        outer_name: str = "лист",
        inner_name: str = "единиц",
        rate_unit: str = "ед",
        session_deadline: Optional[float] = None,
        session_unit_name: Optional[str] = None,
    ):
        self.name = name
        self.total_outer = total_outer
        self.logger = logger
        self.outer_name = outer_name
        self.inner_name = inner_name
        self.rate_unit = rate_unit
        # Момент (time.monotonic()), в который сработает DZZ__SESSION_MAX_MINUTES
        # или аналогичный лимит — только для предупреждения в строке, реального
        # ограничения реализует сама задача.
        self.session_deadline = session_deadline
        self.session_unit_name = session_unit_name or outer_name

        self.enabled = settings.progress.enabled
        self.interval = settings.progress.interval_seconds
        self.rate_window = settings.progress.rate_window_seconds

        self._lock = threading.Lock()
        self._start = time.monotonic()
        self._last_emit = 0.0

        self._outer_index = 0
        self._outer_label = ""
        self._total_inner: Optional[int] = None
        self._extra: dict = {}

        # Счётчики текущего outer (сбрасываются в start_outer) — для отображения.
        self._cur_done = 0
        self._cur_skipped = 0

        # Накопительные счётчики за весь прогон — для ETA и итоговой строки.
        self._global_done = 0
        self._global_skipped = 0
        self._global_failed = 0

        # Скользящее окно скорости: только реально обработанные (tick()),
        # пропущенные с диска не в счёт (иначе после резюмируемости скорость
        # взлетит и ETA обвалится).
        self._events: Deque[Tuple[float, int]] = deque()

        # Учёт простоя (отдых между блоками, round5) для поправки ETA.
        self._idle_seconds = 0.0

        # Для оценки общего объёма inner-единиц по всем outer (см. ETA).
        self._outer_total_inner_sum = 0
        self._outer_total_inner_count = 0

        # По источникам — для итоговой строки download (см. ТЗ п.2).
        self._source_counts: dict = {}

    # ---------- управление ----------

    def start_outer(self, label: str, total_inner: Optional[int] = None) -> None:
        with self._lock:
            self._outer_index += 1
            self._outer_label = label
            self._total_inner = total_inner
            self._cur_done = 0
            self._cur_skipped = 0
            self._extra = {}
            if total_inner is not None:
                self._outer_total_inner_sum += total_inner
                self._outer_total_inner_count += 1

    def set_total_inner(self, total_inner: int) -> None:
        """Заполняет объём текущего outer, когда он известен только после
        начала обработки (например, segmentate.py — число фрагментов
        известно лишь после нарезки холста)."""
        with self._lock:
            if self._total_inner is None:
                self._outer_total_inner_sum += total_inner
                self._outer_total_inner_count += 1
            self._total_inner = total_inner

    def set_extra(self, label: str, text: str) -> None:
        """Дополнительное поле в строке (например, «блоки 6/9» фазы A)."""
        with self._lock:
            self._extra[label] = text

    def add_source_counts(self, counts: dict) -> None:
        """Разбивка по источникам для итоговой строки (download, ТЗ п.2)."""
        with self._lock:
            for k, v in counts.items():
                self._source_counts[k] = self._source_counts.get(k, 0) + v

    def note_idle(self, seconds: float) -> None:
        """Регистрирует время простоя (отдых между блоками, round5, п.5) —
        исключается из расчёта активной скорости, но учитывается в ETA
        через rest_ratio."""
        with self._lock:
            self._idle_seconds += seconds

    def tick(self, n: int = 1) -> None:
        if not self.enabled:
            with self._lock:
                self._cur_done += n
                self._global_done += n
            return
        now = time.monotonic()
        with self._lock:
            self._cur_done += n
            self._global_done += n
            self._events.append((now, n))
            self._prune_events(now)
            self._maybe_emit(now)

    def tick_skipped(self, n: int = 1) -> None:
        with self._lock:
            self._cur_skipped += n
            self._global_skipped += n
            if self.enabled:
                self._maybe_emit(time.monotonic())

    def tick_failed(self, n: int = 1) -> None:
        with self._lock:
            self._global_failed += n

    def finish_outer(self) -> None:
        """Точка расширения — сейчас без обязательных действий, оставлена
        для симметрии интерфейса и возможной будущей пер-outer статистики."""
        return

    def finish(self) -> None:
        """Итоговая строка задачи: обработано/пропущено/не получено, общее
        время, средняя скорость. Печатается всегда при enabled=True, даже
        если ни один tick() не прошёл порог интервала."""
        if not self.enabled:
            return
        elapsed = time.monotonic() - self._start
        with self._lock:
            done = self._global_done
            skipped = self._global_skipped
            failed = self._global_failed
            avg_rate = done / elapsed if elapsed > 0 else 0.0
            parts = [
                f"{PREFIX} {self.name} | завершено",
                f"обработано {done}",
                f"пропущено {skipped}",
                f"не получено {failed}",
                f"время {_format_hms(elapsed)}",
                f"средняя скорость {avg_rate:.2f} {self.rate_unit}/с",
            ]
            if self._source_counts:
                breakdown = ", ".join(f"{k}={v}" for k, v in sorted(self._source_counts.items()))
                parts.append(f"источники: {breakdown}")
        self.logger.info(" | ".join(parts))

    # ---------- внутреннее ----------

    def _prune_events(self, now: float) -> None:
        cutoff = now - self.rate_window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def _current_rate(self, now: float) -> float:
        if not self._events:
            return 0.0
        span = now - self._events[0][0]
        count = sum(n for _, n in self._events)
        if span <= 0:
            return float(count)
        return count / span

    def _maybe_emit(self, now: float) -> None:
        """Вызывается уже под self._lock."""
        if now - self._last_emit < self.interval:
            return
        self._last_emit = now
        self._emit(now)

    def _emit(self, now: float) -> None:
        """Вызывается уже под self._lock."""
        elapsed_total = now - self._start
        active_elapsed = max(elapsed_total - self._idle_seconds, 0.0)
        rate = self._current_rate(now)
        rest_ratio = self._idle_seconds / active_elapsed if active_elapsed > 0 else 0.0

        pct = (self._outer_index / self.total_outer * 100) if self.total_outer else 0.0
        outer_part = f"{self.outer_name} {self._outer_index}/{self.total_outer} ({pct:.1f}%)"
        if self._outer_label:
            outer_part += f" {self._outer_label}"

        segments = [f"{PREFIX} {self.name}", outer_part]

        for label, text in self._extra.items():
            segments.append(f"{label} {text}")

        if self._total_inner is not None:
            inner_part = f"{self.inner_name} {self._cur_done}/{self._total_inner}"
        else:
            inner_part = f"{self.inner_name} {self._cur_done}"
        if self._cur_skipped:
            inner_part += f" (+{self._cur_skipped} с диска)"
        segments.append(inner_part)

        segments.append(f"{rate:.1f} {self.rate_unit}/с")
        segments.append(f"прошло {_format_hms(elapsed_total)}")

        eta_seconds = self._estimate_eta(rate, rest_ratio)
        if eta_seconds is not None:
            segments.append(f"осталось ~{_format_hms(eta_seconds)}")

        warning = self._session_warning(now, eta_seconds)
        if warning:
            segments.append(warning)

        self.logger.info(" | ".join(segments))

    def _estimate_eta(self, rate: float, rest_ratio: float) -> Optional[float]:
        """eta = remaining / rate_active * (1 + rest_ratio) — remaining
        считается по оценке общего объёма inner-единиц всего прогона
        (среднее по уже увиденным outer, помноженное на total_outer), а не
        по одному текущему outer."""
        if rate <= 0 or self._outer_total_inner_count == 0 or not self.total_outer:
            return None
        avg_inner_per_outer = self._outer_total_inner_sum / self._outer_total_inner_count
        estimated_total = avg_inner_per_outer * self.total_outer
        done_overall = self._global_done + self._global_skipped
        remaining = estimated_total - done_overall
        if remaining <= 0:
            return 0.0
        return remaining / rate * (1 + rest_ratio)

    def _session_warning(self, now: float, eta_seconds: Optional[float]) -> Optional[str]:
        if self.session_deadline is None or eta_seconds is None:
            return None
        finish_at = now + eta_seconds
        if finish_at <= self.session_deadline:
            return None
        time_to_deadline = self.session_deadline - now
        if time_to_deadline <= 0 or eta_seconds <= 0:
            outer_left = max(self.total_outer - self._outer_index, 0)
        else:
            outer_remaining = max(self.total_outer - self._outer_index, 0)
            fraction_completable = min(time_to_deadline / eta_seconds, 1.0)
            outer_left = outer_remaining * (1 - fraction_completable)
        return (
            f"ВНИМАНИЕ: лимит сессии сработает раньше конца, "
            f"останется примерно {outer_left:.0f} {self.session_unit_name}(ов)"
        )
