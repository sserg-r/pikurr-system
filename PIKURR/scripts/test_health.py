"""Тесты индикаторов панели (round61, блок B). Без сети, GPU и реальных ключей:
`python3 scripts/test_health.py` из каталога PIKURR (или pytest). Реальные InferenceService/GEEService
используются как есть; подменены только внешние модули (onnxruntime, ee) и settings.

Ключ GEE в тестах — заведомо фиктивный; содержимое в вывод не попадает."""
import os
import sys
import tempfile
import types

# --- заглушка src.core.config (настоящий требует полного окружения) ---------
tmp_model = tempfile.NamedTemporaryFile(suffix=".onnx", delete=False)
tmp_model.write(b"x")
tmp_model.close()

ns = types.SimpleNamespace
fake_settings = ns(
    inference=ns(onnx_model_path=tmp_model.name, provider="CUDAExecutionProvider",
                 intra_op_num_threads=None, inter_op_num_threads=None, batch_size=8),
    gee=ns(service_account={"type": "service_account", "client_email": "x@y.iam.gserviceaccount.com",
                            "private_key": "not-a-key", "token_uri": "https://oauth2.googleapis.com/token"},
           project="p"),
)
cfg = types.ModuleType("src.core.config")
cfg.settings = fake_settings
sys.modules.setdefault("src", types.ModuleType("src")).__path__ = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")]
sys.modules.setdefault("src.core", types.ModuleType("src.core")).__path__ = []
sys.modules["src.core.config"] = cfg

from src.services import health  # noqa: E402


def fake_ort(providers):
    m = types.ModuleType("onnxruntime")

    class Opts:
        intra_op_num_threads = inter_op_num_threads = None

    class Sess:
        def __init__(self, path, sess_options=None, providers=None):
            pass

        def get_providers(self):
            return list(fake_ort.active)

        def get_inputs(self):
            return [ns(name="input")]

    m.SessionOptions = Opts
    m.InferenceSession = Sess
    m.get_available_providers = lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"]
    fake_ort.active = providers
    return m


def inference_with(providers):
    sys.modules["onnxruntime"] = fake_ort(providers)
    sys.modules.pop("src.services.inference", None)
    health.reset_cache()
    return health.check_inference()


def test_inference_cuda_ok():
    s = inference_with(["CUDAExecutionProvider", "CPUExecutionProvider"])
    assert s.state == health.OK and "CUDA активна" in s.text, s


def test_inference_cpu_fallback_is_error():
    s = inference_with(["CPUExecutionProvider"])
    assert s.state == health.ERROR, s
    assert "CPUExecutionProvider" in s.text and "CUDA не инициализирована" in s.text, s
    assert "etl" in s.hint


def test_inference_model_missing():
    old = fake_settings.inference.onnx_model_path
    fake_settings.inference.onnx_model_path = "/nonexistent/model.onnx"
    try:
        s = inference_with(["CUDAExecutionProvider"])
    finally:
        fake_settings.inference.onnx_model_path = old
    assert s.state == health.ERROR and "модель не найдена" in s.text, s


def gee_with_fake_ee(value=1):
    ee = types.ModuleType("ee")
    ee.Initialize = lambda credentials=None: None
    ee.Number = lambda n: ns(getInfo=lambda: value)
    sys.modules["ee"] = ee
    sys.modules.pop("src.services.gee", None)


def test_gee_valid_key_ok():
    # реальный GEEService, подменена только проверка подписи ключа и ee
    gee_with_fake_ee()
    from google.oauth2 import service_account
    orig = service_account.Credentials.from_service_account_info
    service_account.Credentials.from_service_account_info = classmethod(
        lambda cls, info, **kw: ns(with_scopes=lambda s: object()))
    try:
        s = health.check_gee()
    finally:
        service_account.Credentials.from_service_account_info = orig
    assert s.state == health.OK and "авторизация подтверждена" in s.text, s


def test_gee_broken_key_is_error_without_leak():
    gee_with_fake_ee()
    s = health.check_gee()  # настоящий разбор ключа «not-a-key» падает
    assert s.state == health.ERROR and s.text.startswith("❌ GEE: ошибка — "), s
    assert "not-a-key" not in s.text and len(s.text) < 260, s


def test_gee_server_error_is_error_and_network_is_unverified():
    gee_with_fake_ee()
    health._gee_probe, orig = (lambda: (_ for _ in ()).throw(ValueError("bad"))), health._gee_probe
    try:
        assert health.check_gee().state == health.ERROR
        health._gee_probe = lambda: (_ for _ in ()).throw(ConnectionError("down"))
        assert health.check_gee().state == health.UNVERIFIED
        health.GEE_TIMEOUT_S, t0 = 0.2, health.GEE_TIMEOUT_S
        import time
        health._gee_probe = lambda: time.sleep(2)
        s = health.check_gee()
        health.GEE_TIMEOUT_S = t0
        assert s.state == health.UNVERIFIED and "таймаут" in s.text
    finally:
        health._gee_probe = orig


def test_sanitize_hides_key_like_text():
    # маркер собран из частей, чтобы сканер секретов носителя не принимал тест за ключ
    marker = "-----" + "BEGIN PRIV" + "ATE KEY-----"
    assert "BEGIN" not in health.sanitize("x " + marker + " y")
    assert "private_key" not in health.sanitize("bad {'private_key': 'zzz'}")
    assert len(health.sanitize("a" * 1000)) == 200


def test_cache_and_reset():
    calls = []
    health._CHECKS["gee"], orig = (lambda: calls.append(1) or health.Status(health.OK, "ok", "00:00")), health._CHECKS["gee"]
    try:
        health.reset_cache()
        t = [0.0]
        health.get_status("gee", now=lambda: t[0])
        t[0] = 599
        health.get_status("gee", now=lambda: t[0])
        assert len(calls) == 1
        t[0] = 601
        health.get_status("gee", now=lambda: t[0])
        assert len(calls) == 2
        health.reset_cache()
        health.get_status("gee", now=lambda: t[0])
        assert len(calls) == 3
    finally:
        health._CHECKS["gee"] = orig


def test_check_crash_does_not_raise():
    health._CHECKS["gee"], orig = (lambda: 1 / 0), health._CHECKS["gee"]
    try:
        health.reset_cache()
        assert health.get_status("gee").state == health.ERROR
    finally:
        health._CHECKS["gee"] = orig


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("PASS", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, type(e).__name__, str(e)[:200])
    sys.exit(1 if fails else 0)
