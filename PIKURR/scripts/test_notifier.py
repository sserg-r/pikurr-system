"""Тест оповещателя без сети (round61, блок C): requests.post подменён.
`python3 scripts/test_notifier.py [путь_к_notifier.py]` — второй аргумент нужен для
контроля на исходном коде (git show HEAD~:PIKURR/src/services/notifier.py)."""
import importlib.util, os, sys, types

ns = types.SimpleNamespace
cfg = types.ModuleType("src.core.config")
cfg.settings = ns(telegram=ns(token="TEST-TOKEN", chat_id="123"))
for n in ("src", "src.core"):
    sys.modules.setdefault(n, types.ModuleType(n)).__path__ = []
sys.modules["src.core.config"] = cfg

calls = []
def fake_post(url, data=None, timeout=None):
    calls.append((url, dict(data)))
    return ns(status_code=200, text="ok")
import requests
requests.post = fake_post

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src/services/notifier.py")
spec = importlib.util.spec_from_file_location("notifier_under_test", path)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

msg = "Ошибка: файл pikurr_update_2025_x.zip, a*b, [x], `y"
mod.TelegramNotifier().send(msg, status="error")
url, data = calls[-1]
print("parse_mode в запросе:", data.get("parse_mode", "ОТСУТСТВУЕТ"))
ok = "parse_mode" not in data and msg in data["text"] and "*" in data["text"] and data["text"].startswith("🚨 PIKURR System")
print("текст передан как есть, без parse_mode:", ok)

# не настроено — молчит
mod.settings = ns(telegram=ns(token="", chat_id=""))
n0 = len(calls); mod.TelegramNotifier().send("x"); silent = len(calls) == n0
print("не настроено — запросов:", len(calls) - n0)
sys.exit(0 if (ok and silent) else 1)
