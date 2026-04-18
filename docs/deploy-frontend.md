# Развёртывание внешнего контура (REPIKURR)

Внешний контур — это серверная часть, которую видят пользователи.
Включает: PostGIS, GeoServer, React-фронтенд и nginx.

---

## Параметры окружения

Перед началом определитесь со значениями — они используются во всех командах ниже:

| Параметр | Тестовый сервер | Прод-сервер | Описание |
|---|---|---|---|
| `SERVER_IP` | `192.168.251.190` | `158.160.183.235` | IP сервера |
| `SERVER_USER` | `user` | `sserg` | Пользователь SSH |
| `DEPLOY_DIR` | `~/repikurr` | `~/repikurr` | Директория развёртывания |
| `NGINX_CONF` | `nginx.local.conf` | `nginx.conf` | Конфиг nginx (см. ниже) |

---

## Архитектура

```
nginx (80) ──┬── / ──────────── React SPA (pikurr_srv_react)
             └── /geoserver/ ── GeoServer (pikurr_srv_geoserver :8090)
                                    └── PostGIS (pikurr_srv_postgis :5435)

inbox/ ── watchdog.py ── deliver.py ── PostGIS + GeoServer (обновление данных)
```

| Контейнер | Порт | Описание |
|---|---|---|
| `pikurr_srv_postgis` | 5435 | PostgreSQL + PostGIS |
| `pikurr_srv_geoserver` | 8090 | GeoServer |
| `pikurr_srv_react` | — | React SPA (без прямого порта) |
| `pikurr_srv_nginx` | 80 | Точка входа |

---

## nginx: два конфига

| Файл | Когда использовать |
|---|---|
| `nginx.local.conf` | Тест/локальная сеть — `server_name _` (любой хост), доступ по IP |
| `nginx.conf` | Продакшн с доменом — `server_name geobotany.xyz`, redirect www→apex |

`docker-compose.server.yml` по умолчанию монтирует `nginx.local.conf`.
Для продакшна с доменом нужно изменить строку в `docker-compose.server.yml`:

```yaml
# nginx.local.conf → nginx.conf:
- ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
```

---

## Требования

| Зависимость | Версия |
|---|---|
| Docker + Docker Compose v2 | ≥ 24 |
| Python 3 | ≥ 3.10 (для watchdog и deliver.py) |
| sudo | для systemd |
| git, rsync | для получения кода и данных |

Python-зависимости для `deliver.py`:
```bash
pip3 install psycopg2-binary requests
# или
sudo apt install python3-psycopg2 python3-requests
```

---

## Первоначальное развёртывание

### 1. Подготовка репозитория на сервере

```bash
# Клонировать с sparse checkout (нужна только папка REPIKURR)
git clone --no-checkout https://github.com/sserg-r/pikurr-system.git ~/repikurr-repo
cd ~/repikurr-repo
git sparse-checkout init --cone
git sparse-checkout set REPIKURR
git checkout main

# Скопировать содержимое REPIKURR в рабочую директорию
cp -r REPIKURR/. ~/repikurr/
```

### 2. Создать `deliver.env`

```bash
cd ~/repikurr
cp deliver.env.example deliver.env
nano deliver.env
```

Значения для заполнения:

| Переменная | Описание |
|---|---|
| `FRONTEND_DB_USER/PASSWORD/NAME` | Данные PostGIS (pikurr/pikurr/pikurr) |
| `GEOSERVER_USER/PASSWORD` | Данные GeoServer (admin/geoserver) |
| `PIKURR_INBOX` | Полный путь к inbox, например `/home/sserg/repikurr/inbox` |

### 3. Выбрать nginx-конфиг

**Тест (доступ по IP):** `docker-compose.server.yml` уже настроен на `nginx.local.conf` — ничего не менять.

**Продакшн (домен):** отредактировать `docker-compose.server.yml`:
```yaml
# В секции nginx → volumes:
- ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
```

### 4. Запустить деплой

```bash
cd ~/repikurr
bash deploy.sh
```

`deploy.sh` выполняет:
1. Останавливает старый стек
2. Создаёт директории `data/geodata/` и `inbox/`
3. Выставляет права на тома GeoServer
4. Поднимает контейнеры (`docker compose -f docker-compose.server.yml up -d --build`)
5. Дожидается готовности GeoServer (до 120 сек)
6. Устанавливает и запускает systemd-сервис `pikurr-watchdog`

> **Полный сброс** (удалить данные PostGIS и растры):
> ```bash
> bash deploy.sh --clean
> ```

### 5. Проверить

```bash
docker compose -f docker-compose.server.yml ps
sudo systemctl status pikurr-watchdog
```

