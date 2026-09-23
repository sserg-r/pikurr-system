import 'leaflet/dist/leaflet.css'
import { MapContainer, TileLayer, WMSTileLayer, ZoomControl, AttributionControl, Popup, useMap, useMapEvents } from 'react-leaflet'
import { WMS_BASE_URL, WMS_GWC_BASE_URL, GWC_CACHED_LAYERS } from '../constants'
import { useEffect, useMemo, useRef, useState } from 'react'
import './MapView.css'

/* ---- FitBounds ---- */
function FitBounds({ bbox }) {
  const map = useMap()
  useEffect(() => {
    if (bbox) map.fitBounds([[bbox.miny, bbox.minx], [bbox.maxy, bbox.maxx]])
  }, [bbox, map])
  return null
}

/* ---- Feature info popup ---- */
const PROPERTY_LABELS = {
  nr_user:  'id землепользователя',
  year:     'год оценки',
  ball_co:  'балл КО',
  bzdz:     'Благоприятность земледелия',
  area_ha:  'площадь, га',
  valuation:'оценка',
}
const SHOWN_KEYS = Object.keys(PROPERTY_LABELS)

const VALUATION_RU = {
  forest:   'перевод в л/х',
  clearing: 'с/х после расчистки',
  meadow:   'луговое с/х',
  tillage:  'пахотное с/х',
}

// Таблица растительности из stats JSON (новые данные)
const STATS_LABELS = { '0':'лес', '1':'кустарник', '2':'закуст. луг', '3':'луг', '4':'прочее', '5':'пашня' }
const STATS_COLORS = { '0':'#4e7626', '1':'#30b646', '2':'#acf189', '3':'#deffcf', '4':'#f8f5c4', '5':'#cba27b' }

