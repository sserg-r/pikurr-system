export const oblasts = {
  '12': 'Брестская',
  '22': 'Витебская',
  '32': 'Гомельская',
  '42': 'Гродненская',
  '52': 'г. Минск',
  '62': 'Минская',
  '72': 'Могилёвская',
}

export const distr = {'2208':'Браславский', '2210':'Верхнедвинский', '2215':'Глубокский', '2221':'Докшицкий', '2227':'Лепельский',
    '2233':'Миорский', '2238':'Полоцкий', '2240':'Поставский', '2242':'Россонский', '2249':'Ушачский', '2251':'Чашникский',
    '2255':'Шарковщинский', '2205':'Бешенковичский', '2212':'Витебский', '2218':'Городокский', '2224':'Дубровенский',
    '2230':'Лиозненский', '2236':'Оршанский', '2244':'Сенненский', '2246':'Толочинский', '2258':'Шумилинский',
    // Тестовые данные (Минская обл.)
    '6204':'Березинский'};

// export const GEOSERVER_URL = 'http://158.160.183.235:8080';
// export const GEOSERVER_URL = '/geoserver';
// используем переменную окружения Vite
export const GEOSERVER_URL = import.meta.env.VITE_GEOSERVER_URL;

export const WMS_BASE_URL = `${GEOSERVER_URL}/geoserver/pikurr/wms`;
export const WFS_BASE_URL = `${GEOSERVER_URL}/geoserver/wfs`;
export const WPS_BASE_URL = `${GEOSERVER_URL}/geoserver/wps`;

// round32, блок C.3: обычный `/geoserver/pikurr/wms` НЕ проксируется
// через GeoWebCache даже с `tiled=true` — проверено фактом (заголовок
// `geowebcache-cache-result` отсутствует на этом пути в любом случае).
// Кэш GWC реально включается только через отдельный эндпоинт
// `/geoserver/gwc/service/wms` (round32, блок B). Используется только
// для слоёв, реально зарегистрированных в GWC (`fields_latest`,
// `image_assessment` — без CQL_FILTER, единственные два слоя из блока
// B3); `fields` (историчный год, CQL_FILTER) и `image_assessment_<year>`
// не в GWC — идут через обычный эндпоинт, как раньше.
export const WMS_GWC_BASE_URL = `${GEOSERVER_URL}/geoserver/gwc/service/wms`;
export const GWC_CACHED_LAYERS = new Set(['pikurr:fields_latest', 'pikurr:image_assessment']);

