#!/bin/bash
# deploy_backend_vps.sh — синхронизация deliver.py/healthcheck.py/watchdog.py
# (и вспомогательных файлов healthcheck.py) на VPS + проверка расхождения.
#
# round38, блок D4: round37 нашёл, что deliver.py/healthcheck.py на VPS были
# копией ДО round35 — весь механизм прогрева GWC, задокументированный в
# CLAUDE.md как "включён по умолчанию", никогда физически не доезжал до
# прод-сервера (для фронтенда есть deploy_frontend_vps.sh, для этих трёх
# файлов выделенного скрипта не было). Исправлено вручную в round37
# (docs/round37-filtering.md, блок C) — здесь то же самое формализовано,
# чтобы рассинхрон не копился молча снова.
#
# round38 также нашёл (см. docs/round38-data-incident.md, блок C2), что на
# VPS вопреки CLAUDE.md ("watchdog — только на эмуляторе") тоже работает
# pikurr-watchdog.service — если watchdog.py меняется, его стоит
# перезапустить, иначе новый код подхватится только при следующей
# перезагрузке юнита.
#
# Использование:
#   REPIKURR/deploy_backend_vps.sh --check     # только показать расхождение, не трогать VPS
#   REPIKURR/deploy_backend_vps.sh --apply      # синхронизировать (с бэкапом старых файлов)
#
# Требует: ssh-доступ к VPS без пароля (sudo -n работает на VPS — CLAUDE.md).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VPS_HOST="${VPS_HOST:-sgr@158.160.237.90}"
VPS_REMOTE_DIR="${VPS_REMOTE_DIR:-~/repikurr}"
TS="$(date +%Y%m%d_%H%M%S)"

MODE="${1:---check}"
if [[ "$MODE" != "--check" && "$MODE" != "--apply" ]]; then
    echo "Использование: $0 [--check|--apply]" >&2
    exit 2
fi

log() { echo "[$(date '+%F %T')] $*"; }

# Основные файлы: python-скрипты REPIKURR/*.py, которые реально исполняются
# на VPS. Список тот же, что `ls REPIKURR/*.py` (3 файла на момент round38:
# deliver.py, healthcheck.py, watchdog.py) — если появится новый, добавить
# сюда явно (сознательно не собираем список автоматически, чтобы скрипт не
# начал молча синхронизировать что-то новое без явного решения).
CORE_FILES=(deliver.py healthcheck.py watchdog.py)

# Вспомогательные данные healthcheck.py (round37, блок C: без них
# gwc_layer[...]/filtered_layer красные по причине "файл не найден", не по
# реальной проблеме — на плоском развёртывании VPS нет docs/tools/smoke).
declare -A SUPPORT_FILES=(
    ["docs/round32_assets/tiles_with_data.json"]="support_data/tiles_with_data.json"
    ["REPIKURR/tools/smoke/captured_gwc_urls.json"]="support_data/captured_gwc_urls.json"
)

drift_found=0

log "=== Проверка расхождения VPS ($VPS_HOST:$VPS_REMOTE_DIR) против репозитория ==="
for f in "${CORE_FILES[@]}"; do
    local_sha="$(sha256sum "$SCRIPT_DIR/$f" | cut -d' ' -f1)"
    remote_sha="$(ssh "$VPS_HOST" "sha256sum $VPS_REMOTE_DIR/$f 2>/dev/null | cut -d' ' -f1" || true)"
    if [[ -z "$remote_sha" ]]; then
        log "  РАСХОЖДЕНИЕ: $f — на VPS файл отсутствует"
        drift_found=1
    elif [[ "$local_sha" != "$remote_sha" ]]; then
        log "  РАСХОЖДЕНИЕ: $f — репозиторий=$local_sha VPS=$remote_sha"
        drift_found=1
    else
        log "  OK: $f — совпадает ($local_sha)"
    fi
done

