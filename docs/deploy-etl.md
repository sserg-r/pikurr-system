# Развёртывание внутреннего контура (PIKURR ETL)

ETL-контур запускается на рабочей машине администратора. Обрабатывает входные геоданные,
обучает и применяет ML-модели, накапливает результаты в PostGIS и собирает пакет обновлений
для отправки на сервер с фронтендом.

---

## Архитектура

```
inputs/
  sources/
    razgrafka_SK63.zip   ← сетка трапеций (не меняется)
    agrifields.zip       ← полигоны агрополей (обновляется)
  models/                ← модели TF Serving

outputs/
  tiles/                 ← скачанные тайлы (кэш)
  predictions/
    predictions_veget/   ← маски растительности (ML)
    predictions_usab/    ← маски используемости (GEE)
    predictions_final/   ← финальная классификация
    geoserver_public/    ← публичные TIF по годам
  dist/                  ← готовые ZIP-пакеты для отправки
  pg_data/               ← данные PostgreSQL
```

Контейнеры: `db` (PostGIS), `tf-serving` (GPU-инференс), `etl` (Python-воркер).

---

## Требования

| Зависимость | Версия |
|---|---|
| Docker + Docker Compose v2 | ≥ 24 |
| NVIDIA GPU + nvidia-container-toolkit | любая |
| Python | не нужен на хосте |
| rsync, ssh | для отправки пакетов |

---

## Первоначальная настройка

### 1. Клонировать репозиторий

```bash
git clone https://github.com/sserg-r/pikurr-system.git
cd pikurr-system
```

### 2. Создать `.env` из шаблона

```bash
cp .env_example .env
```

Обязательно заполнить:

| Переменная | Описание |
|---|---|
| `POSTGRES_USER / PASSWORD / DB` | Данные PostgreSQL (используются Docker при создании) |
| `GEE__SERVICE_ACCOUNT` | JSON-ключ сервисного аккаунта Google Earth Engine |
| `GEE__PROJECT` | Название GEE-проекта |
| `TILESERVICES__DZZ` | URL тайл-сервиса ДЗЗ |
| `DELIVERY_HOST` | IP сервера с фронтендом (если нужна авто-отправка) |
| `DELIVERY_USER` | Пользователь SSH на сервере |
| `DELIVERY_INBOX` | Путь к inbox на сервере |
| `DELIVERY_SSH_KEY` | Путь к SSH-ключу на хосте (по умолчанию `~/.ssh/id_rsa`) |
| `TELEGRAM__TOKEN / CHAT_ID` | Уведомления в Telegram (опционально) |

### 3. Подготовить входные данные

```bash
mkdir -p inputs/sources inputs/models outputs
cp razgrafka_SK63.zip inputs/sources/
cp agrifields.zip     inputs/sources/
# Скопировать файлы модели в inputs/models/
```

Структура `inputs/models/` для TF Serving:
```
inputs/models/
  two/
    1/
      saved_model.pb
      variables/
  models.config
  batching_parameters.txt
```

### 4. Собрать Docker-образы

```bash
docker compose build etl
```

> После любых изменений кода в `PIKURR/` — повторить `docker compose build etl`.

---

## Запуск пайплайна

### Вариант A: Дашборд (рекомендуется)

```bash
docker compose up -d db tf-serving
docker compose up etl          # запускает Streamlit на порту 8505
```

Открыть в браузере: **http://localhost:8505**

Дашборд позволяет:
- Запустить полный цикл кнопкой **«ЗАПУСТИТЬ ПОЛНЫЙ ЦИКЛ (ETL)»**
- Отправить готовый пакет кнопкой **«ОТПРАВИТЬ ПАКЕТ НА СЕРВЕР»** (если задан `DELIVERY_HOST`)
- Смотреть статус каждого шага и системный журнал в реальном времени

### Вариант Б: Запуск задач по отдельности

```bash
# Запуск любого шага:
docker compose run --rm etl python -m src.tasks.<task>
```

| Команда | Описание |
|---|---|
| `src.tasks.initialize` | Загрузка разграфки и агрополей в PostGIS, создание схемы БД |
| `src.tasks.download` | Скачивание спутниковых тайлов |
| `src.tasks.segmentate` | ML-сегментация растительности |
| `src.tasks.usability` | Анализ используемости через GEE |
| `src.tasks.classify` | Финальная классификация (вег. маска × используемость) |
| `src.tasks.save_db` | Расчёт и сохранение зональной статистики в assessment |
| `src.tasks.export` | Подготовка публичных TIF (маскирование по агрополям) |
| `src.tasks.package` | Сборка ZIP-пакета в `outputs/dist/` |
| `src.tasks.push` | Отправка последнего пакета на сервер через rsync |

### Вариант В: Сборка и отправка одной командой (без дашборда)

```bash
./package_and_push.sh
```

Скрипт собирает пакет и rsync'ит его на сервер. SSH-ключ и адрес сервера берёт из `.env`.

---

## Полный цикл обновления данных

1. Обновить `inputs/sources/agrifields.zip` новой версией полигонов
2. Запустить полный цикл через дашборд **или** вручную пошагово
3. По завершении — пакет появится в `outputs/dist/pikurr_update_<years>_<date>.zip`
4. Отправить на сервер (кнопка в дашборде, `./package_and_push.sh`, или вручную):
   ```bash
   rsync -avz outputs/dist/pikurr_update_*.zip <SERVER_USER>@<SERVER_IP>:~/repikurr/inbox/
   ```
5. Watchdog на сервере подхватит пакет автоматически

---

## Конфигурация SSH для rsync

Проверить наличие ключа:
```bash
ls ~/.ssh/id_rsa
```

Если ключа нет — сгенерировать и скопировать на сервер:
```bash
ssh-keygen -t rsa -b 4096
ssh-copy-id <SERVER_USER>@<SERVER_IP>
```

Проверить связь:
```bash
ssh <SERVER_USER>@<SERVER_IP> "echo OK"
```

---

## Диагностика

```bash
# Статус контейнеров
docker compose ps

# Логи ETL
docker compose logs -f etl

# Подключение к БД
psql -h localhost -p 5444 -U postgres -d pikurr_db

# Проверить что пакет собрался
ls -lh outputs/dist/
```

---

## Обновление кода

```bash
git pull
docker compose build etl   # пересобрать образ после изменений кода
```
