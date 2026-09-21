#!/bin/bash
# Диспетчер для ограниченного SSH-ключа пользователя pikurr_delivery
# (round21 B3 — предложение; round22, задача 7 — внедрено).
#
# authorized_keys содержит command="<путь_к_этому_скрипту>" для ключа, которым
# PushTask пользуется с ETL-стороны (192.168.251.190). Пропускает ровно две
# операции, которые PushTask реально выполняет по ssh:
#   1. rsync-запись пакета в inbox/ (через rrsync -wo — запись, без чтения
#      произвольных путей, ограничено каталогом inbox/);
#   2. чтение файла статуса доставки.
# Всё остальное — отказ.
#
# Для чтения статуса маска в case ("*") — обычный bash-паттерн, а не
# ограниченный именем файла: "*" в case сопоставляется как строка и МОЖЕТ
# включать "/", поэтому маски вида "cat $DIR/pikurr_update_*.zip.json"
# недостаточно — "pikurr_update_/../../../etc/passwd.zip.json" формально ей
# соответствует. Защита — не сама маска, а последующая проверка через
# realpath: реальный канонический каталог запрошенного файла должен быть
# ровно STATUS_DIR, буквально, после разрешения всех "..".
set -eu

INBOX="/home/pikurr_delivery/inbox"
STATUS_DIR="/home/sgr/repikurr/status"

deny() {
    echo "Операция не разрешена: $SSH_ORIGINAL_COMMAND" >&2
    exit 1
}

case "$SSH_ORIGINAL_COMMAND" in
  "rsync --server"*)
    exec /usr/bin/rrsync -wo "$INBOX"
    ;;
  cat\ *)
    requested="${SSH_ORIGINAL_COMMAND#cat }"
    case "$requested" in
      *".."* | *$'\n'*)
        deny
        ;;
      "$STATUS_DIR"/pikurr_update_*.zip.json)
        real=$(realpath -e -- "$requested" 2>/dev/null) || deny
        if [[ "$(dirname -- "$real")" == "$STATUS_DIR" ]]; then
          exec cat -- "$real"
        fi
        deny
        ;;
      *)
        deny
        ;;
    esac
    ;;
  *)
    deny
    ;;
esac
