#!/usr/bin/env bash
# round37, блок A3: время отрисовки экрана из 12 тайлов с выбором (район,
# 2208) и без, 3 повтора, порядок перемешан. Параллелизм 6 — типичный
# лимит браузера на соединения к одному хосту.
set -euo pipefail
BASE="https://geobotany.of.by"
TILES_JSON="/home/sgr/PIKURR_REFACTOR/docs/round32_assets/tiles_with_data.json"
CQL=$(python3 -c "import urllib.parse; print(urllib.parse.quote(\"nr_user LIKE '2208%'\"))")

mapfile -t BBOXES < <(python3 -c "
import json
d = json.load(open('$TILES_JSON'))
for t in d[:12]:
    print(','.join(str(x) for x in t['bbox_3857']))
")

fetch_screen_without() {
  printf '%s\n' "${BBOXES[@]}" | xargs -P 6 -I{} curl -s -o /dev/null \
    "${BASE}/geoserver/gwc/service/wms?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=pikurr:fields_latest&STYLES=&SRS=EPSG:900913&BBOX={}&WIDTH=256&HEIGHT=256&FORMAT=image/png&TILED=true"
}

fetch_screen_with() {
  # 12 фоновых (GWC, без фильтра — приглушённый нижний слой) + 12 подсветки
  # (прямой WMS, CQL_FILTER района)
  {
    printf '%s\n' "${BBOXES[@]}" | xargs -P 6 -I{} curl -s -o /dev/null \
      "${BASE}/geoserver/gwc/service/wms?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=pikurr:fields_latest&STYLES=&SRS=EPSG:900913&BBOX={}&WIDTH=256&HEIGHT=256&FORMAT=image/png&TILED=true"
    printf '%s\n' "${BBOXES[@]}" | xargs -P 6 -I{} curl -s -o /dev/null \
      "${BASE}/geoserver/pikurr/wms?service=WMS&version=1.1.1&request=GetMap&layers=pikurr:fields_latest&styles=&format=image/png&transparent=true&width=256&height=256&srs=EPSG:3857&bbox={}&CQL_FILTER=${CQL}"
  }
}

echo "machine=geobotany.of.by(VPS) date=$(date -u +%FT%TZ) tiles=12 concurrency=6"
plan=$(mktemp)
for cond in without with; do for rep in 1 2 3; do echo "$cond $rep"; done; done | shuf > "$plan"
while read -r cond rep; do
  t0=$(date +%s.%N)
  if [ "$cond" = "without" ]; then fetch_screen_without; else fetch_screen_with; fi
  t1=$(date +%s.%N)
  echo "cond=$cond rep=$rep total_s=$(python3 -c "print(f'{$t1-$t0:.3f}')")"
done < "$plan"
rm -f "$plan"
