#!/usr/bin/env python3
"""Тесты round66: автоматический пропуск пакета нового расчётного года (deliver.py).

Реальная временная PostgreSQL (initdb/pg_ctl во временном каталоге, свой порт, таблицы
без PostGIS), поэтому проверяется настоящий SQL `_check_year_composition` и
`_swap_staged_tables`. Каждый ключевой сценарий — с КОНТРОЛЕМ на прежнем коде (OLD_REF).

Запуск: python3 REPIKURR/tools/test_year_composition.py   (нужны initdb, pg_ctl, psql)
"""
import glob
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPIKURR = HERE.parent
REPO = REPIKURR.parent
OLD_REF = "ecee1e8"            # коммит до round66

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pg_bin(name):
    for d in sorted(glob.glob("/usr/lib/postgresql/*/bin"), reverse=True):
        if (Path(d) / name).exists():
            return str(Path(d) / name)
    return shutil.which(name)


class TempPg:
    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="pg66_"))
        self.port = free_port()
        subprocess.run([pg_bin("initdb"), "-D", str(self.dir / "d"), "-U", "pikurr", "-A", "trust"],
                       check=True, capture_output=True)
        subprocess.run([pg_bin("pg_ctl"), "-D", str(self.dir / "d"), "-o",
                        f"-p {self.port} -k {self.dir} -c listen_addresses=127.0.0.1", "-l",
                        str(self.dir / "log"), "-w", "start"], check=True, capture_output=True)
        self.sql("CREATE DATABASE pikurr;", db="postgres")

    def sql(self, q, db="pikurr"):
        r = subprocess.run(["psql", "-h", "127.0.0.1", "-p", str(self.port), "-U", "pikurr", "-d", db,
                            "-v", "ON_ERROR_STOP=1", "-tA", "-c", q], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr)
        return r.stdout.strip()

    def stop(self):
        subprocess.run([pg_bin("pg_ctl"), "-D", str(self.dir / "d"), "-m", "immediate", "stop"],
                       capture_output=True)
        shutil.rmtree(self.dir, ignore_errors=True)


def load(name, source, pg):
    os.environ.update({"GEOSERVER_URL": "http://127.0.0.1:1/geoserver", "GEOSERVER_PASSWORD": "x",
                       "GEOSERVER_USER": "u", "FRONTEND_DB_PASSWORD": "x", "FRONTEND_DB_HOST": "127.0.0.1",
                       "FRONTEND_DB_PORT": str(pg.port), "FRONTEND_DB_USER": "pikurr",
                       "FRONTEND_DB_NAME": "pikurr", "GEOSERVER_WORKSPACE": "pikurr"})
    tmp = Path(tempfile.mkdtemp(prefix="t66_"))
    (tmp / "tile_math.py").write_text((HERE / "tile_math.py").read_text())
    f = tmp / f"{name}.py"
    f.write_text(source)
    sys.path.insert(0, str(tmp))
    spec = importlib.util.spec_from_file_location(name, f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def old_source():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{OLD_REF}:REPIKURR/deliver.py"],
                          capture_output=True, text=True, check=True).stdout


def set_live(pg, rows_by_year):
    pg.sql("DROP TABLE IF EXISTS assessment; DROP TABLE IF EXISTS assessment_stage;")
    pg.sql("CREATE TABLE assessment (fid_ext text, year int, valuation int);")
    for y, n in rows_by_year.items():
        pg.sql(f"INSERT INTO assessment SELECT 'f'||g, {y}, 1 FROM generate_series(1,{n}) g;")


def set_stage(pg, rows_by_year):
    pg.sql("CREATE TABLE assessment_stage (fid_ext text, year int);")
    for y, n in rows_by_year.items():
        pg.sql(f"INSERT INTO assessment_stage SELECT 'f'||g, {y} FROM generate_series(1,{n}) g;")


def verdict(mod, live, pkg, **kw):
    """-> ("pass", результат) | ("reject", текст)"""
    set_live(pg, {y: 10 for y in live})
    try:
        return "pass", mod._check_year_composition(sorted(pkg), **kw)
    except mod.YearCompositionGuardError as e:
        return "reject", str(e)


def swap(mod, live_rows, stage_rows, check_years, **kw):
    set_live(pg, live_rows)
    set_stage(pg, stage_rows)
    try:
        mod._swap_staged_tables(["assessment"], check_years=check_years, **kw)
        return "pass", pg.sql("SELECT count(*) FROM assessment")
    except mod.SwapGuardError as e:
        return "reject", str(e)


