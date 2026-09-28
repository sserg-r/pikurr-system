#!/bin/bash
# backup_config_offsite.sh — резервное копирование конфигурации VPS за
# пределы самой ВМ (round43, блок D).
#
# Данные БД защищены дампами перед каждой подменой (deliver.py,
# backup_before_swap, round38). Конфигурация — нет: часть уже лежит в
# git (docker-compose.vps.yml, Caddyfile, geoserver_data/workspaces,
# geoserver_data/styles — см. `git ls-files REPIKURR/geoserver_data/`),
# но GWC-конфигурация (geowebcache.xml, диски квоты, per-layer настройки
# в gwc-layers/) и все секреты (geoserver_data/security/**, deliver.env,
# .env) существуют ТОЛЬКО на самой ВМ — при полной потере ВМ (не только
# данных БД) их взять неоткуда.
#
# Запускать с машины, у которой уже есть рабочий SSH-доступ к VPS
# (координаторская — проверено фактом round43; стенд не имеет прямого
# SSH до VPS — отдельное решение о доверии ключей, не в этом раунде).
#
# Секреты и не-секретная конфигурация архивируются ОТДЕЛЬНО:
#   - config: geoserver_data/gwc/*.xml, geoserver_data/gwc-layers/*.xml
#     — не секрет, но нужен для полного восстановления GWC (метатайлы,
#     квота, gridset-настройки, если когда-либо станут нестандартными).
#   - secrets: geoserver_data/security/** (пароли/jceks/users/roles),
#     deliver.env, .env — НИКОГДА не в git (см. CLAUDE.md "Не делать").
#     Хранится локально с правами 600, отдельно от config-архива.
#
# Использование:
#   REPIKURR/backup_config_offsite.sh              # сделать бэкап сейчас
#   REPIKURR/backup_config_offsite.sh --restore-config-to <dir>
#                                                   # распаковать последний
#                                                   # config-архив в <dir>
#                                                   # (для проверки на эмуляторе)
#
# Ротация — по числу файлов (как REPIKURR/backups/ для БД), по умолчанию
# 10 последних архивов каждого вида.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VPS_HOST="${VPS_HOST:-sgr@158.160.237.90}"
VPS_REMOTE_DIR="${VPS_REMOTE_DIR:-~/repikurr}"
LOCAL_BACKUP_DIR="${LOCAL_BACKUP_DIR:-$REPO_ROOT/config_backups_offsite}"
RETENTION_COUNT="${RETENTION_COUNT:-10}"
TS="$(date +%Y%m%d_%H%M%S)"

log() { echo "[$(date '+%F %T')] $*"; }

if [[ "${1:-}" == "--restore-config-to" ]]; then
    TARGET_DIR="${2:?Укажите каталог назначения}"
    LATEST_CONFIG=$(ls -t "$LOCAL_BACKUP_DIR"/config_*.tar.gz 2>/dev/null | head -1)
    if [[ -z "$LATEST_CONFIG" ]]; then
        echo "Нет ни одного config-архива в $LOCAL_BACKUP_DIR" >&2
        exit 1
    fi
    log "Распаковываю $LATEST_CONFIG в $TARGET_DIR"
    mkdir -p "$TARGET_DIR"
    tar -xzf "$LATEST_CONFIG" -C "$TARGET_DIR"
    log "Готово. Содержимое:"
    find "$TARGET_DIR" -type f | sort
    exit 0
fi

mkdir -p "$LOCAL_BACKUP_DIR"
chmod 700 "$LOCAL_BACKUP_DIR"

log "=== Резервное копирование конфигурации VPS ($VPS_HOST:$VPS_REMOTE_DIR) ==="

# --- config (не секрет) ---
CONFIG_ARCHIVE="$LOCAL_BACKUP_DIR/config_${TS}.tar.gz"
log "Собираю config-архив на VPS..."
ssh "$VPS_HOST" "cd $VPS_REMOTE_DIR && tar -czf /tmp/backup_config_${TS}.tar.gz \
    geoserver_data/gwc/*.xml \
    geoserver_data/gwc-layers/*.xml \
    2>/dev/null || true"
scp -q "$VPS_HOST:/tmp/backup_config_${TS}.tar.gz" "$CONFIG_ARCHIVE"
ssh "$VPS_HOST" "rm -f /tmp/backup_config_${TS}.tar.gz"
log "Config-архив: $CONFIG_ARCHIVE ($(du -h "$CONFIG_ARCHIVE" | cut -f1))"

# --- secrets (НИКОГДА не в git) ---
SECRETS_ARCHIVE="$LOCAL_BACKUP_DIR/secrets_${TS}.tar.gz"
log "Собираю secrets-архив на VPS..."
ssh "$VPS_HOST" "cd $VPS_REMOTE_DIR && sudo -n tar -czf /tmp/backup_secrets_${TS}.tar.gz \
    geoserver_data/security \
    deliver.env \
    .env \
    2>/dev/null || true"
ssh "$VPS_HOST" "sudo -n chown \$(whoami) /tmp/backup_secrets_${TS}.tar.gz"
scp -q "$VPS_HOST:/tmp/backup_secrets_${TS}.tar.gz" "$SECRETS_ARCHIVE"
ssh "$VPS_HOST" "rm -f /tmp/backup_secrets_${TS}.tar.gz"
chmod 600 "$SECRETS_ARCHIVE"
log "Secrets-архив: $SECRETS_ARCHIVE ($(du -h "$SECRETS_ARCHIVE" | cut -f1)), права 600"

# --- ротация ---
for pattern in "config_*.tar.gz" "secrets_*.tar.gz"; do
    ls -t "$LOCAL_BACKUP_DIR"/$pattern 2>/dev/null | tail -n +$((RETENTION_COUNT + 1)) | while read -r old; do
        log "Ротация: удаляю $old"
        rm -f "$old"
    done
done

log "=== Готово. Локальная копия: $LOCAL_BACKUP_DIR ==="
