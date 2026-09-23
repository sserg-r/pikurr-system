#!/bin/bash
# Опрос окна недоступности во время реальной доставки (round31, блок D;
# формализовано в round32, блок E.3).
#
# round31 использовал `curl -m 2` без обоснования порога и без разбора
# ПРИЧИНЫ отказа — код 000 от curl означает и "сервер не ответил вовсе",
# и "curl сам оборвал по таймауту живой, но медленный запрос", а это
# РАЗНЫЕ вещи: первое — реальная недоступность, второе — искусственный
# отказ, вносимый самим инструментом измерения.
#
# round32, блок A показал: холодное TCP+TLS соединение снаружи к тайлу
# с данными — до ~914мс-1.15с (блок A.4); под нагрузкой k6 (VU=3, один
# из 9 прогонов) максимум одного запроса достигал 1.86с (блок D.2) —
# ВСЁ ЕЩЁ успешный ответ, не отказ. Порог `-m 2` в этом свете был на
# грани — мог искусственно классифицировать легитимно медленный, но
# живой ответ как "нет ответа". Порог поднят до 5с — с запасом (~2.7×)
# над худшим наблюдённым УСПЕШНЫМ ответом этого раунда, а не подобран
# произвольно.
#
# Дополнительно: время каждого запроса записывается в лог, и ответы,
# уложившиеся в лимит, но занявшие дольше SLOW_THRESHOLD_S, помечаются
# отдельно ("SLOW"), а не смешиваются с "OK" — округ25/round31 не
# различал "ответил, но медленно" от "ответил быстро", что маскировало
# деградацию, не доходящую до полного отказа.

set -u

BASE_URL="${BASE_URL:-https://geobotany.of.by}"
OUT="${OUT:-/tmp/delivery_window_poll.log}"
DURATION_S="${DURATION_S:-420}"
POLL_INTERVAL_S="${POLL_INTERVAL_S:-0.2}"
CURL_TIMEOUT_S="${CURL_TIMEOUT_S:-5}"
SLOW_THRESHOLD_S="${SLOW_THRESHOLD_S:-1.5}"

WMS_URL="${BASE_URL}/geoserver/pikurr/wms?service=WMS&request=GetMap&layers=pikurr:fields_latest&styles=&format=image/png&width=64&height=64&srs=EPSG:3857&bbox=3209132,7357522,3287403,7435794"
WFS_URL="${BASE_URL}/geoserver/pikurr/wfs?service=WFS&version=2.0.0&request=GetFeature&typeNames=pikurr:fields_latest&count=1&outputFormat=application/json"

> "$OUT"
END=$((SECONDS + DURATION_S))

check_one() {
  local url="$1" body_tmp="$2" kind="$3"
  # curl -w выводит и код, и реальное время запроса (%{time_total}) —
  # именно это время используется для деления OK/SLOW/TIMEOUT, а не
  # факт истечения -m (тот отличает только "уложился/не уложился").
  local out code elapsed
  out=$(curl -s -m "$CURL_TIMEOUT_S" -o "$body_tmp" -w '%{http_code} %{time_total}' "$url" 2>/dev/null)
  local rc=$?
  code=$(echo "$out" | awk '{print $1}')
  elapsed=$(echo "$out" | awk '{print $2}')

  if [ "$rc" -ne 0 ] || [ -z "$code" ] || [ "$code" = "000" ]; then
    echo "NORESPONSE/-"
    return
  fi

  local status="OK"
  if [ "$kind" = "wms" ]; then
    if [ "$code" != "200" ]; then
      status="BADCODE"
    else
      local head
      head=$(head -c 8 "$body_tmp" | xxd -p | head -c 16)
      [ "$head" != "89504e470d0a1a0a" ] && status="BADBODY"
    fi
  else
    if [ "$code" != "200" ]; then
      status="BADCODE"
    else
      grep -q "ExceptionReport\|ServiceException" "$body_tmp" 2>/dev/null && status="EXCEPTION"
      grep -q "FeatureCollection\|features" "$body_tmp" 2>/dev/null || status="${status}_EMPTY"
    fi
  fi

  # Разделяем "ответил быстро" от "ответил, но медленно" — оба живые,
  # но деградация видна отдельно от полного отказа (NORESPONSE выше).
  if [ "$status" = "OK" ] && awk -v e="$elapsed" -v t="$SLOW_THRESHOLD_S" 'BEGIN{exit !(e>t)}'; then
    status="SLOW"
  fi
  echo "${code}/${status}/${elapsed}s"
}

while [ $SECONDS -lt $END ]; do
  T=$(date +%s.%N)
  WMS_RESULT=$(check_one "$WMS_URL" /tmp/_poll_wms_body.tmp wms)
  WFS_RESULT=$(check_one "$WFS_URL" /tmp/_poll_wfs_body.tmp wfs)
  echo "$T WMS=$WMS_RESULT WFS=$WFS_RESULT" >> "$OUT"
  sleep "$POLL_INTERVAL_S"
done
