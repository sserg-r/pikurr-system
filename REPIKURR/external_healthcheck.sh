#!/bin/bash
# Внешний мониторинг витрины (round33, блок D.1) — запускается НЕ на VPS,
# а с эмулятора (192.168.251.190), чтобы отказ самой VPS не забирал с собой
# и мониторинг за неё.
#
# healthcheck.py --json запускается без FRONTEND_DB_PASSWORD (его нет на
# этой машине и не должно быть — секрет БД VPS не нужно тащить наружу ради
# внешнего мониторинга) — поэтому проверка db_matches_static намеренно
# исключается из итогового вердикта здесь (она использует этот пароль и
# иначе была бы одним "постоянным false positive" в каждом внешнем прогоне,
# round33, блок A3 наблюдал этот же эффект локально). Остальные 4 проверки
# (wms_getmap, wfs_getfeature, main_page, year_district_json) не требуют
# доступа к БД и полностью пригодны для внешнего запуска. `disk_space`
# (round39, блок D4) добавлена в `healthcheck.py` тем же принципом —
# исключена здесь по той же причине, только наоборот: она проверяет
# диск ТОЙ машины, где запущен сам скрипт, значит с эмулятора
# отчиталась бы про диск эмулятора, а не VPS — бессмысленно и вводит
# в заблуждение при внешнем запуске.
#
# round61, блок D (решение Р4-б): уведомления в Telegram о сбоях витрины.
# Подавление дребезга — ВМ прерываемая: раз в сутки принудительная остановка,
# автоподъём ≈ 4 мин, поэтому одиночный RED уведомления не порождает.
#   - счётчик подряд идущих RED/CRASH — в файле состояния ($STATE);
#   - «🚨 Витрина недоступна» — один раз, когда счётчик достиг ALERT_AFTER_FAILS
#     (по умолчанию 3, при таймере раз в 5 минут ≈ 15 мин);
#   - «✅ Витрина восстановлена, простой ≈ N мин» — один раз при первом GREEN и
#     только если перед этим уходило уведомление о сбое.
# Отправка: curl, простой текст, таймаут 10 с. TELEGRAM__TOKEN / TELEGRAM__CHAT_ID
# (те же имена, что в ETL) берутся из окружения — на стенде из файла,
# подключённого в unit через EnvironmentFile= (права 600, вне git; шаблон —
# systemd/pikurr-external-healthcheck.env.example). Нет токена — уведомления
# выключены, поведение прежнее. Ошибка отправки вердикт и код выхода не меняет;
# в журнал пишется «ALERT sent|failed» (токен в журнал не попадает). Если отправка
# сбоя не удалась — повтор при следующем запуске (alerted остаётся 0).

set -u

BASE_URL="${BASE_URL:-https://geobotany.of.by}"
LOG="${LOG:-/home/user/repikurr/external_healthcheck.log}"
HEALTHCHECK_PY="${HEALTHCHECK_PY:-/home/user/repikurr/healthcheck.py}"
STATE="${STATE:-${LOG}.state}"
ALERT_AFTER_FAILS="${ALERT_AFTER_FAILS:-3}"
TELEGRAM_API_URL="${TELEGRAM_API_URL:-https://api.telegram.org}"
TG_TOKEN="${TELEGRAM__TOKEN:-}"
TG_CHAT="${TELEGRAM__CHAT_ID:-}"

NOW=$(date -u +%s)
TS=$(date -u -d "@$NOW" '+%Y-%m-%dT%H:%M:%SZ')

# --- состояние: fails, first_red (epoch), alerted (0|1), failed (текст) ---
FAILS=0; FIRST_RED=0; ALERTED=0; FAILED_TXT=""
if [ -f "$STATE" ]; then
  while IFS='=' read -r k v; do
    case "$k" in
      fails) FAILS="${v//[^0-9]/}";;
      first_red) FIRST_RED="${v//[^0-9]/}";;
      alerted) ALERTED="${v//[^0-9]/}";;
      failed) FAILED_TXT="$v";;
    esac
  done < "$STATE"
fi
FAILS=${FAILS:-0}; FIRST_RED=${FIRST_RED:-0}; ALERTED=${ALERTED:-0}

