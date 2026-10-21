#!/usr/bin/env python3
"""Тесты round64: сторы растров по годам (deliver.py) и проверка raster_years (healthcheck.py).

Без сети и без GeoServer: фиктивный REST-сервер с состоянием вместо GeoServer,
фиктивный HTTP-сервер витрины вместо прода. Каждый тест с КОНТРОЛЕМ: тот же
сценарий на прежнем коде (OLD_REF) даёт «ok» там, где новый код падает.

Запуск: python3 REPIKURR/tools/test_year_stores.py
"""
import copy
import http.server
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import threading
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPIKURR = HERE.parent
REPO = REPIKURR.parent
OLD_REF = "b93e652"          # коммит до round64 (прежний deliver.py/healthcheck.py)

# ---------------------------------------------------------------- фиктивный GeoServer
TEMPLATE_COVERAGE = {
    "name": "image_assessment", "nativeName": 2025, "title": "image_assessment",
    "description": "Generated from ImageMosaic", "keywords": {"string": [2024, "WCS", "ImageMosaic"]},
    "srs": "EPSG:4326", "projectionPolicy": "REPROJECT_TO_DECLARED", "enabled": True, "advertised": True,
    "parameters": {"entry": [{"string": ["MergeBehavior", "FLAT"]}]},
    "dimensions": {"coverageDimension": {"name": "GRAY_INDEX", "nullValues": {"double": 0}}},
    "metadata": {"entry": [{"@key": "dirName", "$": "image_assessment_2024"}]},
    "store": {"name": "pikurr:image_assessment"},
}
TEMPLATE_LAYER = {"name": "image_assessment", "type": "RASTER", "queryable": False,
                  "defaultStyle": {"name": "pikurr:raster_vegetation", "workspace": "pikurr"}}


DBF_ONE_RECORD = struct.pack("<4sI", b"\x03\x00\x00\x00", 1) + b"\x00" * 24   # заголовок dBASE: 1 запись


class FakeGeoServer:
    def __init__(self):
        self.stores = {"image_assessment": {"name": "image_assessment", "type": "ImageMosaic",
                                            "url": "file:///mnt/data/geodata/2025/"}}
        self.coverages = {"image_assessment": copy.deepcopy(TEMPLATE_COVERAGE)}
        self.layers = {"image_assessment": copy.deepcopy(TEMPLATE_LAYER)}
        self.fail = {}          # "create_store" | "create_coverage" | "put_store" -> код ответа
        self.log = []           # (method, path)
        self.geodata = None     # каталог geodata теста: harvest пересоздаёт в нём индекс
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def _send(self, code, body=None):
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self):
                n = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(n) if n else b""
                try:
                    return json.loads(raw) if raw else None
                except ValueError:
                    return raw.decode()

            def do_GET(self):
                p = self.path.split("?")[0]
                fake.log.append(("GET", p))
                m = re.fullmatch(r"/geoserver/rest/workspaces/pikurr/coveragestores/([^/]+)\.json", p)
                if m:
                    s = fake.stores.get(m.group(1))
                    return self._send(200, {"coverageStore": s}) if s else self._send(404)
                m = re.fullmatch(r"/geoserver/rest/workspaces/pikurr/coveragestores/([^/]+)/coverages/([^/]+)\.json", p)
                if m:
                    c = fake.coverages.get(m.group(2))
                    return self._send(200, {"coverage": c}) if c and m.group(1) in fake.stores else self._send(404)
                m = re.fullmatch(r"/geoserver/rest/layers/pikurr:([^/]+)\.json", p)
                if m:
                    l = fake.layers.get(m.group(1))
                    return self._send(200, {"layer": l}) if l else self._send(404)
                self._send(404)

            def do_POST(self):
                p = self.path.split("?")[0]
                body = self._body()
                fake.log.append(("POST", p, body))
                if p == "/geoserver/rest/workspaces/pikurr/coveragestores":
                    if "create_store" in fake.fail:
                        return self._send(fake.fail["create_store"], {"err": "boom"})
                    s = body["coverageStore"]
                    fake.stores[s["name"]] = s
                    return self._send(201)
                m = re.fullmatch(r"/geoserver/rest/workspaces/pikurr/coveragestores/([^/]+)/coverages", p)
                if m:
                    if "create_coverage" in fake.fail:
                        return self._send(fake.fail["create_coverage"], {"err": "boom"})
                    c = body["coverage"]
                    fake.coverages[c["name"]] = c
                    fake.layers[c["name"]] = {"name": c["name"], "defaultStyle": {"name": "raster"}}
                    return self._send(201)
                if p.endswith("/external.imagemosaic") and fake.geodata is not None:
                    ym = re.search(r"/geodata/(\d+)/", body if isinstance(body, str) else "")
                    if ym:   # harvest строит индекс мозаики заново
                        y = ym.group(1)
                        for ext in ("properties", "shp", "shx", "dbf"):
                            (fake.geodata / y / f"{y}.{ext}").write_bytes(b"")
                        (fake.geodata / y / f"{y}.dbf").write_bytes(DBF_ONE_RECORD)
                if p.endswith("/reset") or p.endswith("/external.imagemosaic"):
                    return self._send(202 if p.endswith("imagemosaic") else 200)
                if p == "/geoserver/rest/reload":
                    return self._send(200)
                self._send(404)

            def do_PUT(self):
                p = self.path.split("?")[0]
                body = self._body()
                fake.log.append(("PUT", p, body))
                m = re.fullmatch(r"/geoserver/rest/workspaces/pikurr/coveragestores/([^/]+)\.json", p)
                if m:
                    if "put_store" in fake.fail:
                        return self._send(fake.fail["put_store"])
                    if m.group(1) not in fake.stores:
                        return self._send(404)
                    fake.stores[m.group(1)].update(body["coverageStore"])
                    return self._send(200)
                m = re.fullmatch(r"/geoserver/rest/workspaces/pikurr/coveragestores/([^/]+)/coverages/([^/]+)\.json", p)
                if m:
                    return self._send(200) if m.group(2) in fake.coverages else self._send(404)
                m = re.fullmatch(r"/geoserver/rest/layers/pikurr:([^/]+)\.json", p)
                if m and m.group(1) in fake.layers:
                    fake.layers[m.group(1)].update(body["layer"])
                    return self._send(200)
                self._send(404)

            def log_message(self, *a):
                pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/geoserver"


