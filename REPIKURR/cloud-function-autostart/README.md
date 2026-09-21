# Автоперезапуск ВМ REPIKURR

Прерываемую ВМ Yandex Cloud нельзя перезапустить изнутри — принудительно
останавливается не позже чем через 24 часа с момента ручного `start`. Эта
функция дёргает Compute API снаружи по таймеру и запускает ВМ, если она
`STOPPED`.

**Выполняет пользователь** — у Claude Code нет credentials/API-доступа к
Yandex Cloud. Инструкция ниже — точные команды по шагам, с проверкой после
каждого; плейсхолдеры в `<УГЛОВЫХ СКОБКАХ>` подставить своими значениями.

Понадобится `yc` CLI, авторизованный (`yc init`), и `jq` для разбора
JSON-вывода (`sudo apt install jq`, если нет).

---

## Шаг 0. Узнать ID инстанса и каталога (folder)

```
yc resource-manager folder list
```
Запомнить `id` нужного каталога → `<FOLDER_ID>`.

```
yc compute instance list --folder-id <FOLDER_ID>
```
Запомнить `id` ВМ REPIKURR (имя вида `compute-vm-...`) → `<INSTANCE_ID>`.

**Проверить**: `yc compute instance get <INSTANCE_ID> --format json | jq -r .status`
должен вернуть `RUNNING` или `STOPPED` (не ошибку) — подтверждает, что ID верный.

---

## Шаг 1. Сервисный аккаунт

```
yc iam service-account create \
  --name pikurr-autostart \
  --folder-id <FOLDER_ID>
```

**Проверить**: команда выводит `id: ajX...` — это `<SA_ID>`, запомнить.
```
yc iam service-account get pikurr-autostart --folder-id <FOLDER_ID>
```
должна найти только что созданный аккаунт.

---

## Шаг 2. Права — привязка на уровне ОДНОГО инстанса, не всего каталога

**Решение (не альтернатива, а то, что разворачивать)**: роль `compute.editor`
даёт больше, чем нужно (start+stop+delete+update), но привязывается **не**
на весь каталог, а конкретно на этот один инстанс через
`add-access-binding` на самом ресурсе `instance` — сервисный аккаунт не
получает никаких прав на другие ВМ или ресурсы каталога. Более узкая
предопределённая роль (только `compute.instances.start`) в Yandex Cloud не
предусмотрена — она потребовала бы кастомной роли на уровне организации,
что для одной автоматизации избыточно.

```
yc compute instance add-access-binding <INSTANCE_ID> \
  --role compute.editor \
  --subject serviceAccount:<SA_ID>
```

**Проверить**:
```
yc compute instance list-access-bindings <INSTANCE_ID>
```
должна показать строку с `serviceAccount:<SA_ID>` и ролью `compute.editor`.
Отдельно убедиться, что **на каталоге** такой привязки НЕТ:
```
yc resource-manager folder list-access-bindings <FOLDER_ID> | grep <SA_ID>
```
— пустой вывод (права только на инстанс, не на каталог).

---

## Шаг 3. Код функции

`main.py` в этом каталоге — без зависимостей (только `urllib` из стандартной
библиотеки), `requirements.txt` не нужен.

```
cd REPIKURR/cloud-function-autostart
zip function.zip main.py

yc serverless function create \
  --name pikurr-autostart \
  --folder-id <FOLDER_ID>

yc serverless function version create \
  --function-name pikurr-autostart \
  --folder-id <FOLDER_ID> \
  --runtime python312 \
  --entrypoint main.handler \
  --memory 128m \
  --execution-timeout 15s \
  --service-account-id <SA_ID> \
  --environment INSTANCE_ID=<INSTANCE_ID> \
  --source-path function.zip
```

**Проверить**:
```
yc serverless function version list --function-name pikurr-autostart --folder-id <FOLDER_ID>
```
должна показать одну версию со статусом `ACTIVE`. Вызвать вручную, не
дожидаясь триггера:
```
yc serverless function invoke pikurr-autostart --folder-id <FOLDER_ID>
```
Ожидаемый ответ: `{"statusCode": 200, "body": "already running"}` (если ВМ
сейчас `RUNNING`) — это подтверждает, что функция реально видит статус
инстанса через IAM-токен сервисного аккаунта, а не падает на правах.

---

## Шаг 4. Триггер по таймеру

**Интервал 2 минуты** — обосновано измерением из round22 (задача 4): после
жёсткой перезагрузки ВМ весь стек (Docker, compose, watchdog) поднялся сам
за ~24с, публичный HTTPS/карта были доступны через ~32с от старта ВМ. 2
минуты — почти четырёхкратный запас, не чаще, чем машина успевает встать.

```
yc serverless trigger create timer \
  --name pikurr-autostart-timer \
  --folder-id <FOLDER_ID> \
  --cron-expression "*/2 * * * ? *" \
  --invoke-function-name pikurr-autostart \
  --invoke-function-service-account-id <SA_ID>
```

**Проверить**:
```
yc serverless trigger get pikurr-autostart-timer --folder-id <FOLDER_ID>
```
должна показать `status: ACTIVE` и тот же `cron_expression`.

**Важно (предупреждение из ТЗ round23)**: правильно настроенный триггер с
недостаточными правами сервисного аккаунта выглядит в консоли нормально и
при этом ничего не делает — сам факт `ACTIVE` у триггера и функции НЕ
подтверждает, что автозапуск работает. Обязательна проверка шагом 5.

---

## Шаг 5. Обработка «уже запускается» и логи — уже в коде, проверить фактом

`main.py`: при статусе `STARTING`/`PROVISIONING` — `start` не вызывается
повторно; при `RUNNING` — ничего не делает; вызывает `start` только при
`STOPPED`. Логи — `print()` уходит в Cloud Logging автоматически, группа
лога функции создаётся сама при первом вызове.

**Проверить**:
```
yc logging read \
  --group-id $(yc serverless function get pikurr-autostart --folder-id <FOLDER_ID> --format json | jq -r .logGroupId) \
  --since 1h
```
или в консоли: Cloud Functions → `pikurr-autostart` → вкладка «Логи».

---

## Шаг 6. Проверка фактом — обязательна, не заменяется чтением конфигурации

1. Остановить ВМ из консоли Yandex Cloud (реальная остановка, не
   гипотетическая) — засечь точное время.
2. Ждать **не дольше 3 минут** (интервал триггера 2 мин + запас) —
   `curl -o /dev/null -w '%{http_code}\n' https://geobotany.of.by/` в цикле
   каждые 10-15с.
3. Как только `200` — засечь время, посчитать разницу с моментом остановки.
4. Проверить логи функции (шаг 5) за это окно — должен быть виден вызов
   `start` с `[autostart] STOPPED — вызываю start`.
5. Убедиться, что **повторных** вызовов `start` в этом же окне нет — только
   один, остальные (если триггер сработал ещё раз пока ВМ уже `STARTING`)
   должны показать `[autostart] уже в переходном статусе ... — не дёргаю
   start повторно`.

**Результат проверки — записать в `docs/round23-...md`** (не оставлять
только в этом README): дата/время теста, фактическое время до `200`,
подтверждение отсутствия повторных `start`.
