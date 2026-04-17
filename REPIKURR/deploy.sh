#!/bin/bash
# deploy.sh — чистое развёртывание REPIKURR на сервере с нуля.
#
# Использование:
#   bash deploy.sh          — полный деплой (останавливает старый стек)
#   bash deploy.sh --clean  — то же + удаляет volumes (сброс БД и растров)
#
# Требования:
#   - docker, docker compose
#   - sudo (для systemd)
#   - git (если нужен pull)
#
# После успешного завершения:
#   - Контейнеры запущены: postgis, geoserver, react, nginx
#   - watchdog запущен как systemd-сервис pikurr-watchdog
#   - inbox/ готова к приёму пакетов

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.server.yml"
SERVICE_SRC="$SCRIPT_DIR/pikurr-watchdog.service"
SERVICE_DST="/etc/systemd/system/pikurr-watchdog.service"
GEODATA_DIR="$SCRIPT_DIR/data/geodata"
INBOX_DIR="$SCRIPT_DIR/inbox"

CLEAN=false
if [[ "${1:-}" == "--clean" ]]; then
    CLEAN=true
fi

log() { echo "[$(date '+%F %T')] $*"; }

# ---------------------------------------------------------------------------
log "=== PIKURR deploy ==="
log "SCRIPT_DIR : $SCRIPT_DIR"
log "CLEAN      : $CLEAN"

# 1. Остановить старый стек
log "Останавливаю старый стек..."
if $CLEAN; then
    docker compose -f "$COMPOSE_FILE" down -v --remove-orphans || true
else
    docker compose -f "$COMPOSE_FILE" down --remove-orphans || true
fi

# 2. Удалить данные (только при --clean)
if $CLEAN; then
    log "Очищаю данные (--clean)..."
    rm -rf "$GEODATA_DIR"
fi

# 3. Создать необходимые директории (если не существуют)
log "Создаю директории..."
mkdir -p "$GEODATA_DIR"
mkdir -p "$INBOX_DIR"
# GeoServer пишет/читает через docker mount ./data → /mnt/data
# и ./geoserver_data → /opt/geoserver/data_dir.
# Права должны быть открыты, т.к. контейнер работает под другим UID.
chmod -R 777 "$SCRIPT_DIR/data"
# geoserver_data частично принадлежит UID контейнера (gwc, logs) — игнорируем ошибки прав
chmod -R 777 "$SCRIPT_DIR/geoserver_data" 2>/dev/null || true

# 4. Поднять стек
log "Запускаю контейнеры..."
docker compose -f "$COMPOSE_FILE" up -d --build

# 5. Дождаться готовности GeoServer (healthcheck по REST API)
log "Жду готовности GeoServer (до 120 сек)..."
GEOSERVER_URL="http://localhost:8090/geoserver/rest/about/version.json"
for i in $(seq 1 24); do
    if curl -sf -u admin:geoserver "$GEOSERVER_URL" > /dev/null 2>&1; then
        log "GeoServer готов."
        break
    fi
    if [[ $i -eq 24 ]]; then
        log "WARN: GeoServer не ответил за 120 сек — продолжаем без проверки."
    fi
    sleep 5
done

# 6. Установить systemd-сервис для watchdog
if [[ -f "$SERVICE_SRC" ]]; then
    log "Устанавливаю systemd-сервис pikurr-watchdog..."

    # Заменяем /home/user/repikurr на реальный путь (на случай другого имени пользователя)
    sed "s|/home/user/repikurr|$SCRIPT_DIR|g" "$SERVICE_SRC" \
        | sudo tee "$SERVICE_DST" > /dev/null

    sudo systemctl daemon-reload
    sudo systemctl enable pikurr-watchdog
    sudo systemctl restart pikurr-watchdog
    log "Статус watchdog:"
    sudo systemctl status pikurr-watchdog --no-pager -l || true
else
    log "WARN: pikurr-watchdog.service не найден — watchdog не установлен."
fi

# ---------------------------------------------------------------------------
log "=== Развёртывание завершено ==="
log ""
log "Сервисы:"
docker compose -f "$COMPOSE_FILE" ps
log ""
log "Следующий шаг: доставить пакет данных:"
log "  rsync -avz pikurr_update_*.zip user@$(hostname -I | awk '{print $1}'):$INBOX_DIR/"
log "watchdog подхватит автоматически. Логи: journalctl -fu pikurr-watchdog"
