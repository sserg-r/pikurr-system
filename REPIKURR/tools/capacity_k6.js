// round40, блок A — модель нагрузки "пользователь = браузерная сессия".
//
// Каждый VU держит свою cookie jar (проверено фактом round40 A1 —
// GeoServer выдаёт `GS_FLOW_CONTROL` при первом запросе без кук, второй
// запрос с той же VU присылает cookie обратно и получает СВОЙ отдельный
// ключ очереди control-flow, отличный от других VU: три параллельных VU
// дали три разных значения `GS_CFLOW_...:-7ff1/-7ff2/-7ff3` за один
// прогон) — значит при `user=6` в controlflow.properties k6 действительно
// моделирует N независимых пользователей, а не одного с N потоками.
//
// Состав действий (A2, стартовые доли из ТЗ, меняются флагами):
//   70% NAV   — навигация по засеянным областям, GWC-путь (tiled=true),
//               ожидание HIT.
//   20% GROUP — выбранная группа/землепользователь, верхний
//               фильтрованный слой (`CQL_FILTER=nr_user LIKE '...'`)
//               ВСЕГДА через обычный /geoserver/pikurr/wms, мимо GWC
//               (CLAUDE.md "Ловушки": GWC игнорирует CQL_FILTER) —
//               самый дорогой путь.
//   10% MISS  — глубокий зум за пределами засеянного диапазона (z17-18
//               вместо z13 — тайлы того же bbox, но мельче, что GWC не
//               засевал).
//
// Batch-размеры (A1) — ПЕРЕСНЯТЫ ФАКТОМ round40 (Playwright,
// `measure_batch_sizes.mjs`, 3 прогона, все три стабильно совпали) с
// живого фронтенда, не приближение из round28 A3 (то было до подсветки
// группы round37 и до зачистки 2024 round39, к тому же меньший viewport):
//   первая загрузка страницы  — 30 тайлов (было 24 в round28)
//   сдвиг (pan)                — 4 тайла (было 8, ТЗ предполагало 8-12)
//   включение слоя AI-оценки   — 20 тайлов (было 16)
//   клик по полю                — 1 запрос (GetFeatureInfo, подтверждено)
// Модель NAV ниже: первое действие VU — загрузка (30 тайлов), дальше
// смесь сдвигов (80%, 4 тайла) и включения растра (20%, 20 тайлов).
//   GROUP (клик по группе) — до 8 тайлов текущего охвата + 1 клик
//   MISS (глубокий зум)    — 8 тайлов
//
// Пауза между ДЕЙСТВИЯМИ (не между тайлами внутри действия) — 3-10с.
//
// Запуск (стенд, т.к. с координаторской машины исходящий интернет из
// docker заблокирован — round40 A1, подтверждено фактом):
//   BASE_URL=https://geobotany.of.by VUS=15 DURATION=60s \
//     docker run --rm -i -e BASE_URL -e VUS -e DURATION \
//       -v "$PWD":/scripts grafana/k6 run /scripts/capacity_k6.js
// (либо через stdin, если volume mount недоступен — см. round40 отчёт)

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE = __ENV.BASE_URL || 'https://geobotany.of.by';
const TILES_PATH = __ENV.TILES_PATH || '../../docs/round32_assets/tiles_with_data.json';
const TILES = JSON.parse(open(TILES_PATH));

// Реальные коды землепользователей (WFS levelsagg, снято фактом round40 A блок).
const GROUP_CODES = ['2212000055', '2238000015', '2212000077', '2212000113'];

const smallTiles = new Counter('tiles_under_2kb');
const totalTiles = new Counter('tiles_total');
const hitRate = new Rate('gwc_hit_rate');
const exceptionBodies = new Counter('service_exception_bodies');

const actionDurNav = new Trend('action_duration_nav', true);
const actionDurGroup = new Trend('action_duration_group', true);
const actionDurMiss = new Trend('action_duration_miss', true);
const actionErrNav = new Rate('action_error_nav');
const actionErrGroup = new Rate('action_error_group');
const actionErrMiss = new Rate('action_error_miss');

export const options = {
  scenarios: {
    users: {
      executor: 'constant-vus',
      vus: parseInt(__ENV.VUS || '1'),
      duration: __ENV.DURATION || '60s',
    },
  },
  thresholds: {
    // Ступень останавливается вручную при >5% ошибок (блок B п.1) —
    // порог здесь только чтобы k6 явно пометил прогон, не прерывал сам.
    http_req_failed: ['rate<1.0'],
  },
};