def main():
    global pg
    pg = TempPg()
    try:
        new = load("deliver_new", (REPIKURR / "deliver.py").read_text(), pg)
        old = load("deliver_old", old_source(), pg)

        cases = [   # (описание, L, P, ожидание, year_change)
            ("L={2025}, P={2025,2026} -> пропуск, appended [2026]", {2025}, {2025, 2026}, "pass", "appended [2026]"),
            ("L={2025,2026}, P={2025,2026,2027} -> пропуск", {2025, 2026}, {2025, 2026, 2027}, "pass", "appended [2027]"),
            ("L={2025}, P={2025,2027} -> пропуск (пропущенный год допустим)", {2025}, {2025, 2027}, "pass", "appended [2027]"),
            ("L={2025}, P={2023,2024,2025} (инцидент 37/38) -> отказ", {2025}, {2023, 2024, 2025}, "reject", None),
            ("L={2025,2026}, P={2026,2027} (пропал 2025) -> отказ", {2025, 2026}, {2026, 2027}, "reject", None),
            ("L={2025,2026}, P={2024,2025,2026} -> отказ", {2025, 2026}, {2024, 2025, 2026}, "reject", None),
            ("L={2025,2027}, P={2025,2026,2027} (год внутри набора) -> отказ", {2025, 2027}, {2025, 2026, 2027}, "reject", None),
            ("P=L -> пропуск, none", {2025, 2026}, {2025, 2026}, "pass", "none"),
            ("P={2025}, L={2025,2026} (сужение) -> отказ", {2025, 2026}, {2025}, "reject", None),
        ]
        for desc, L, P, want, yc in cases:
            got, res = verdict(new, L, P)
            ok = got == want and (yc is None or res["year_change"] == yc)
            check(desc, ok, f"{got}" + (f", year_change={res['year_change']}" if got == "pass" else ""))

        # L пусто (таблица есть, строк нет) и таблицы нет — пропуск, none
        pg.sql("DROP TABLE IF EXISTS assessment; CREATE TABLE assessment (fid_ext text, year int, valuation int);")
        r = new._check_year_composition([2025, 2026])
        check("L пусто (первая доставка) -> пропуск, none", r["year_change"] == "none")
        pg.sql("DROP TABLE assessment;")
        r = new._check_year_composition([2025, 2026])
        check("таблицы assessment нет -> пропуск, none", r["year_change"] == "none")

        # --allow-year-change по-прежнему обходит отказ
        got, res = verdict(new, {2025}, {2023, 2024, 2025}, allow_year_change=True)
        check("--allow-year-change обходит отказ (инцидент 37/38)", got == "pass" and res["year_change"] == "overridden")

        # текст отказа: перечень L и P и нарушенное условие
        got, msg = verdict(new, {2025}, {2023, 2024, 2025})
        check("текст отказа содержит L, P и нарушенное условие",
              "[2023, 2024, 2025]" in msg and "[2025]" in msg and "не позже последнего" in msg, msg[:160])
        got, msg = verdict(new, {2025, 2026}, {2026, 2027})
        check("текст отказа при пропаже года называет пропавший год", "[2025]" in msg and "нет годов" in msg)

        # усадка по годам (реальный SQL swap)
        got, msg = swap(new, {2025: 100, 2026: 100}, {2025: 80, 2026: 100, 2027: 100}, (2025, 2026))
        check("добавлен год, строк 2025 в стадии на 20 % меньше -> отказ по усадке года",
              got == "reject" and "года 2025" in msg, msg[:120])
        got, cnt = swap(new, {2025: 100, 2026: 100}, {2025: 80, 2026: 100, 2027: 100}, (2025, 2026), allow_shrink=True)
        check("то же с --allow-shrink -> пропуск", got == "pass" and cnt == "280", f"строк после: {cnt}")
        got, cnt = swap(new, {2025: 100, 2026: 100}, {2025: 95, 2026: 100, 2027: 100}, (2025, 2026))
        check("усадка 2025 на 5 % (в пределах порога) -> пропуск", got == "pass" and cnt == "295")
        got, cnt = swap(new, {2025: 100}, {2025: 100, 2026: 50}, (2025,))
        check("добавлен год, старый год цел -> пропуск", got == "pass" and cnt == "150")
        got, msg = swap(new, {2025: 100, 2026: 100}, {2026: 100, 2027: 300}, (2025, 2026))
        check("год 2025 исчез из стадии (сумма выросла) -> отказ по усадке года", got == "reject" and "года 2025" in msg)

        # КОНТРОЛИ на прежнем коде
        for desc, L, P, *_ in cases[:3]:
            got, res = verdict(old, L, P)
            check(f"КОНТРОЛЬ (прежний код): {desc.split(' -> ')[0]} -> отказ", got == "reject")
        got, res = verdict(old, {2025}, {2023, 2024, 2025})
        check("КОНТРОЛЬ: прежний код тоже отклоняет инцидент 37/38 (поведение сохранено)", got == "reject")
        set_live(pg, {2025: 100, 2026: 100})
        set_stage(pg, {2025: 80, 2026: 100, 2027: 100})
        try:
            old._swap_staged_tables(["assessment"])
            passed = True
        except Exception:
            passed = False
        check("КОНТРОЛЬ: прежний код потерю 20 % строк года 2025 при росте суммы НЕ замечает", passed)
    finally:
        pg.stop()
    failed = [r for r in results if not r[1]]
    print(f"\nИТОГ: {len(results) - len(failed)}/{len(results)} проверок PASS")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
