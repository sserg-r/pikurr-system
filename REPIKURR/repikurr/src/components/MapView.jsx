import 'leaflet/dist/leaflet.css'
import { MapContainer, TileLayer, WMSTileLayer, ZoomControl, Popup, useMap, useMapEvents } from 'react-leaflet'
import { WMS_BASE_URL } from '../constants'
import { useEffect, useMemo, useState } from 'react'
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

// Заменяет английские названия категорий растительности в HTML-таблице на русские
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
        {props?.description && (
          <div
            className="popup-description"
            dangerouslySetInnerHTML={{ __html: translateDescHtml(props.description) }}
          />
        )}
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
export default function MapView({ baseLayer, bbox, cqlExpr, showVectors, showMosaic, selectedYear, maxYear }) {
  const initialCenter = useMemo(() => [55.2, 29.6], [])
  const cacheBuster   = useMemo(() => (cqlExpr ? Date.now() : undefined), [cqlExpr])
  const [clickCoords, setClickCoords] = useState(null)

  // Мемоизируем params чтобы WMSTileLayer не пересоздавался при посторонних ре-рендерах
  const wmsVectorParams = useMemo(
    () => cqlExpr ? { CQL_FILTER: cqlExpr, time: cacheBuster } : undefined,
    [cqlExpr, cacheBuster]
  )

  const vectorLayer = selectedYear ? 'pikurr:fields' : 'pikurr:fields_latest'
  const effectiveYear = selectedYear ?? maxYear
  const rasterLayer = (!effectiveYear || effectiveYear === maxYear)
    ? 'image_assessment'
    : `image_assessment_${effectiveYear}`

  return (
    <div style={{ position: 'relative', height: '100%', width: '100%' }}>
      <MapContainer center={initialCenter} zoom={9} zoomControl={false} style={{ height: '100%', width: '100%' }}>
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
          <WMSTileLayer key={`mosaic-${rasterLayer}`} zIndex={300}
            url={WMS_BASE_URL} version="1.1.1"
            layers={rasterLayer} format="image/png" transparent />
        )}
        {showVectors && (
          <WMSTileLayer key={vectorLayer} zIndex={500}
            url={WMS_BASE_URL} version="1.1.1"
            layers={vectorLayer} format="image/png" transparent
            params={wmsVectorParams} />
        )}
      </MapContainer>

      <CoordBar coords={clickCoords} />
    </div>
  )
}
