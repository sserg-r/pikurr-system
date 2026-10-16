#!/usr/bin/env python3
"""Тест подавления дребезга и уведомлений external_healthcheck.sh (round61, блок D).
Локально, без сети: фиктивный HTTP-сервер вместо api.telegram.org записывает
запросы; healthcheck.py подменён заглушкой (HEALTHCHECK_PY) с исходом из файла.
Журнал и состояние — во временном каталоге. Запуск: python3 test_alerts.py"""
import http.server, json, os, subprocess, sys, tempfile, threading, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.environ.get("SCRIPT") or os.path.join(os.path.dirname(HERE), "external_healthcheck.sh")
reqs, mode = [], {"status": 200}

class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        reqs.append((self.path, urllib.parse.parse_qs(self.rfile.read(n).decode())))
        self.send_response(mode["status"]); self.end_headers(); self.wfile.write(b'{"ok":true}')
    def log_message(self, *a): pass

srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
tmp = tempfile.mkdtemp()
stub = os.path.join(tmp, "stub_hc.py")
open(stub, "w").write('''import json, os, sys
ok = open(os.environ["STUB_FILE"]).read().strip() == "ok"
print(json.dumps({"ok": ok, "checks": [{"check": "wms_getmap", "ok": ok, "detail": ""}, {"check": "main_page", "ok": True, "detail": ""}]}))
sys.exit(0 if ok else 1)
''')

def run(outcome, token="TESTTOKEN", extra=None, tag="t"):
    d = os.path.join(tmp, tag); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "outcome"), "w").write(outcome)
    env = dict(os.environ, STUB_FILE=os.path.join(d, "outcome"), HEALTHCHECK_PY=stub, LOG=os.path.join(d, "log"),
               TELEGRAM_API_URL=f"http://127.0.0.1:{srv.server_port}", BASE_URL="http://example.invalid", **(extra or {}))
    env.pop("TELEGRAM__TOKEN", None); env.pop("TELEGRAM__CHAT_ID", None)
    if token: env["TELEGRAM__TOKEN"] = token; env["TELEGRAM__CHAT_ID"] = "42"
    # время «прошло»: сдвигаем first_red назад, чтобы «простой» был ненулевым
    return subprocess.run(["bash", SCRIPT], env=env, capture_output=True, text=True).returncode

def shift_first_red(tag, minutes):
    p = os.path.join(tmp, tag, "log.state"); L = open(p).read().splitlines()
    L = [f"first_red={int(l.split('=')[1]) - minutes*60}" if l.startswith("first_red=") else l for l in L]
    open(p, "w").write("\n".join(L) + "\n")

fails = 0
def expect(name, got, want):
    global fails
    ok = got == want; fails += (not ok)
    print(("PASS" if ok else "FAIL"), name, f"(запросов {got}, ожидалось {want})")

def n(): return len(reqs)

# Сценарий 1: RED×4 → GREEN → GREEN
rcs = []
for i in (1, 2): rcs.append(run("red", tag="s1"))
expect("2 RED — запросов 0", n(), 0)
rcs.append(run("red", tag="s1")); expect("3-й RED — ровно 1 запрос", n(), 1)
down = reqs[0][1]["text"][0]
print("   текст:", down)
assert "Витрина недоступна" in down and "wms_getmap" in down
rcs.append(run("red", tag="s1")); expect("4-й RED — запросов по-прежнему 1", n(), 1)
shift_first_red("s1", 20)
rcs.append(run("ok", tag="s1")); expect("GREEN — ровно 1 запрос «восстановлена»", n(), 2)
print("   текст:", reqs[1][1]["text"][0]); assert "восстановлена" in reqs[1][1]["text"][0] and "≈ 2" in reqs[1][1]["text"][0]
rcs.append(run("ok", tag="s1")); expect("ещё GREEN — новых запросов нет", n(), 2)
expect("коды выхода RED×4=1, GREEN=0", rcs, [1, 1, 1, 1, 0, 0])
log = open(os.path.join(tmp, "s1", "log")).read()
expect("журнал: ALERT sent ×2", log.count("ALERT sent"), 2)
assert "TESTTOKEN" not in log

# Сценарий 2: 1 RED → GREEN — ни одного запроса
before = n(); run("red", tag="s2"); run("ok", tag="s2"); expect("1 RED → GREEN — запросов 0", n() - before, 0)

# Сценарий 3: нет токена — молчит, журнал прежний
before = n()
for _ in range(4): run("red", token=None, tag="s3")
expect("без токена — запросов 0", n() - before, 0)
assert "ALERT" not in open(os.path.join(tmp, "s3", "log")).read()

# Сценарий 4: отправка падает (HTTP 500) — вердикт и код выхода не меняются, в журнале ALERT failed, повтор на следующем RED
mode["status"] = 500; before = n(); rc = [run("red", tag="s4") for _ in range(4)]
log = open(os.path.join(tmp, "s4", "log")).read()
expect("при сбое отправки код выхода = 1", rc, [1, 1, 1, 1])
expect("при сбое: ALERT failed ×2 (3-й и 4-й прогон — повтор)", log.count("ALERT failed"), 2)
mode["status"] = 200; run("red", tag="s4"); expect("после восстановления API — 1 «недоступна» уходит", n() - before - 2, 1)

# Сценарий 5: порог переопределяется
before = n(); [run("red", tag="s5", extra={"ALERT_AFTER_FAILS": "2"}) for _ in range(2)]; expect("ALERT_AFTER_FAILS=2 — 1 запрос на 2-м RED", n() - before, 1)

# Сценарий 6: CRASH (healthcheck падает rc>1) тоже считается
open(stub, "w").write("import sys; sys.exit(3)\n"); before = n()
rc = [run("red", tag="s6") for _ in range(3)]
expect("CRASH×3 — 1 запрос, код выхода 2", (n() - before, rc[-1]), (1, 2))
print("ИТОГО провалов:", fails); sys.exit(1 if fails else 0)