for repo_rel in "${!SUPPORT_FILES[@]}"; do
    remote_rel="${SUPPORT_FILES[$repo_rel]}"
    local_path="$REPO_ROOT/$repo_rel"
    if [[ ! -f "$local_path" ]]; then
        log "  (пропуск: $repo_rel не существует в репозитории)"
        continue
    fi
    local_sha="$(sha256sum "$local_path" | cut -d' ' -f1)"
    remote_sha="$(ssh "$VPS_HOST" "sha256sum $VPS_REMOTE_DIR/$remote_rel 2>/dev/null | cut -d' ' -f1" || true)"
    if [[ "$local_sha" != "$remote_sha" ]]; then
        log "  РАСХОЖДЕНИЕ: $repo_rel → $remote_rel (VPS=${remote_sha:-отсутствует})"
        drift_found=1
    else
        log "  OK: $repo_rel → $remote_rel"
    fi
done

if [[ "$MODE" == "--check" ]]; then
    if [[ "$drift_found" -eq 0 ]]; then
        log "=== Расхождений не найдено ==="
        exit 0
    else
        log "=== Есть расхождения — для синхронизации: $0 --apply ==="
        exit 1
    fi
fi

# --apply: синхронизация с бэкапом старых файлов на VPS.
if [[ "$drift_found" -eq 0 ]]; then
    log "Расхождений нет, синхронизировать нечего."
    exit 0
fi

log "=== Синхронизация (бэкапы с суффиксом .bak_pre_deploy_${TS}) ==="
watchdog_changed=0
for f in "${CORE_FILES[@]}"; do
    local_sha="$(sha256sum "$SCRIPT_DIR/$f" | cut -d' ' -f1)"
    remote_sha="$(ssh "$VPS_HOST" "sha256sum $VPS_REMOTE_DIR/$f 2>/dev/null | cut -d' ' -f1" || true)"
    if [[ "$local_sha" == "$remote_sha" ]]; then
        continue
    fi
    log "  $f: бэкап + копирование..."
    ssh "$VPS_HOST" "test -f $VPS_REMOTE_DIR/$f && cp $VPS_REMOTE_DIR/$f $VPS_REMOTE_DIR/${f}.bak_pre_deploy_${TS} || true"
    scp -q "$SCRIPT_DIR/$f" "$VPS_HOST:$VPS_REMOTE_DIR/$f"
    if [[ "$f" == "watchdog.py" ]]; then
        watchdog_changed=1
    fi
done

for repo_rel in "${!SUPPORT_FILES[@]}"; do
    remote_rel="${SUPPORT_FILES[$repo_rel]}"
    local_path="$REPO_ROOT/$repo_rel"
    [[ -f "$local_path" ]] || continue
    local_sha="$(sha256sum "$local_path" | cut -d' ' -f1)"
    remote_sha="$(ssh "$VPS_HOST" "sha256sum $VPS_REMOTE_DIR/$remote_rel 2>/dev/null | cut -d' ' -f1" || true)"
    [[ "$local_sha" == "$remote_sha" ]] && continue
    log "  $repo_rel → $remote_rel: копирование..."
    ssh "$VPS_HOST" "mkdir -p $(dirname "$VPS_REMOTE_DIR/$remote_rel")"
    scp -q "$local_path" "$VPS_HOST:$VPS_REMOTE_DIR/$remote_rel"
done

log "Проверка синтаксиса на VPS (py_compile)..."
ssh "$VPS_HOST" "cd $VPS_REMOTE_DIR && python3 -m py_compile ${CORE_FILES[*]}"
log "  OK — синтаксис корректен."

if [[ "$watchdog_changed" -eq 1 ]]; then
    log "watchdog.py изменился — перезапускаю pikurr-watchdog.service (sudo -n на VPS)..."
    ssh "$VPS_HOST" "sudo -n systemctl restart pikurr-watchdog.service"
    log "  OK — сервис перезапущен."
fi

log "=== Синхронизация завершена. Повторная проверка: $0 --check ==="
