#!/bin/bash
# deploy_frontend_vps.sh — раскатка ТОЛЬКО react-образа на VPS, с
# обязательным дымовым сценарием как условием успеха.
#
# round35, блок B3: выкатка фронтенда не считается завершённой без
# зелёного прогона `tools/smoke/smoke.mjs` (правило CLAUDE.md, введено
# round34 A3 — healthcheck.py не поймал сломанный растровый слой ровно
# потому, что верификация была без реального браузера). Раньше эта
# последовательность (build → бэкап тега → save|scp|load → retag →
# force-recreate) выполнялась вручную по шагам из отчёта round34 —
# формализована здесь, чтобы шаг со smoke.mjs нельзя было случайно
# пропустить.
#
# Выбор: скрипт выкатки САМ вызывает smoke.mjs (не отдельный шаг в
# инструкции) — инструкция полагается на то, что оператор её прочитает
# и не забудет последний пункт; скрипт технически не даёт считать
# деплой успешным (ненулевой exit code) без зелёного прогона. Цена —
# скрипт должен уметь ставить Node/Playwright, если их нет (см. ниже) —
# принято, это одноразовые накладные расходы, а не риск пропущенного
# шага при каждой раскатке.
#
# Использование:
#   REPIKURR/deploy_frontend_vps.sh
#
# Требует: docker (локально, для сборки), ssh-доступ к VPS без пароля,
# Node 20+ и подготовленный REPIKURR/tools/smoke (npm install +
# playwright install chromium — один раз, см. README самого smoke).
#
# Откат при провале smoke (скрипт НЕ делает это автоматически —
# решение о том, оставлять ли заведомо проверенный сломанным билд,
# принимает оператор):
#   ssh sgr@158.160.237.90 "docker tag repikurr-react:pre_deploy_<TS> repikurr-react:latest && \
#     cd ~/repikurr && docker compose -f docker-compose.vps.yml up -d --force-recreate react-client"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REACT_DIR="$SCRIPT_DIR/repikurr"
SMOKE_DIR="$SCRIPT_DIR/tools/smoke"
VPS_HOST="${VPS_HOST:-sgr@158.160.237.90}"
VPS_COMPOSE_FILE="${VPS_COMPOSE_FILE:-docker-compose.vps.yml}"
VPS_REMOTE_DIR="${VPS_REMOTE_DIR:-~/repikurr}"
BASE_URL="${BASE_URL:-https://geobotany.of.by}"
TS="$(date +%Y%m%d%H%M%S)"
TAG="round_deploy_${TS}"
BACKUP_TAG="pre_deploy_${TS}"

log() { echo "[$(date '+%F %T')] $*"; }

log "=== deploy_frontend_vps: сборка ${TAG} ==="
docker build -t "repikurr-react:${TAG}" "$REACT_DIR"

log "Бэкап текущего образа на VPS под тегом ${BACKUP_TAG}..."
ssh "$VPS_HOST" "docker tag repikurr-react:latest repikurr-react:${BACKUP_TAG}"
log "Откат при необходимости:"
log "  ssh $VPS_HOST \"docker tag repikurr-react:${BACKUP_TAG} repikurr-react:latest && cd $VPS_REMOTE_DIR && docker compose -f $VPS_COMPOSE_FILE up -d --force-recreate react-client\""

TMP_TAR="/tmp/repikurr-react-${TAG}.tar.gz"
log "Перенос образа (docker save | gzip | scp | docker load)..."
docker save "repikurr-react:${TAG}" | gzip > "$TMP_TAR"
scp "$TMP_TAR" "$VPS_HOST:/tmp/"
ssh "$VPS_HOST" "gunzip -c /tmp/$(basename "$TMP_TAR") | docker load && rm /tmp/$(basename "$TMP_TAR")"
rm -f "$TMP_TAR"

log "Тегирование и пересоздание контейнера react-client..."
ssh "$VPS_HOST" "docker tag repikurr-react:${TAG} repikurr-react:latest && \
  cd $VPS_REMOTE_DIR && docker compose -f $VPS_COMPOSE_FILE up -d --force-recreate react-client"

log "=== Дымовой сценарий (обязателен — деплой не считается завершённым без него) ==="
if [ ! -d "$SMOKE_DIR/node_modules" ]; then
    log "node_modules отсутствует в $SMOKE_DIR — устанавливаю зависимости (один раз)..."
    (cd "$SMOKE_DIR" && npm install && npx playwright install chromium)
fi

if (cd "$SMOKE_DIR" && BASE_URL="$BASE_URL" node smoke.mjs); then
    log "=== Дымовой сценарий ПРОЙДЕН — деплой завершён успешно (${TAG}) ==="
    exit 0
else
    log "=== Дымовой сценарий ПРОВАЛЕН — деплой ${TAG} НЕ считается завершённым ==="
    log "На проде сейчас уже раскатан ${TAG} (не откачен автоматически) — решение об откате за оператором, команда выше."
    exit 1
fi