function StatsTable({ statsRaw }) {
  let stats
  try { stats = typeof statsRaw === 'string' ? JSON.parse(statsRaw) : statsRaw } catch { return null }
  const rows = Object.entries(stats)
    .filter(([, v]) => Number(v) > 0)
    .sort(([a], [b]) => Number(a) - Number(b))
  if (!rows.length) return null
  return (
    <table className="popup-stats-table">
      <tbody>
        {rows.map(([cls, pct]) => (
          <tr key={cls}>
            <td>
              <span className="popup-stats-swatch" style={{ background: STATS_COLORS[cls] || '#999' }} />
              {STATS_LABELS[cls] || cls}
            </td>
            <td className="popup-stats-pct">{(Number(pct) * 100).toFixed(1)}%</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// Fallback для legacy-данных: перевод английских меток в HTML-таблице
const DESC_TRANSLATIONS = [
  [/\bforest\b/gi,  'лес'],
  [/\bbushes\b/gi,  'кустарник'],
  [/\bbushy\b/gi,   'закуст. луг'],
  [/\bmeadows\b/gi, 'луг'],
  [/\bother\b/gi,   'прочее'],
  [/\btillage\b/gi, 'пашня'],
]
function translateDescHtml(html) {
  if (!html) return html
  return DESC_TRANSLATIONS.reduce((s, [re, ru]) => s.replace(re, ru), html)
}

function formatValue(k, v) {
  const s = String(v)
  if (k === 'valuation') return VALUATION_RU[s] ?? s
  return s
}

function FeatureInfo({ layerName, cqlExpr, onMapClick }) {
  const [popup, setPopup] = useState(null)

  const map = useMapEvents({
    click: async (e) => {
      onMapClick?.(e.latlng)

      try {
        const point  = map.latLngToContainerPoint(e.latlng, map.getZoom())
        const size   = map.getSize()
        const bounds = map.getBounds()
        const params = new URLSearchParams({
          service: 'WMS', version: '1.1.1', request: 'GetFeatureInfo',
          srs: 'EPSG:4326',
          bbox: `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`,
          width: String(size.x), height: String(size.y),
          x: String(Math.round(point.x)), y: String(Math.round(point.y)),
          layers: layerName, query_layers: layerName,
          info_format: 'application/json', feature_count: '10',
        })
        if (cqlExpr) params.set('CQL_FILTER', cqlExpr)
        const resp = await fetch(`${WMS_BASE_URL}?${params}`)
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const json = await resp.json()
        const first = json?.features?.[0]
        setPopup(first ? { latlng: e.latlng, props: first.properties } : null)
      } catch (err) {
        console.error(err)
      }
    },
  })

  const props = popup?.props || null
  return popup ? (
    <Popup position={popup.latlng} onClose={() => setPopup(null)}>
      <div className="map-popup">
        <h3>Детали участка</h3>
        {props?.stats
          ? <StatsTable statsRaw={props.stats} />
          : props?.description && (
              <div
                className="popup-description"
                dangerouslySetInnerHTML={{ __html: translateDescHtml(props.description) }}
              />
            )
        }
        <div className="popup-properties">
          {SHOWN_KEYS
            .filter(k => props[k] !== undefined && props[k] !== null)
            .map(k => (
              <div key={k} className="property-row">
                <span className="property-name">{PROPERTY_LABELS[k]}</span>
                <span className="property-value">{formatValue(k, props[k])}</span>
              </div>
            ))}
        </div>
      </div>
    </Popup>
  ) : null
}

/* ---- Coordinate bar (показывает координаты последнего клика) ---- */
function CoordBar({ coords }) {
  const [copied, setCopied] = useState(false)
  if (!coords) return null

  const text = `${coords.lat.toFixed(6)}, ${coords.lng.toFixed(6)}`

  const handleCopy = () => {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div className="coord-bar">
      <span className="coord-label">📍</span>
      <span className="coord-text">{text}</span>
      <button className="coord-copy" onClick={handleCopy} title="Скопировать координаты">
        {copied ? '✓' : '⎘'}
      </button>
    </div>
  )
}

/* ---- MapView ---- */
export default function MapView({ baseLayer, bbox, cqlExpr, showVectors, showMosaic, selectedYear, maxYear, dataVersion }) {
  const initialCenter = useMemo(() => [55.2, 29.6], [])
  // round29, блок C: раньше cacheBuster (и вместе с ним весь параметр
  // `time` в URL тайла) существовал ТОЛЬКО когда был активен CQL-фильтр
  // — у `pikurr:fields` (историчный год) он почти всегда есть (год сам
  // становится частью фильтра), а у `pikurr:fields_latest` (режим "все
  // годы", фильтра нет) — никогда. round28, A6 нашёл фактом: именно
  // отсутствие `&time=<epoch>` у `fields_latest` даёт один случайный
  // HTTP 503 в прошлом навсегда "залипнуть" в HTTP-кэше браузера для
  // этого URL — `fields` той же уязвимости не подвержен ровно потому,
  // что кэш-бастер у него уже был. Единый механизм для обоих слоёв.
  //
  // round32, блок C: сам `Date.now()` был ПРИЧИНОЙ, по которой ни браузер,
  // ни GWC не могли ничего закэшировать — URL каждого тайла был уникален
  // на каждую загрузку страницы, а не только на каждую доставку данных.
  // `dataVersion` (из `/static/year_district.json`, пишется deliver.py
  // ТОЛЬКО при доставке) даёт то же самое разрешение задачи round29 A6
  // (после доставки URL меняется — старые тайлы не залипают), но НЕ
  // меняет URL между доставками — значит, кэш браузера и GWC реально
  // работают. Пока `dataVersion` ещё не загрузился (самый первый рендер
  // до ответа `/static/year_district.json`) — используем 'loading' как
  // временное значение, а не `Date.now()`, чтобы не создавать одноразовый
  // уникальный URL даже на долю секунды.
  const cacheBuster   = dataVersion || 'loading'
  const [clickCoords, setClickCoords] = useState(null)

  const vectorLayer = selectedYear ? 'pikurr:fields' : 'pikurr:fields_latest'
  const effectiveYear = selectedYear ?? maxYear
  const rasterLayer = (!effectiveYear || effectiveYear === maxYear)
    ? 'image_assessment'
    : `image_assessment_${effectiveYear}`

  // round32, блок C.3: обычный `/geoserver/pikurr/wms` НЕ проксируется
  // через GWC даже с `tiled=true` (проверено фактом, блок B) — кэшируемые
  // слои идут через отдельный эндпоинт `/geoserver/gwc/service/wms` с
  // `tiled=true`; остальные (fields с CQL_FILTER, историчные растры) —
  // как раньше, напрямую.
  const vectorFqName = `pikurr:${vectorLayer.replace(/^pikurr:/, '')}`
  const rasterFqName = `pikurr:${rasterLayer}`
  const vectorIsCached = GWC_CACHED_LAYERS.has(vectorFqName)
  const rasterIsCached = GWC_CACHED_LAYERS.has(rasterFqName)
  const vectorWmsUrl = vectorIsCached ? WMS_GWC_BASE_URL : WMS_BASE_URL
  const rasterWmsUrl = rasterIsCached ? WMS_GWC_BASE_URL : WMS_BASE_URL

  // round33, блок C.1: недоступность GeoServer (весь бэкенд лежит, а не
  // просто один тайл) раньше была не видна пользователю — сломанные тайлы
  // молча не грузились. Считаем ошибки тайлов слоя данных за короткое
  // окно; при их накоплении показываем баннер поверх карты (сама карта —
  // базовая подложка OSM/Esri — продолжает работать, т.к. не зависит от
  // GeoServer). Retry — сброс счётчика и перезапрос через смену key.
  const [tileErrorBanner, setTileErrorBanner] = useState(false)
  const [reloadNonce, setReloadNonce] = useState(0)
  const tileErrorCountRef = useRef(0)
  const tileErrorWindowRef = useRef(0)
  const handleTileError = () => {
    const now = Date.now()
    if (now - tileErrorWindowRef.current > 5000) {
      tileErrorWindowRef.current = now
      tileErrorCountRef.current = 0
    }
    tileErrorCountRef.current += 1
    if (tileErrorCountRef.current >= 3) setTileErrorBanner(true)
  }
  const retryTiles = () => {
    setTileErrorBanner(false)
    tileErrorCountRef.current = 0
    setReloadNonce(n => n + 1)
  }

  // round33, блок A: `vectorIsCached`/`rasterIsCached` — `const`, а
  // useMemo ниже их читал ДО этой точки объявления (temporal dead zone) —
  // React бросал `ReferenceError: Cannot access 'X' before initialization`
  // на каждом рендере без исключения (не только после ребута VPS),
  // без ErrorBoundary это гарантированно давало белый экран всегда.
  // Мемоизируем params чтобы WMSTileLayer не пересоздавался при посторонних ре-рендерах
  const wmsVectorParams = useMemo(
    () => ({
      ...(cqlExpr ? { CQL_FILTER: cqlExpr } : {}),
      time: cacheBuster,
      ...(vectorIsCached ? { tiled: true } : {}),
    }),
    [cqlExpr, cacheBuster, vectorIsCached]
  )
  const wmsRasterParams = useMemo(
    () => (rasterIsCached ? { tiled: true } : {}),
    [rasterIsCached]
  )

  return (
    <div style={{ position: 'relative', height: '100%', width: '100%' }}>
      <MapContainer center={initialCenter} zoom={9} zoomControl={false} attributionControl={false} style={{ height: '100%', width: '100%' }}>
        {/* round33, блок C.3: убрана ссылка на саму Leaflet (prefix) —
            установлено фактом (см. docs/round33-reboot-incident.md), что
            базовые подложки — сторонние (OpenStreetMap, Esri), их
            указание обязательно условиями использования и сохранено
            через attribution проп у TileLayer ниже; сам движок карт
            (Leaflet) — не источник данных, ссылка на него не требуется. */}
        <AttributionControl position="bottomright" prefix={false} />
        <ZoomControl position="topright" />
        <FitBounds bbox={bbox} />
        <FeatureInfo layerName={vectorLayer} cqlExpr={cqlExpr} onMapClick={setClickCoords} />

        {baseLayer === 'osm' && (
          <TileLayer zIndex={100}
            url="https://{s}.tile.openstreetmap.de/{z}/{x}/{y}.png"
            attribution="&copy; OpenStreetMap" />
        )}
        {baseLayer === 'esri' && (
          <TileLayer zIndex={100}
            url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            attribution="Tiles &copy; Esri" />
        )}
        {showMosaic && (
          // round34, блок A: `layers` для растра должен быть с workspace-префиксом
          // (`rasterFqName`), не голым `rasterLayer` — `/geoserver/pikurr/wms`
          // принимает оба варианта (workspace уже в пути), но `/geoserver/gwc/service/wms`
          // не виртуализован по workspace и без префикса отдаёт 400 Unknown layer.
          <WMSTileLayer key={`mosaic-${rasterLayer}-${reloadNonce}`} zIndex={300}
            url={rasterWmsUrl} version="1.1.1"
            layers={rasterFqName} format="image/png" transparent
            params={wmsRasterParams}
            eventHandlers={{ tileerror: handleTileError }} />
        )}
        {showVectors && (
          <WMSTileLayer key={`${vectorLayer}-${reloadNonce}`} zIndex={500}
            url={vectorWmsUrl} version="1.1.1"
            layers={vectorLayer} format="image/png" transparent
            params={wmsVectorParams}
            eventHandlers={{ tileerror: handleTileError }} />
        )}
      </MapContainer>

      {tileErrorBanner && (
        <div style={{
          position: 'absolute', top: 8, left: '50%', transform: 'translateX(-50%)',
          zIndex: 1000, background: '#f8d7da', border: '1px solid #f5c2c7',
          borderRadius: 6, padding: '8px 16px', display: 'flex', alignItems: 'center',
          gap: 12, boxShadow: '0 2px 6px rgba(0,0,0,0.15)', fontSize: 14,
        }}>
          <span>Слой данных недоступен (проблема на сервере карт). Базовая подложка работает.</span>
          <button
            onClick={retryTiles}
            style={{ cursor: 'pointer', padding: '4px 10px', borderRadius: 4, border: '1px solid #ccc' }}
          >
            Повторить
          </button>
        </div>
      )}

      <CoordBar coords={clickCoords} />
    </div>
  )
}
