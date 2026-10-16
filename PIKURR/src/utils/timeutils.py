import datetime

from src.core.season import rollover_date


def _today() -> datetime.date:
    return datetime.date.today()


def get_target_year() -> int:
    """Расчётный год — единственный источник во всём ETL (round62, Р5-б).

    Текущий год, если дата не раньше конца окна снимков Sentinel-2 плюс запас
    (по умолчанию 20 октября, см. `src.core.season`), иначе прошлый.
    """
    today = _today()
    return today.year if today >= rollover_date(today.year) else today.year - 1


def describe_target_year() -> str:
    """Текст для панели: расчётный год, правило и источник."""
    today = _today()
    year = get_target_year()
    r = rollover_date(today.year)
    return (f"Расчётный год: {year} — по правилу: с {r.day} {_MONTHS[r.month]} — текущий год, "
            f"раньше — прошлый (конец окна снимков + запас)")


_MONTHS = {1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня", 7: "июля",
           8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"}


def get_target_years(count: int = 3) -> range:
    """Диапазон расчётных лет: последние count лет включая текущий."""
    cur = get_target_year()
    return range(cur - count + 1, cur + 1)