Открыть в браузере: `http://<SERVER_IP>` — должна открыться карта.

---

## Обновление кода фронтенда

```bash
# На сервере:
cd ~/repikurr-repo
git pull
cp -r REPIKURR/. ~/repikurr/
cd ~/repikurr
bash deploy.sh
```

---

## Доставка данных (пакет обновлений)

Пакеты создаются ETL-контуром и доставляются через rsync.

### Автоматически (рекомендуется)

С машины администратора (конфиг в `.env`):
```bash
./package_and_push.sh
# или через дашборд: кнопка «ОТПРАВИТЬ ПАКЕТ НА СЕРВЕР»
```

### Вручную

```bash
rsync -avz outputs/dist/pikurr_update_*.zip <SERVER_USER>@<SERVER_IP>:~/repikurr/inbox/
```

### Что происходит после получения пакета

`watchdog.py` опрашивает `inbox/` каждые 10 секунд. При обнаружении нового `.zip` запускает `deliver.py`, который:

1. Распаковывает архив во временную директорию
2. Копирует TIF-файлы в `data/geodata/{year}/`
3. Загружает вектора (GeoPackage) в PostGIS через `ogr2ogr`
4. Пересоздаёт SQL-вьюхи из `create_assessment_schema.sql`
5. Перезагружает хранилища растров в GeoServer через REST API
6. Переименовывает ZIP в `delivered_<...>.zip`

Логи доставки:
```bash
journalctl -fu pikurr-watchdog
# или
tail -f ~/repikurr/watchdog.log
```

---

## GeoServer: слои и стили

Конфигурация хранится в `geoserver_data/` и монтируется в контейнер.
**Не менять настройки через веб-интерфейс** — все настройки в файлах репозитория.

| Слой | Источник | Назначение |
|---|---|---|
| `pikurr:fields` | VirtualTable → `assessment_ready` | Все годы с CQL-фильтрацией |
| `pikurr:fields_latest` | VirtualTable → `assessment_ready_latest` | Только свежайшая оценка |
| `pikurr:levelsagg` | VirtualTable → `agrifields` | Список землепользователей |
| `pikurr:image_assessment` | ImageMosaic → `data/geodata/2025/` | Растр последнего года |
| `pikurr:image_assessment_2024` | ImageMosaic → `data/geodata/2024/` | Растр 2024 |

При добавлении нового года растров:
1. Скопировать конфиг `geoserver_data/workspaces/pikurr/image_assessment_2024/` → `image_assessment_{year}/`
2. Исправить пути внутри `coveragestore.xml` и `coverage.xml`
3. Перезапустить GeoServer: `docker restart pikurr_srv_geoserver`

---

## PostGIS: схема

| Таблица | Описание |
|---|---|
| `agrifields` | Полигоны агрополей с атрибутами |
| `razgrafka` | Сетка трапеций |
| `assessment` | Статистика по полям (stats JSON, год) |

Вьюхи пересоздаются автоматически при каждой доставке пакета.

```bash
# Подключение:
psql -h localhost -p 5435 -U pikurr -d pikurr
```

---

## Диагностика

```bash
# Статус контейнеров
docker compose -f ~/repikurr/docker-compose.server.yml ps

# Логи сервисов
docker logs pikurr_srv_geoserver -f
docker logs pikurr_srv_nginx -f

# Watchdog
sudo systemctl status pikurr-watchdog
journalctl -fu pikurr-watchdog
sudo systemctl restart pikurr-watchdog

# Проверить GeoServer REST
curl -s -u admin:geoserver http://localhost:8090/geoserver/rest/workspaces.json | python3 -m json.tool

# PostGIS
psql -h localhost -p 5435 -U pikurr -d pikurr -c "SELECT COUNT(*) FROM assessment;"
```

---

## Типичные проблемы

### GeoServer не обновляет растры

`deliver.py` сбрасывает кэш автоматически. Если не помогло — вручную:
```bash
curl -X DELETE -u admin:geoserver \
  http://localhost:8090/geoserver/rest/workspaces/pikurr/coveragestores/image_assessment/coverages/image_assessment/reset
```

### Watchdog не подхватывает пакет

```bash
sudo systemctl status pikurr-watchdog
ls -la ~/repikurr/inbox/

# Запустить deliver.py вручную:
cd ~/repikurr
source deliver.env
python3 deliver.py ~/repikurr/inbox/pikurr_update_*.zip
```

### PostGIS недоступен

```bash
docker logs pikurr_srv_postgis
docker compose -f ~/repikurr/docker-compose.server.yml restart postgis
```
