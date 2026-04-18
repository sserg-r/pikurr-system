#!/bin/bash
# Сборка пакета обновлений PIKURR и отправка на сервер с фронтендом.
# Использование: ./package_and_push.sh
# Конфигурация: переменные DELIVERY_* в .env
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Загружаем .env (только переменные, без экспорта системных)
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
else
    echo "Ошибка: файл .env не найден" >&2
    exit 1
fi

# Параметры доставки — берём из .env, с fallback-значениями
DELIVERY_HOST="${DELIVERY_HOST:-192.168.251.190}"
DELIVERY_USER="${DELIVERY_USER:-user}"
DELIVERY_INBOX="${DELIVERY_INBOX:-/home/user/repikurr/inbox}"
DELIVERY_SSH_KEY="${DELIVERY_SSH_KEY:-$HOME/.ssh/id_rsa}"
HOST_OUTPUT_DIR="${HOST_OUTPUT_DIR:-./outputs}"

# ─── Сборка пакета ────────────────────────────────────────────────────────────
echo ""
echo "=== [1/2] Сборка пакета ==="
PACKAGE_LOG=$(docker compose run --rm etl python -m src.tasks.package 2>&1 | tee /dev/stderr)

# Ищем строку вида "OUTPUT: /data_output/dist/pikurr_update_....zip"
CONTAINER_PATH=$(echo "$PACKAGE_LOG" | grep "^OUTPUT:" | awk '{print $2}' || true)

if [ -z "$CONTAINER_PATH" ]; then
    echo "" >&2
    echo "Ошибка: пакет не создан — строка OUTPUT не найдена в выводе." >&2
    exit 1
fi

# Конвертируем путь внутри контейнера (/data_output/dist/...) в путь на хосте
FILENAME=$(basename "$CONTAINER_PATH")
HOST_PATH="$HOST_OUTPUT_DIR/dist/$FILENAME"

if [ ! -f "$HOST_PATH" ]; then
    echo "Ошибка: ожидаемый файл не найден: $HOST_PATH" >&2
    exit 1
fi

# ─── Отправка ─────────────────────────────────────────────────────────────────
echo ""
echo "=== [2/2] Отправка на сервер ==="
echo "  Файл:    $FILENAME"
echo "  Куда:    $DELIVERY_USER@$DELIVERY_HOST:$DELIVERY_INBOX/"
echo "  SSH key: $DELIVERY_SSH_KEY"
echo ""

rsync -avz --progress \
    -e "ssh -i $DELIVERY_SSH_KEY -o StrictHostKeyChecking=no" \
    "$HOST_PATH" \
    "$DELIVERY_USER@$DELIVERY_HOST:$DELIVERY_INBOX/"

echo ""
echo "=== Готово: $FILENAME отправлен на $DELIVERY_HOST ==="
