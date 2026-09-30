# Состав исходных текстов для будущего носителя (проект)

Раунд 51, блок B7. Аналог старой «Ведомости НЗ» (`legacy-diff.md`, А1г).
**Решение о составе носителя — за пользователем; здесь только проект и
факты.** Размеры — байты, по `git ls-files` на коммите `030ec02` + правки
раунда 51 (файлы фактической базы `docs/facts/` в подсчёт не включены) и
по чтению каталогов на координаторской машине и стенде 2026-09-30. Ни один
файл в раунде 51 не удалялся и не перемещался.

## 1. Что логично включить (все файлы — под контролем git)

| Группа | Пути | Файлов | Байт | Комментарий |
|---|---|---|---|---|
| ETL — код | `PIKURR/src/**` (задачи, сервисы, утилиты, SQL-скрипты, `_archive/inference_ovms_tfserving.py`), `PIKURR/pipeline.py`, `PIKURR/dashboard.py`, `PIKURR/scripts/provenance_snapshot.py` | 30 | 226 857 | основной код обработки; SQL-схемы — `PIKURR/src/sqlscripts/*.sql` |
| ETL — сборка и запуск | `PIKURR/Dockerfile`, `PIKURR/requirements.txt`, `PIKURR/.dockerignore`, `PIKURR/.gitignore`, `docker-compose.yml`, `.env_example`, `package_and_push.sh`, `.gitignore` | 8 | 21 840 | `.env_example` — шаблон с заглушками (см. §2: значения-заглушки вроде `POSTGRES_PASSWORD=postgres`) |
| Витрина — backend/развёртывание | `REPIKURR/deliver.py` (110 823), `watchdog.py`, `watchdog.sh`, `healthcheck.py`, `deploy.sh`, `deploy_backend_vps.sh`, `deploy_frontend_vps.sh`, `backup_config_offsite.sh`, `check_delivery_window.sh`, `external_healthcheck.sh`, `delivery-dispatch.sh`, `docker-compose{,.local,.server,.vps}.yml`, `Caddyfile`, `nginx*.conf`, `pikurr-*.service`, `systemd/*`, `cloud-function-autostart/{main.py,README.md}`, `.env.example`, `deliver.env.example` | 27 | 231 475 | шаблоны `*.example` — без значений |
| Витрина — инструменты | `REPIKURR/tools/**` (в т. ч. `smoke/*.mjs`, `package.json`, `package-lock.json`, `tile_math.py`, `gwc_*`, `k6_*`, `capacity_k6.js`, `build_qgis_plugin.py`, `gen_districts_ref.py`, `pikurr_layers.qlr`) | 23 | 224 409 | `smoke/captured_gwc_urls.json`, `all_tile_requests.json` — сгенерированные файлы |
| Витрина — конфигурация GeoServer | `REPIKURR/geoserver_data/**` из git (рабочая область `pikurr`, стили, `global.xml`, `wps.xml`, часть `security/**` без секретов) | 70 | 81 474 | **содержит `workspaces/pikurr/postgis_pikurr/datastore.xml` с паролем БД в открытом виде — см. §2** |
| Витрина — фронтенд | `REPIKURR/repikurr/**` (`src/`, `public/` без архива плагина, `package.json`, `package-lock.json`, `Dockerfile`, `index.html`, `vite.config.js`, `eslint.config.js`, `.env`) | 29 | 203 443 | `.env` фронтенда — одна переменная `VITE_GEOSERVER_URL` (значение пусто/относительный путь, в git); версии — `package-lock.json` |
| Витрина — публикуемый архив плагина | `REPIKURR/repikurr/public/pikurr_qgis.zip`, `pikurr_qgis.sha256`, `pikurr_qgis_readme.txt` | (в группе выше, кроме zip) | 25 368 (zip) | производный артефакт; собирается из `pikurr_qgis/` (`build_qgis_plugin.py`) — дублирует исходники |
| Плагин QGIS — код | `pikurr_qgis/*.py`, `metadata.txt`, `pikurr_panel_base.ui`, `icon_2.png`, `wps_templates/*`, `PROTOTYPE_NOTICE.md` | 10 | 71 557 | версия 1.2.0 |
| Плагин QGIS — тесты | `pikurr_qgis/tests/*.py` | 4 | 52 590 | требуют боевого сервера (`test-methods.md`) |
| Плагин QGIS — справка | `pikurr_qgis/help/**` (сгенерирована Sphinx) | 20 | 73 584 | производный артефакт |
| Инструкции репозитория | `CLAUDE.md` | 1 | 91 583 | рабочие инструкции агента, содержат IP-адреса, имена ВМ и идентификаторы облачной папки (см. §2) |
| Документация | `docs/**` (кроме `docs/_legacy_local/`) | 58 | 1 672 795 | до раунда 51; отчёты по раундам, `system-state.md`, `architecture.md`, `third-party-components.md`; **включение — решение пользователя** |