# ---------------------------------------------------------------- загрузка модулей
def load_module(name: str, source: str, geoserver_url: str):
    os.environ.update({
        "GEOSERVER_URL": geoserver_url, "GEOSERVER_PASSWORD": "x", "GEOSERVER_USER": "u",
        "FRONTEND_DB_PASSWORD": "x", "GEOSERVER_WORKSPACE": "pikurr",
    })
    tmp = Path(tempfile.mkdtemp(prefix="t64_"))
    # tile_math импортируется deliver.py из соседнего каталога
    (tmp / "tile_math.py").write_text((HERE / "tile_math.py").read_text())
    f = tmp / f"{name}.py"
    f.write_text(source)
    sys.path.insert(0, str(tmp))
    spec = importlib.util.spec_from_file_location(name, f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.__dict__["_tmpdir"] = tmp
    return mod


def old_source(fname: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), "show", f"{OLD_REF}:REPIKURR/{fname}"],
                          capture_output=True, text=True, check=True).stdout


def prepare_geodata(mod, years, gs=None):
    """Каталоги лет с TIF и индексом мозаики (как после copy_rasters + прежних доставок)."""
    root = Path(tempfile.mkdtemp(prefix="geodata_"))
    for y in years:
        d = root / str(y)
        d.mkdir()
        (d / "a.tif").write_bytes(b"x")
        for ext in ("properties", "shp", "shx", "dbf"):
            (d / f"{y}.{ext}").write_bytes(b"")
        (d / f"{y}.dbf").write_bytes(DBF_ONE_RECORD)
    mod.GEODATA_DIR = root
    if gs is not None:
        gs.geodata = root
    return root


