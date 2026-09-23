import http from 'k6/http';
import { check } from 'k6';
import { Counter, Trend } from 'k6/metrics';

// round32, блок D.2: k6 на фиксированном наборе из блока A (20 bbox с
// реальными данными, docs/round32_assets/tiles_with_data.json) — не
// случайные bbox, как в round28-31 (там 42-100% тайлов оказывались
// пустыми, round31 блок B, см. CLAUDE.md "Нагрузочный тест без проверки
// содержимого..."). Каждый VU проходит по всем 20 bbox за итерацию
// (упрощённая имитация загрузки страницы: 20 тайлов слоя fields_latest
// через реальный путь фронтенда — GWC-эндпоинт, round32 блок C).
//
// round33: перенесено из /tmp в репозиторий (SESSION_RESTART.md, п. 1) —
// путь к набору тайлов теперь ссылается на канонический файл
// docs/round32_assets/tiles_with_data.json, а не на отдельную копию.
//
// Запуск (из корня репозитория):
//   BASE_URL=https://geobotany.of.by VUS=3 REPS_PER_VU=3 \
//     k6 run REPIKURR/tools/k6_loadtest.js

const BASE = __ENV.BASE_URL || 'https://geobotany.of.by';
const TILES_PATH = __ENV.TILES_PATH || '../../docs/round32_assets/tiles_with_data.json';

const TILES = JSON.parse(open(TILES_PATH));

const tSizeBytes = new Trend('tile_size_bytes');
const smallTiles = new Counter('tiles_under_2kb');
const totalTiles = new Counter('tiles_total');

export const options = {
  scenarios: {
    vus_scenario: {
      executor: 'shared-iterations',
      vus: parseInt(__ENV.VUS || '1'),
      iterations: parseInt(__ENV.VUS || '1') * parseInt(__ENV.REPS_PER_VU || '1'),
      maxDuration: '120s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
  },
};

export default function () {
  const specs = TILES.map((t) => {
    const [minx, miny, maxx, maxy] = t.bbox_3857;
    const url = `${BASE}/geoserver/gwc/service/wms?service=WMS&version=1.1.1&request=GetMap&layers=pikurr:fields_latest&bbox=${minx},${miny},${maxx},${maxy}&width=256&height=256&srs=EPSG:3857&format=image/png&tiled=true`;
    return { method: 'GET', url, params: { responseType: 'binary' } };
  });
  const responses = http.batch(specs);
  for (const r of responses) {
    check(r, { 'status 200': (resp) => resp.status === 200 });
    const size = r.body ? r.body.byteLength : 0;
    tSizeBytes.add(size);
    totalTiles.add(1);
    if (size < 2048) smallTiles.add(1);
  }
}
