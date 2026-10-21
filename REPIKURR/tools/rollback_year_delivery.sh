#!/usr/bin/env bash
# Откат доставки нового года (два года -> прежний один) — round64.
#
# Запускается НА целевой машине (VPS или эмулятор), в каталоге развёртывания
# (~/repikurr), от пользователя, который запускает deliver.py. Значения переменных
# окружения не печатаются.
#
# Что делает (проверено на эмуляторе, round64, блок B5):
#   1. повторная доставка ПРЕЖНЕГО пакета (один год) штатным deliver.py — подменяет
#      agrifields/razgrafka/assessment, пересоздаёт и обновляет представления,
#      возвращает URL стора image_assessment на geodata/<прежний год>, пишет
#      year_district.json, прогревает GWC, запускает healthcheck;
#      нужны ОБА флага: --allow-year-change (состав лет {2025,2026} -> {2025}) и
#      --allow-shrink (assessment 111 568 -> 55 784 строк, усадка больше 10 %);
#   2. каталог нового года data/geodata/<год> переносится в _removed_<метка>/ (не удаляется);
#   3. стор image_assessment_<прежний год>, созданный доставкой, удаляется из GeoServer
#      (purge=none — файлы растров НЕ трогаются; сам стор больше не нужен, т.к.
#      прежний год снова последний и обслуживается стором image_assessment).
#
# Использование:
#   tools/rollback_year_delivery.sh <пакет_прежнего_года.zip> <новый_год> <прежний_год>
#   например: tools/rollback_year_delivery.sh ~/repikurr/manual/pikurr_update_2025_2026-10-01_16-32.zip 2026 2025
#
# Данные БД на момент отката сохраняет и сама доставка (pg_dump в backups/ перед подменой).
set -euo pipefail

PKG="${1:?путь к пакету прежнего года}"
NEW_YEAR="${2:?новый год, чей каталог убрать (например 2026)}"
OLD_YEAR="${3:?прежний год, чей отдельный стор удалить (например 2025)}"
cd "${REPIKURR_DIR:-$HOME/repikurr}"
[ -f "$PKG" ] || { echo "нет файла пакета: $PKG" >&2; exit 1; }

set -a; . ./deliver.env; set +a
WS="${GEOSERVER_WORKSPACE:-pikurr}"
STORE="${GEOSERVER_COVERAGESTORE:-image_assessment}"
TS="$(date +%Y%m%d_%H%M%S)"; T0="$(date +%s)"
log() { echo "[$(date +%T)] $*"; }
step_time() { echo "    ($(( $(date +%s) - T_STEP )) с)"; }

log "1/3 повторная доставка прежнего пакета: $(basename "$PKG")"
T_STEP="$(date +%s)"
python3 deliver.py --allow-year-change --allow-shrink "$PKG"
step_time

log "2/3 data/geodata/$NEW_YEAR -> data/geodata/_removed_${TS}/$NEW_YEAR"
T_STEP="$(date +%s)"
if [ -d "data/geodata/$NEW_YEAR" ]; then
    mkdir -p "data/geodata/_removed_${TS}"
    mv "data/geodata/$NEW_YEAR" "data/geodata/_removed_${TS}/$NEW_YEAR"
else
    log "    каталога data/geodata/$NEW_YEAR нет — пропуск"
fi
step_time

log "3/3 удаление стора ${STORE}_${OLD_YEAR} (purge=none: файлы не трогаются)"
T_STEP="$(date +%s)"
AUTH=(-u "${GEOSERVER_USER}:${GEOSERVER_PASSWORD}")
curl -sS -o /dev/null -w "    слой:  HTTP %{http_code}\n" "${AUTH[@]}" -X DELETE \
    "${GEOSERVER_URL}/rest/layers/${WS}:${STORE}_${OLD_YEAR}.json?recurse=true"
curl -sS -o /dev/null -w "    стор:  HTTP %{http_code}\n" "${AUTH[@]}" -X DELETE \
    "${GEOSERVER_URL}/rest/workspaces/${WS}/coveragestores/${STORE}_${OLD_YEAR}?recurse=true&purge=none"
step_time

log "откат выполнен за $(( $(date +%s) - T0 )) с; проверить: healthcheck.py и smoke.mjs"
