#!/bin/bash
# watchdog.sh — следит за папкой inbox, запускает deliver.py при появлении ZIP.
#
# Запуск вручную:   bash watchdog.sh
# Запуск в фоне:    nohup bash watchdog.sh >> ~/repikurr/watchdog.log 2>&1 &
# Остановить:       kill $(cat ~/repikurr/watchdog.pid)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INBOX="${SCRIPT_DIR}/inbox"
LOG="${SCRIPT_DIR}/watchdog.log"
PID_FILE="${SCRIPT_DIR}/watchdog.pid"
DELIVER="${SCRIPT_DIR}/deliver.py"
ENV_FILE="${SCRIPT_DIR}/deliver.env"

mkdir -p "$INBOX"
echo $$ > "$PID_FILE"
echo "[$(date '+%F %T')] watchdog started, watching $INBOX" | tee -a "$LOG"

# Требует: inotifywait (пакет inotify-tools)
if ! command -v inotifywait &>/dev/null; then
    echo "[$(date '+%F %T')] ERROR: inotifywait not found. Install: sudo apt install inotify-tools" | tee -a "$LOG"
    exit 1
fi

inotifywait -m -e close_write,moved_to "$INBOX" --format '%f' 2>>"$LOG" | while read -r FNAME; do
    # Реагируем только на ZIP-пакеты PIKURR
    [[ "$FNAME" == pikurr_update_*.zip ]] || continue

    ZIP="${INBOX}/${FNAME}"
    echo "[$(date '+%F %T')] New package: $FNAME" | tee -a "$LOG"

    # Небольшая пауза — дать rsync дописать файл полностью
    sleep 2

    # Загружаем конфиг и запускаем deliver.py
    set -a; source "$ENV_FILE"; set +a
    if python3 "$DELIVER" "$ZIP" >> "$LOG" 2>&1; then
        echo "[$(date '+%F %T')] Delivery SUCCESS: $FNAME" | tee -a "$LOG"
    else
        echo "[$(date '+%F %T')] Delivery FAILED: $FNAME — see $LOG" | tee -a "$LOG"
    fi
done
