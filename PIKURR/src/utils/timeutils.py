import datetime


def get_target_year() -> int:
    """Текущий расчётный год: если месяц < 11, берём прошлый год."""
    now = datetime.datetime.now()
    return now.year if now.month >= 11 else now.year - 1


def get_target_years(count: int = 3) -> range:
    """Диапазон расчётных лет: последние count лет включая текущий."""
    cur = get_target_year()
    return range(cur - count + 1, cur + 1)
