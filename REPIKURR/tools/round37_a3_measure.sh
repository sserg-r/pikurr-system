#!/usr/bin/env bash
# round37, блок A3: замер цены подсветки на VPS.
# Машина: geobotany.of.by (ПРОД). Порядок запросов перемешан (см.
# CLAUDE.md, "Правила замеров") — все (условие, bbox, повтор) сначала
# перечисляются, затем встряхиваются одним shuf, а не идут блоками.
set -euo pipefail

BASE="https://geobotany.of.by"
TILES_JSON="/home/sgr/PIKURR_REFACTOR/docs/round32_assets/tiles_with_data.json"

mapfile -t BBOXES < <(python3 -c "
import json
d = json.load(open('$TILES_JSON'))
for t in d[:3]:
    b = t['bbox_3857']
    print(','.join(str(x) for x in b))
")

urlencode() { python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$1"; }

CQL_OBLAST=$(urlencode "nr_user LIKE '22%'")
CQL_DISTRICT=$(urlencode "nr_user LIKE '2208%'")
CQL_LANDUSER=$(urlencode "nr_user LIKE '22080000010%'")

build_url() {
  local cond="$1" bbox="$2"
  case "$cond" in
    gwc_hit)
      echo "${BASE}/geoserver/gwc/service/wms?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=pikurr:fields_latest&STYLES=&SRS=EPSG:900913&BBOX=${bbox}&WIDTH=256&HEIGHT=256&FORMAT=image/png&TILED=true" ;;
    direct_nofilter)
      echo "${BASE}/geoserver/pikurr/wms?service=WMS&version=1.1.1&request=GetMap&layers=pikurr:fields_latest&styles=&format=image/png&transparent=true&width=256&height=256&srs=EPSG:3857&bbox=${bbox}" ;;
    oblast)
      echo "${BASE}/geoserver/pikurr/wms?service=WMS&version=1.1.1&request=GetMap&layers=pikurr:fields_latest&styles=&format=image/png&transparent=true&width=256&height=256&srs=EPSG:3857&bbox=${bbox}&CQL_FILTER=${CQL_OBLAST}" ;;
    district)
      echo "${BASE}/geoserver/pikurr/wms?service=WMS&version=1.1.1&request=GetMap&layers=pikurr:fields_latest&styles=&format=image/png&transparent=true&width=256&height=256&srs=EPSG:3857&bbox=${bbox}&CQL_FILTER=${CQL_DISTRICT}" ;;
    landuser)
      echo "${BASE}/geoserver/pikurr/wms?service=WMS&version=1.1.1&request=GetMap&layers=pikurr:fields_latest&styles=&format=image/png&transparent=true&width=256&height=256&srs=EPSG:3857&bbox=${bbox}&CQL_FILTER=${CQL_LANDUSER}" ;;
  esac
}

echo "machine=geobotany.of.by(VPS) date=$(date -u +%FT%TZ)"

# сгенерировать все тройки (условие, bbox_index, повтор), перемешать
plan=$(mktemp)
for cond in gwc_hit direct_nofilter oblast district landuser; do
  for bi in 0 1 2; do
    for rep in 1 2 3; do
      echo "$cond $bi $rep"
    done
  done
done | shuf > "$plan"

while read -r cond bi rep; do
  bbox="${BBOXES[$bi]}"
  url=$(build_url "$cond" "$bbox")
  result=$(curl -s -o /dev/null -w "%{http_code} %{time_total} %{size_download}" "$url")
  echo "cond=$cond bbox_idx=$bi rep=$rep $result"
done < "$plan"

rm -f "$plan"
