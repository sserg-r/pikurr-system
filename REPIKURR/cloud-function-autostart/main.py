"""
Yandex Cloud Function — автоперезапуск прерываемой ВМ REPIKURR (round22,
задача 5). Прерываемую ВМ невозможно перезапустить изнутри (гарантированно
останавливается принудительно не позже чем через 24ч, может раньше) —
эта функция дёргает Compute API снаружи по таймеру.

Аутентификация к Compute API — через сервисный аккаунт, привязанный к самой
функции (не отдельный ключ в коде): IAM-токен берётся из метаданных функции,
тем же способом, что на инстансах Compute Cloud.

Переменные окружения функции (задаются в консоли/при деплое, не в коде):
  INSTANCE_ID — id ВМ REPIKURR.

Роль сервисного аккаунта — минимальная, только на этот инстанс (не на весь
folder): compute.instances.get + compute.instances.start. См. README.md,
раздел "Сервисный аккаунт".
"""
import json
import os
import time
import urllib.request
import urllib.error

METADATA_TOKEN_URL = (
    "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/"
    "default/token"
)
COMPUTE_API_BASE = "https://compute.api.cloud.yandex.net/compute/v1/instances"


def _get_iam_token() -> str:
    req = urllib.request.Request(
        METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.load(resp)["access_token"]


def _api_get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def _api_post(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Length": "0"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def handler(event, context):
    instance_id = os.environ["INSTANCE_ID"]
    token = _get_iam_token()

    instance = _api_get(f"{COMPUTE_API_BASE}/{instance_id}", token)
    status = instance.get("status")
    print(f"[autostart] instance={instance_id} status={status}")

    if status == "RUNNING":
        print("[autostart] уже RUNNING — ничего не делаю")
        return {"statusCode": 200, "body": "already running"}

    if status in ("STARTING", "PROVISIONING"):
        # round22, задача 5: не дёргать start повторно, пока инстанс уже
        # запускается — повторный вызов start на переходном статусе — лишний
        # API-вызов и потенциальная ошибка 409, ничего не даёт по существу.
        print(f"[autostart] уже в переходном статусе {status} — не дёргаю start повторно")
        return {"statusCode": 200, "body": f"already transitioning: {status}"}

    if status == "STOPPED":
        print("[autostart] STOPPED — вызываю start")
        try:
            result = _api_post(f"{COMPUTE_API_BASE}/{instance_id}:start", token)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"[autostart] ОШИБКА start: {e.code} {body}")
            return {"statusCode": 500, "body": f"start failed: {e.code}"}
        print(f"[autostart] start запущен, operation id={result.get('id')}")
        return {"statusCode": 200, "body": f"start triggered: {result.get('id')}"}

    # STOPPING, DELETING, ERROR и т.п. — не наша забота, просто залогировать.
    print(f"[autostart] статус {status} не обрабатывается автоматически")
    return {"statusCode": 200, "body": f"status not handled: {status}"}
