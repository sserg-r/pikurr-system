"""Тест расчётного года (round62, блок B). Без сети и БД, дата подменяется.
`python3 scripts/test_target_year.py [корень_PIKURR]` — второй аргумент нужен для контроля на исходном коде
(например, распакованный `git archive <старый коммит> PIKURR`).

Год проверяется через методы задач (usability, classify, save_db, export, package), а не через timeutils напрямую;
недостающие тяжёлые библиотеки подменяются заглушками (вычисляется только год)."""
import datetime as _dt
import importlib
import os
import sys
import types
from unittest import mock

ROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ns = types.SimpleNamespace
cfg = types.ModuleType("src.core.config")
cfg.settings = mock.MagicMock()
sys.modules["src.core.config"] = cfg
for name in ["geopandas", "cv2", "pyproj", "yaml"]:
    try:
        importlib.import_module(name)
    except Exception:
        sys.modules[name] = mock.MagicMock()
for dotted in ["src.services.gee", "src.services.inference", "src.services.db", "src.utils.progress"]:
    try:
        importlib.import_module(dotted)
    except Exception:
        sys.modules[dotted] = mock.MagicMock()

from src.tasks.usability import UsabilityTask      # noqa: E402
from src.tasks.classify import ClassificationTask  # noqa: E402
from src.tasks.save_db import SaveStatsTask        # noqa: E402
from src.tasks.export import ExportTask            # noqa: E402
from src.tasks.package import PackageTask          # noqa: E402
import src.utils.timeutils as tu                   # noqa: E402
import src.tasks.package as pk                     # noqa: E402


def frozen(y, m, d):
    class FD(_dt.date):
        @classmethod
        def today(cls): return cls(y, m, d)
    class FDT(_dt.datetime):
        @classmethod
        def now(cls, tz=None): return cls(y, m, d, 12, 0, 0)
    return types.SimpleNamespace(date=FD, datetime=FDT, timedelta=_dt.timedelta)


def years_by_task(y, m, d):
    fake = frozen(y, m, d)
    with mock.patch.object(tu, "datetime", fake), mock.patch.object(pk, "datetime", fake):
        return {
            "usability": UsabilityTask.get_target_years(None)[-1],
            "classify": ClassificationTask.get_target_years(None)[-1],
            "save_db": SaveStatsTask.get_target_year(None),
            "export": ExportTask.get_target_year(None),
            "package": PackageTask.get_target_year(None),
        }, list(UsabilityTask.get_target_years(None)) if False else None


CASES = [((2026, 10, 19), 2025), ((2026, 10, 20), 2026), ((2027, 1, 1), 2026), ((2027, 10, 20), 2027)]
fails = 0
for (y, m, d), want in CASES:
    got, _ = years_by_task(y, m, d)
    ok = set(got.values()) == {want}
    fails += (not ok)
    print(("PASS" if ok else "FAIL"), f"{d:02d}.{m:02d}.{y} → ожидается {want}; задачи: {got}")

fake = frozen(2026, 10, 20)
with mock.patch.object(tu, "datetime", fake):
    rng = list(tu.get_target_years(3))
ok = rng == [2024, 2025, 2026]; fails += (not ok)
print(("PASS" if ok else "FAIL"), "get_target_years(3) на 20.10.2026 =", rng)

# единственный источник: в package.py нет собственного вычисления года от даты
src = open(os.path.join(ROOT, "src/tasks/package.py"), encoding="utf-8").read()
own = [l.strip() for l in src.splitlines() if "now.month" in l or ".month <" in l]
ok = not own; fails += (not ok)
print(("PASS" if ok else "FAIL"), "package.py: собственное правило года отсутствует", own if own else "")
sys.exit(1 if fails else 0)