# ---------------------------------------------------------------- проверки
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def test_deliver():
    new_src = (REPIKURR / "deliver.py").read_text()

    # 1. Стора прошлого года нет → создаётся, параметры — с образца
    gs = FakeGeoServer()
    d = load_module("deliver_new", new_src, gs.url)
    prepare_geodata(d, [2025, 2026], gs)
    made = d.ensure_year_stores({2025: 1, 2026: 1})
    cov = gs.coverages.get("image_assessment_2025", {})
    st = gs.stores.get("image_assessment_2025", {})
    check("deliver: нет стора -> создан стор+покрытие+слой", made == ["image_assessment_2025"]
          and st.get("url") == "file:///mnt/data/geodata/2025/" and st.get("type") == "ImageMosaic", f"made={made}")
    check("deliver: параметры покрытия скопированы с образца",
          cov.get("projectionPolicy") == "REPROJECT_TO_DECLARED"
          and cov.get("dimensions", {}).get("coverageDimension", {}).get("nullValues") == {"double": 0}
          and cov.get("parameters") == TEMPLATE_COVERAGE["parameters"]
          and cov.get("nativeCoverageName") == "2025" and cov.get("name") == "image_assessment_2025",
          f"keys={sorted(cov)}")
    check("deliver: dirName в metadata = имя нового стора",
          cov["metadata"]["entry"][0]["$"] == "image_assessment_2025")
    check("deliver: стиль слоя скопирован с образца (не 'raster')",
          gs.layers["image_assessment_2025"]["defaultStyle"]["name"] == "pikurr:raster_vegetation"
          and gs.layers["image_assessment_2025"].get("queryable") is False)

    # 2. Стор уже есть → ничего не создаётся (идемпотентность)
    n_post = sum(1 for e in gs.log if e[0] == "POST")
    again = d.ensure_year_stores({2025: 1, 2026: 1})
    check("deliver: стор есть -> повторно не создаётся", again == [] and sum(1 for e in gs.log if e[0] == "POST") == n_post)

    # 3. Один год в пакете → прошлых сторов нет, ничего не делается
    gs1 = FakeGeoServer()
    d1 = load_module("deliver_new1", new_src, gs1.url)
    check("deliver: пакет одного года -> сторы не создаются", d1.ensure_year_stores({2025: 1}) == [] and
          not [e for e in gs1.log if e[0] == "POST"])

    # 4. Ответ 500 при создании стора -> исключение
    for fail_key in ("create_store", "create_coverage"):
        gs2 = FakeGeoServer()
        gs2.fail[fail_key] = 500
        d2 = load_module("deliver_new2", new_src, gs2.url)
        prepare_geodata(d2, [2025, 2026], gs2)
        try:
            d2.ensure_year_stores({2025: 1, 2026: 1})
            raised = None
        except d2.GeoServerStoreError as e:
            raised = e
        check(f"deliver: 500 при {fail_key} -> GeoServerStoreError", raised is not None, str(raised)[:90])

    # 5. Полная доставка растров (reload_geoserver): 500 при создании -> падает; КОНТРОЛЬ на прежнем коде -> ok
    gs3 = FakeGeoServer()
    gs3.fail["create_store"] = 500
    d3 = load_module("deliver_new3", new_src, gs3.url)
    prepare_geodata(d3, [2025, 2026], gs3)
    try:
        d3.reload_geoserver({2025: 1, 2026: 1})
        new_raised = False
    except d3.GeoServerStoreError:
        new_raised = True
    check("deliver: reload_geoserver при 500 создания стора -> доставка падает", new_raised)

    gs4 = FakeGeoServer()
    gs4.fail["create_store"] = 500
    d4 = load_module("deliver_old", old_source("deliver.py"), gs4.url)
    prepare_geodata(d4, [2025, 2026], gs4)
    try:
        d4.reload_geoserver({2025: 1, 2026: 1})
        old_ok = True
    except Exception as e:  # noqa: BLE001
        old_ok = False
        print("   (контроль) прежний код упал:", repr(e)[:80])
    check("КОНТРОЛЬ: прежний код при том же сценарии проходит 'ok' (404 на PUT — только warning)", old_ok)

    # 6. Не 2xx на PUT стора существующего года -> исключение; прежний код — warning
    gs5 = FakeGeoServer()
    gs5.fail["put_store"] = 500
    d5 = load_module("deliver_new5", new_src, gs5.url)
    prepare_geodata(d5, [2026], gs5)
    try:
        d5.reload_geoserver({2026: 1})
        r5 = False
    except d5.GeoServerStoreError:
        r5 = True
    check("deliver: 500 на PUT стора -> исключение", r5)
    gs6 = FakeGeoServer()
    gs6.fail["put_store"] = 500
    d6 = load_module("deliver_old6", old_source("deliver.py"), gs6.url)
    prepare_geodata(d6, [2026], gs6)
    try:
        d6.reload_geoserver({2026: 1})
        r6 = True
    except Exception:  # noqa: BLE001
        r6 = False
    check("КОНТРОЛЬ: прежний код при 500 на PUT стора проходит", r6)

    # 7. Нормальная доставка двух лет: оба стора обновлены, ошибок нет
    gs7 = FakeGeoServer()
    d7 = load_module("deliver_new7", new_src, gs7.url)
    prepare_geodata(d7, [2025, 2026], gs7)
    try:
        d7.reload_geoserver({2025: 1, 2026: 1})
        ok7 = True
    except Exception as e:  # noqa: BLE001
        ok7 = False
        print("   ", repr(e)[:150])
    check("deliver: нормальная доставка двух лет проходит; image_assessment -> geodata/2026",
          ok7 and gs7.stores["image_assessment"]["url"] == "file:///mnt/data/geodata/2026/"
          and gs7.stores["image_assessment_2025"]["url"] == "file:///mnt/data/geodata/2025/")


