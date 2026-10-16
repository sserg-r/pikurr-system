"""Окно снимков Sentinel-2 и правило расчётного года (round62, Р5-б).

Единственное место констант: и окно запроса к GEE (`GEEService.get_scl_series_url`),
и правило смены расчётного года (`src.utils.timeutils.get_target_year`) берут их
отсюда. Окно снимков — {год}-04-15 … {год}-10-15; расчётный год становится
текущим через GRACE дней после конца окна (запас на поступление снимков в GEE),
то есть с 20 октября. Значения окна НЕ менять без решения пользователя — они
определяют, какие снимки попадают в обработку.
"""
import datetime

SEASON_START = (4, 15)          # (месяц, день) начала окна снимков
SEASON_END = (10, 15)           # (месяц, день) конца окна снимков
YEAR_ROLLOVER_GRACE_DAYS = 5    # запас после конца окна, дней


def season_window(year: int) -> tuple[str, str]:
    """Границы окна снимков года строками YYYY-MM-DD (для ee.Filter.date)."""
    return (f"{year}-{SEASON_START[0]:02d}-{SEASON_START[1]:02d}",
            f"{year}-{SEASON_END[0]:02d}-{SEASON_END[1]:02d}")


def rollover_date(year: int) -> datetime.date:
    """Дата, с которой расчётным годом становится `year` (конец окна + запас)."""
    return (datetime.date(year, *SEASON_END)
            + datetime.timedelta(days=YEAR_ROLLOVER_GRACE_DAYS))