function pick(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

function checkBody(r, results) {
  totalTiles.add(1);
  // responseType:'binary' даёт ArrayBuffer (.byteLength), 'text' — строку
  // (.length) — округление GetFeatureInfo/JSON под "тайл < 2КБ" не имеет
  // смысла (не тайл), но метрику size всё равно считаем корректно для
  // обоих типов, иначе .byteLength на строке всегда undefined → 0 →
  // ложный "мелкий/пустой ответ" (найдено этим же смоук-прогоном).
  const size = r.body ? (r.body.byteLength !== undefined ? r.body.byteLength : r.body.length) : 0;
  if (size < 2048) smallTiles.add(1);
  const cacheResult = r.headers['Geowebcache-Cache-Result'] || r.headers['geowebcache-cache-result'];
  if (cacheResult) hitRate.add(cacheResult.toUpperCase() === 'HIT');
  // ServiceExceptionReport может прийти с HTTP 200 (CLAUDE.md, "Критерий
  // приёмки") — искать по телу, не по коду, но только для текстовых/малых
  // тел (бинарный PNG не декодировать как текст — баг round27 B4).
  const ct = (r.headers['Content-Type'] || r.headers['content-type'] || '');
  if (ct.includes('xml') || ct.includes('text')) {
    const text = r.body ? r.body.toString() : '';
    if (text.includes('ServiceExceptionReport')) exceptionBodies.add(1);
  }
  const ok = check(r, { 'status 200': (resp) => resp.status === 200 });
  results.push(ok && size > 0);
}

function actionNav(isFirst) {
  const t0 = Date.now();
  // round40 A1, пересъёмка фактом: загрузка=30, сдвиг=4, растр=20.
  let n;
  if (isFirst) {
    n = 30;
  } else if (Math.random() < 0.8) {
    n = 4; // сдвиг
  } else {
    n = 20; // включение растра
  }
  const specs = [];
  for (let i = 0; i < n; i++) {
    const t = pick(TILES);
    const [minx, miny, maxx, maxy] = t.bbox_3857;
    const layer = Math.random() < 0.5 ? 'pikurr:fields_latest' : 'pikurr:image_assessment';
    const url = `${BASE}/geoserver/gwc/service/wms?service=WMS&version=1.1.1&request=GetMap&layers=${encodeURIComponent(layer)}&bbox=${minx},${miny},${maxx},${maxy}&width=256&height=256&srs=EPSG:3857&format=image/png&tiled=true`;
    specs.push({ method: 'GET', url, params: { responseType: 'binary', tags: { action: 'nav' } } });
  }
  const responses = http.batch(specs);
  const results = [];
  for (const r of responses) checkBody(r, results);
  actionDurNav.add(Date.now() - t0);
  actionErrNav.add(results.some((ok) => !ok));
}

function actionGroup() {
  const t0 = Date.now();
  const code = pick(GROUP_CODES);
  const t = pick(TILES);
  const [minx, miny, maxx, maxy] = t.bbox_3857;
  const n = 4 + Math.floor(Math.random() * 5); // 4-8, мимо кэша дороже — меньше батч
  const specs = [];
  for (let i = 0; i < n; i++) {
    const cql = encodeURIComponent(`nr_user LIKE '${code.slice(0, 4)}%' AND year=2025`);
    const url = `${BASE}/geoserver/pikurr/wms?service=WMS&version=1.1.1&request=GetMap&layers=pikurr:fields&bbox=${minx},${miny},${maxx},${maxy}&width=256&height=256&srs=EPSG:3857&format=image/png&CQL_FILTER=${cql}`;
    specs.push({ method: 'GET', url, params: { responseType: 'binary', tags: { action: 'group' } } });
  }
  // клик — GetFeatureInfo поверх той же области/фильтра
  const infoCql = encodeURIComponent(`nr_user LIKE '${code.slice(0, 4)}%' AND year=2025`);
  const infoUrl = `${BASE}/geoserver/pikurr/wms?service=WMS&version=1.1.1&request=GetFeatureInfo&layers=pikurr:fields&query_layers=pikurr:fields&bbox=${minx},${miny},${maxx},${maxy}&width=256&height=256&srs=EPSG:3857&x=128&y=128&info_format=application/json&CQL_FILTER=${infoCql}`;
  specs.push({ method: 'GET', url: infoUrl, params: { responseType: 'text', tags: { action: 'group_click' } } });
  const responses = http.batch(specs);
  const results = [];
  for (const r of responses) checkBody(r, results);
  actionDurGroup.add(Date.now() - t0);
  actionErrGroup.add(results.some((ok) => !ok));
}

function actionMiss() {
  const t0 = Date.now();
  const base = pick(TILES);
  const n = 8;
  const specs = [];
  // Мельчим bbox базового (засеянного) тайла в 4 непересекающихся
  // подтайла (z+2 эквивалент) — та же геопозиция, за пределами
  // засеянного диапазона зума GWC (z9-14, см. CLAUDE.md) => MISS.
  const [minx, miny, maxx, maxy] = base.bbox_3857;
  const w = (maxx - minx) / 4;
  const h = (maxy - miny) / 4;
  for (let i = 0; i < n; i++) {
    const cx = minx + (i % 4) * w;
    const cy = miny + Math.floor(i / 4) * h;
    const url = `${BASE}/geoserver/gwc/service/wms?service=WMS&version=1.1.1&request=GetMap&layers=pikurr:fields_latest&bbox=${cx},${cy},${cx + w},${cy + h}&width=256&height=256&srs=EPSG:3857&format=image/png&tiled=true`;
    specs.push({ method: 'GET', url, params: { responseType: 'binary', tags: { action: 'miss' } } });
  }
  const responses = http.batch(specs);
  const results = [];
  for (const r of responses) checkBody(r, results);
  actionDurMiss.add(Date.now() - t0);
  actionErrMiss.add(results.some((ok) => !ok));
}

export default function () {
  const roll = Math.random();
  if (roll < 0.70) actionNav(__ITER === 0);
  else if (roll < 0.90) actionGroup();
  else actionMiss();
  sleep(3 + Math.random() * 7); // 3-10с думскейт между действиями
}