# ---------------------------------------------------------------- healthcheck
def png(width=64, height=64, seed=7):
    raw = b"".join(b"\x00" + bytes(((x * 7 + y * 13 + seed) % 251) for x in range(width * 4)) for y in range(height))
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class FakeSite:
    def __init__(self, years, broken_layers=(), exception_layers=()):
        site = self
        self.years, self.broken, self.exc = years, set(broken_layers), set(exception_layers)

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/static/year_district.json"):
                    if site.years is None:
                        self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
                    body = json.dumps({"years": site.years, "districtsByYear": {str(y): ["2208"] for y in site.years}}).encode()
                    ctype = "application/json"
                elif "/wms" in self.path and "GetMap" in self.path:
                    layer = re.search(r"layers=pikurr:([\w_]+)", self.path).group(1)
                    if layer in site.exc:        # HTTP 200 + ServiceExceptionReport — классика round24
                        body, ctype = b"<ServiceExceptionReport>Could not find layer</ServiceExceptionReport>", "text/xml"
                    elif layer in site.broken:   # однотонный крошечный PNG
                        body, ctype = png(2, 2), "image/png"
                    else:
                        body, ctype = png(), "image/png"
                else:
                    self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"


def run_raster_years(mod, site):
    checks = []
    static = mod.check_year_district(site.url, checks)
    mod.check_raster_years(site.url, static, checks)
    return [c for c in checks if c["check"] == "raster_years"][0]


def test_healthcheck():
    os.environ["TILES_WITH_DATA_PATH"] = str(REPO / "docs" / "round32_assets" / "tiles_with_data.json")
    src = (REPIKURR / "healthcheck.py").read_text()
    hc = load_module("healthcheck_new", src, "http://127.0.0.1:1/geoserver")

    c = run_raster_years(hc, FakeSite([2025, 2026]))
    check("healthcheck: два года, оба слоя отдают PNG -> PASS", c["ok"] and "2025 (image_assessment_2025)" in c["detail"]
          and "2026 (image_assessment)" in c["detail"], c["detail"][:120])

    c = run_raster_years(hc, FakeSite([2025]))
    check("healthcheck: один год 2025 (как на проде сейчас) -> PASS, слой image_assessment",
          c["ok"] and "2025 (image_assessment)" in c["detail"], c["detail"][:100])

    c = run_raster_years(hc, FakeSite([2025, 2026], exception_layers={"image_assessment_2025"}))
    check("healthcheck: ServiceExceptionReport с кодом 200 для 2025 -> FAIL",
          not c["ok"] and "ServiceExceptionReport" in c["detail"], c["detail"][:140])

    c = run_raster_years(hc, FakeSite([2025, 2026], broken_layers={"image_assessment"}))
    check("healthcheck: пустой PNG для текущего года -> FAIL", not c["ok"], c["detail"][:140])

    c = run_raster_years(hc, FakeSite(None))
    check("healthcheck: year_district.json недоступен -> FAIL (года неизвестны)", not c["ok"], c["detail"][:100])

    # контроль: прежний healthcheck.py проверки raster_years не имеет — сломанный стор 2025 не заметит
    old = load_module("healthcheck_old", old_source("healthcheck.py"), "http://127.0.0.1:1/geoserver")
    check("КОНТРОЛЬ: в прежнем healthcheck.py нет check_raster_years (отсутствие стора 2025 не видно)",
          not hasattr(old, "check_raster_years"))


if __name__ == "__main__":
    test_deliver()
    test_healthcheck()
    failed = [r for r in results if not r[1]]
    print(f"\nИТОГ: {len(results) - len(failed)}/{len(results)} проверок PASS")
    sys.exit(1 if failed else 0)