Итого по git-отслеживаемым файлам без `docs/` — 1 304 180 Б (1,30 МБ;
= 2 976 975 − 1 672 795); вместе с документацией — 2 976 975 Б
(`git ls-files`, 282 файла до раунда 51). Каталога `prompts/` в git нет.

## 2. Что включать нельзя

Проверка: `git check-ignore -v`, `find` по шаблонам имён, `grep` по
шаблонам секретов (приватные ключи, `AKIA`, `AIza`, `ghp_`, `xox*`, JWT,
`"private_key"`, `plain:`/`crypt*:`, присвоения `password/token/secret` с
литералом) по всем отслеживаемым файлам и по локальным старым каталогам.

**Файлы с секретами, лежащие на диске рядом с кодом (вне git, `.gitignore`
их закрывает — на носитель не копировать):**

| Файл | Размер, Б | Что это |
|---|---|---|
| `.env` (корень) | 5 527 | переменные окружения ETL: БД, GEE-ключ сервисного аккаунта, доставка, Telegram |
| `PIKURR/.env`, `PIKURR/.env.docker`, `PIKURR/.env.example` | 3 288 / 4 534 / 1 091 | локальные копии окружения ETL (`PIKURR/.env.example` не отслеживается git, в отличие от корневого `.env_example`) |
| `PIKURR/geoserver.env` | 359 | `geoserver.env` с паролями GeoServer (в старой ВНЗ был включён) |
| `REPIKURR/deliver.env` | 530 | доступ к БД и GeoServer для `deliver.py`/`healthcheck.py` |
| `repikurr_old_dump/.env` | 100 | старый дамп окружения |
| `PIKURR/pyscr/earthengine/credentials` | 387 | учётные данные Earth Engine старой реализации (в ВНЗ 2024 — в составе носителя) |
| `REPIKURR/geoserver_data/security/geoserver.jceks` | 538 | хранилище зашифрованных паролей GeoServer |
| `REPIKURR/geoserver_data/security/masterpw/default/passwd`, `masterpw.digest` | 32 / 72 | мастер-пароль GeoServer |
| `REPIKURR/geoserver_data/security/usergroup/default/users.xml`, `users.xml.orig`; `role/default/roles.xml.orig` | 299 / 299 / 367 | пользователи и роли GeoServer (хеши) |
| `REPIKURR/geoserver_data/tomcat_pass.txt` | 19 | пароль Tomcat |
| `config_backups_offsite/secrets_*.tar.gz` | (в каталоге 8 775 Б обоих архивов) | архив секретов (права 600) |
| `outputs/pg_data/` | недоступен | том PostgreSQL |

**Выявленное в git-отслеживаемых файлах (проверено `grep`):**

- `REPIKURR/geoserver_data/workspaces/pikurr/postgis_pikurr/datastore.xml`
  (строка 29): пароль пользователя БД записан **открытым текстом** (префикс
  `plain:`); файл введён в git коммитом `21f53d7`. Значение в документы не
  переносится. Проверка хешем строки: на VPS в этом файле **другое**
  значение (тоже с префиксом `plain:`), на стенде — зашифрованное
  (`crypt2:`); на каком из окружений репозиторное значение используется —
  не установлено. Это находка для решения пользователя: по правилам
  репозитория история git не переписывается без явного запроса
  (`CLAUDE.md`, «Не делать»); для носителя файл должен быть исключён или
  очищен.
- `.env_example`, `REPIKURR/.env.example`, `REPIKURR/deliver.env.example`:
  значения-заглушки (`POSTGRES_PASSWORD=postgres`, `your_db_password`,
  `token_here`). Это шаблоны, но `POSTGRES_PASSWORD=postgres` — пароль-«по
  умолчанию».
- Других совпадений в отслеживаемых файлах (приватные ключи, токены,
  JWT) нет.
