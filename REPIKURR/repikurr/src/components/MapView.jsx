import 'leaflet/dist/leaflet.css'
import { MapContainer, TileLayer, WMSTileLayer, Popup, useMap, useMapEvents } from 'react-leaflet'
import { WMS_BASE_URL } from '../constants'
import { useEffect, useMemo, useState } from 'react'

function FitBounds({ bbox }) {
  const map = useMap()
  useEffect(() => {
    if (bbox) {
      const southWest = [bbox.miny, bbox.minx]
      const northEast = [bbox.maxy, bbox.maxx]
      map.fitBounds([southWest, northEast])
    }
  }, [bbox, map])
  return null
}

function FeatureInfo({ layerName, cqlExpr }) {
  const map = useMapEvents({
    click: async (e) => {
      try {
        const point = map.latLngToContainerPoint(e.latlng, map.getZoom())
        const size = map.getSize()
        const bounds = map.getBounds()
        const bboxParam = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`
        const params = new URLSearchParams({
          service: 'WMS',
          version: '1.1.1',
          request: 'GetFeatureInfo',
          srs: 'EPSG:4326',
          bbox: bboxParam,
          width: String(size.x),
          height: String(size.y),
          x: String(Math.round(point.x)),
          y: String(Math.round(point.y)),
          layers: layerName,
          query_layers: layerName,
          info_format: 'application/json',
          feature_count: '10',
        })
        if (cqlExpr) params.set('CQL_FILTER', cqlExpr)
        const url = `${WMS_BASE_URL}?${params.toString()}`
        const resp = await fetch(url)
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const json = await resp.json()
        const first = json?.features?.[0]
        if (first) {
          setPopup({ latlng: e.latlng, props: first.properties })
        } else {
          setPopup(null)
        }
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error(err)
      }
    },
  })
  const [popup, setPopup] = useState(null)
  const props = popup?.props || null
  return popup ? (
    <Popup position={popup.latlng} onClose={() => setPopup(null)}>
      <div style={{ maxWidth: 360 }}>
        {props?.description ? (
          <div dangerouslySetInnerHTML={{ __html: props.description }} />
        ) : null}
        <div style={{ marginTop: 8 }}>
          {Object.entries(props || {})
           .filter(([k]) => k !== 'description')
           .filter(([k]) => ['nr_user', 'year', 'ball_co', 'bzdz', 'area_ha', 'valuation'].includes(k))
           .map(([k, v]) => {
             const propertyNames = {
               nr_user: "id землепользователя",
               year: "год оценки",
               ball_co: "балл КО",
               bzdz: "балл bzdz",
               area_ha: "площадь, га",
               valuation: "оценка"
             };
             return (
               <div key={k} style={{ display: 'flex', gap: 8 }}>
                 <div style={{ minWidth: 140, fontWeight: 600 }}>{propertyNames[k] || k}</div>
                 <div style={{ flex: 1 }}>{String(v)}</div>
               </div>
             );
           })}
        </div>
      </div>
    </Popup>
  ) : null
}

export default function MapView({ baseLayer, bbox, cqlExpr, showVectors, showMosaic, selectedYear, maxYear }) {
  const initialCenter = useMemo(() => [55.2, 29.6], [])
  const cacheBuster = useMemo(() => (cqlExpr ? Date.now() : undefined), [cqlExpr])
  // When no year is selected, use fields_latest (one record per field, latest year)
  const vectorLayer = selectedYear ? 'pikurr:fields' : 'pikurr:fields_latest'
  // image_assessment = latest year; image_assessment_{year} = specific older year
  const effectiveYear = selectedYear ?? maxYear
  const rasterLayer = (!effectiveYear || effectiveYear === maxYear)
    ? 'image_assessment'
    : `image_assessment_${effectiveYear}`
  return (
    <MapContainer center={initialCenter} zoom={9} style={{ height: '100%', width: '100%' }}>
      <FitBounds bbox={bbox} />
      <FeatureInfo layerName={vectorLayer} cqlExpr={cqlExpr} />
      {baseLayer === 'osm' && (
        <TileLayer zIndex={100} url="https://{s}.tile.openstreetmap.de/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap" />
      )}
      {baseLayer === 'esri' && (
        <TileLayer zIndex={100} url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}" attribution="Tiles &copy; Esri" />
      )}
      {showMosaic && (
        <WMSTileLayer
          key={`mosaic-${rasterLayer}`}
          zIndex={300}
          url={`${WMS_BASE_URL}`}
          version="1.1.1"
          layers={rasterLayer}
          format="image/png"
          transparent
        />
      )}
      {showVectors && (
        <WMSTileLayer
          key={vectorLayer}
          zIndex={500}
          url={`${WMS_BASE_URL}`}
          version="1.1.1"
          layers={vectorLayer}
          format="image/png"
          transparent
          params={cqlExpr ? { CQL_FILTER: cqlExpr, time: cacheBuster } : undefined}
        />
      )}
    </MapContainer>
  )
}

