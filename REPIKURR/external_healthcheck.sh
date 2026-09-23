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
# доступа к БД и полностью пригодны для внешнего запуска.

set -u

BASE_URL="${BASE_URL:-https://geobotany.of.by}"
LOG="${LOG:-/home/user/repikurr/external_healthcheck.log}"
HEALTHCHECK_PY="${HEALTHCHECK_PY:-/home/user/repikurr/healthcheck.py}"

TS=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
JSON=$(python3 "$HEALTHCHECK_PY" --base-url "$BASE_URL" --json 2>&1)
RC=$?

if [ $RC -gt 1 ]; then
  # healthcheck.py сам не смог отработать (не сеть) — редкий случай,
  # отличаем от "витрина красная" (RC=1, штатный результат проверки).
  echo "$TS CRASH rc=$RC output=$JSON" >> "$LOG"
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
sys.exit(1 if failed else 0)
PYEOF
echo "$JSON" | python3 "$PYSCRIPT" "$TS" "$LOG"
RESULT=$?
rm -f "$PYSCRIPT"
exit $RESULT