save_state() {
  printf 'fails=%s\nfirst_red=%s\nalerted=%s\nfailed=%s\n' "$FAILS" "$FIRST_RED" "$ALERTED" "$FAILED_TXT" > "$STATE.tmp" \
    && mv "$STATE.tmp" "$STATE"
}

# send_alert <kind> <текст>; код 0 — доставлено. Токен в журнал не пишется.
send_alert() {
  local kind="$1" text="$2" resp
  if [ -z "$TG_TOKEN" ] || [ -z "$TG_CHAT" ]; then
    return 2   # уведомления выключены (не настроено) — не ошибка и не запись в журнал
  fi
  resp=$(curl -sS -m 10 -w '\n%{http_code}' -X POST \
      --data-urlencode "chat_id=$TG_CHAT" --data-urlencode "text=$text" \
      "$TELEGRAM_API_URL/bot$TG_TOKEN/sendMessage" 2>/dev/null)
  local code="${resp##*$'\n'}"
  if [ "$code" = "200" ]; then
    echo "$TS ALERT sent kind=$kind" >> "$LOG"; return 0
  fi
  echo "$TS ALERT failed kind=$kind http=${code:-000}" >> "$LOG"; return 1
}

# обработка исхода прогона: handle_result RED|CRASH|GREEN "<проваленные проверки>"
handle_result() {
  local status="$1" failed="$2"
  if [ "$status" = "GREEN" ]; then
    if [ "$ALERTED" = "1" ]; then
      local mins=$(( (NOW - FIRST_RED + 30) / 60 ))
      send_alert recovered "✅ Витрина восстановлена, простой ≈ ${mins} мин ($BASE_URL)" || true
    fi
    FAILS=0; FIRST_RED=0; ALERTED=0; FAILED_TXT=""
  else
    FAILS=$((FAILS + 1))
    if [ "$FAILS" -eq 1 ]; then FIRST_RED=$NOW; fi
    FAILED_TXT="$failed"
    if [ "$FAILS" -ge "$ALERT_AFTER_FAILS" ] && [ "$ALERTED" != "1" ]; then
      local since; since=$(date -u -d "@$FIRST_RED" '+%Y-%m-%d %H:%M UTC')
      if send_alert down "🚨 Витрина недоступна: ${FAILED_TXT}, с ${since} ($BASE_URL)"; then ALERTED=1; fi
    fi
  fi
  save_state
}

JSON=$(python3 "$HEALTHCHECK_PY" --base-url "$BASE_URL" --json 2>&1)
RC=$?

if [ $RC -gt 1 ]; then
  # healthcheck.py сам не смог отработать (не сеть) — редкий случай,
  # отличаем от "витрина красная" (RC=1, штатный результат проверки).
  echo "$TS CRASH rc=$RC output=$JSON" >> "$LOG"
  handle_result CRASH "проверка не выполнена (rc=$RC)"
  exit 2
fi

# Вердикт без db_matches_static: python сам разбирает JSON и решает,
# зелено ли всё остальное. Формат healthcheck.py --json:
# {"ok": bool, "checks": [{"check": name, "ok": bool, "detail": str}, ...]}
# (heredoc и here-string на одной команде конфликтуют за stdin — скрипт
# идёт файлом во временный путь, JSON — через stdin отдельно)
PYSCRIPT=$(mktemp)
cat > "$PYSCRIPT" <<'PYEOF'
import json, sys
ts, log_path = sys.argv[1], sys.argv[2]
data = json.load(sys.stdin)
checks = data.get('checks', [])
relevant = [c for c in checks if c.get('check') != 'db_matches_static']
failed = [c['check'] for c in relevant if not c.get('ok')]
status = 'RED' if failed else 'GREEN'
with open(log_path, 'a') as f:
    f.write(f"{ts} {status} failed={failed}\n")
print(status + "\t" + ", ".join(failed))
sys.exit(1 if failed else 0)
PYEOF
OUT=$(echo "$JSON" | python3 "$PYSCRIPT" "$TS" "$LOG")
RESULT=$?
rm -f "$PYSCRIPT"
STATUS="${OUT%%$'\t'*}"; FAILED_LIST="${OUT#*$'\t'}"
case "$STATUS" in
  RED|GREEN) handle_result "$STATUS" "$FAILED_LIST";;
  *) handle_result CRASH "не удалось разобрать ответ проверки";;
esac
exit $RESULT