- Инфраструктурные идентификаторы, присутствующие в скриптах и
  документах и не являющиеся секретами, но требующие решения перед
  передачей носителя: IP-адреса `158.160.237.90` (VPS) и `192.168.251.190`
  (стенд); имя пользователя `sgr@…` как значение по умолчанию
  `VPS_HOST` (`deploy_backend_vps.sh:29`, `deploy_frontend_vps.sh:40`);
  идентификатор облачной папки Yandex Cloud и имена функции/триггера
  (`CLAUDE.md`); домен `geobotany.of.by`, а в `nginx.conf` — прежний
  `geobotany.xyz`.
- Файлы старого комплекта `docs/_legacy_local/*` (в `.gitignore`) содержат
  персональные данные владельца носителя (ВНЗ) и учётные данные в тексте ПМИ —
  на носитель и в git **не входят**.

Фрагмент `REPIKURR/geoserver_data/security/**` в git: конфигурации без
секретов (`config.xml`, `filter/*/config.xml`, `role/default/config.xml`,
`masterpw.xml`, `services.properties` и т. п.); фактические секреты (`jceks`,
`passwd`, `users.xml`) в git не входят (`git status --ignored`).

## 3. Локальные каталоги старой реализации (не отслеживаются git)

| Путь | Байт | Статус |
|---|---|---|
| `PIKURR/pyscr/**` | 685 028 | старая реализация (`pikurr_start.py`, `pylib/*`, `task_*.py`, `earthengine/credentials`, стили, `data/sources`) — **не часть текущей системы** (`legacy-diff.md`); содержит секрет (см. §2) |
| `PIKURR/database/**`, `PIKURR/sqlscripts/**`, `PIKURR/configs.ini` (1 516), `PIKURR/docker-compose.yml` (старый) | вместе с `pyscr` 689 467 (три каталога `find`) | старые файлы; решение о включении — за пользователем |
| `PIKURR/src/tasks/segmentate_old.py` | — | не в git; устаревшая версия сегментации |
| `PIKURR/test_*.py`, `PIKURR/dedug_inference.py` | — | не в git; тесты ETL (`test-methods.md`, §3) |

## 4. Веса моделей (отдельной строкой)

| Файл | Байт | Где лежит | Примечание |
|---|---|---|---|
| `two_opset13.onnx` | 47 209 600 | стенд: `/mnt/nfsdata/PIKURR/inputs/models/onnx/` (на координаторской машине нет); `sha256` начинается с `ab5d26830809eb3c` | используется ETL; сформирована из SavedModel `two` конвертацией `tf2onnx` (`docs/deploy-etl.md`) |
| `models/two/1/**` (SavedModel) | 51 145 741 (`saved_model.pb` 3 196 172; `keras_metadata.pb` 371 838; `variables.data-00000-of-00001` 47 558 666; `variables.index` 19 009; `fingerprint.pb` 56) | `inputs/models/two/1` (стенд и координаторская) | исходник для конвертации/откат |
| `models/one/1/**` (SavedModel) | 51 192 214 (`saved_model.pb` 3 242 191; `keras_metadata.pb` 371 994; `variables.data-00000-of-00001` 47 558 964; `variables.index` 19 009; `fingerprint.pb` 56) | то же | кодом не используется |
| `models.config`, `batching_parameters.txt` | 245 / 99 | то же | конфигурация отката на TF Serving |

Итого по трём наборам весов: 47 209 600 + 51 145 741 + 51 192 214 = 149 547 555 Б
(без конфигурационных файлов). Веса в git не хранятся (`.gitignore`).
Происхождение и условия использования моделей — вне репозитория (пробел).

## 5. Ориентир по объёму носителя (арифметика, не рекомендация)

- Только исходные тексты (первые 8 строк §1, без `docs/`, без производных
  артефактов `pikurr_qgis.zip` и `pikurr_qgis/help`): 226 857 + 21 840 +
  231 475 + 224 409 + 81 474 + 203 443 + 71 557 + 52 590 = **1 113 645 Б**;
- то же + веса трёх наборов моделей: 1 113 645 + 149 547 555 =
  **150 661 200 Б** (≈ 143,7 МиБ; старый носитель по ВНЗ — 103 104 502 Б,
  4,37 ГБ ёмкость);
- с `docs/` (+ 1 672 795) и `CLAUDE.md` (+ 91 583) — по решению пользователя.
