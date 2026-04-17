import { getLegendUrl } from '../services/geoserver'

export default function WmsLegend({ layer, title = 'AI оценка', floating = false }) {
  if (!layer) return null
  const url = getLegendUrl(layer)
  return (
    <div style={floating ? { position: 'absolute', right: 12, bottom: 12, background: '#fff', padding: 12, border: '1px solid #e5e7eb', boxShadow: '0 2px 8px rgba(0,0,0,0.08)', zIndex: 2000, width: 'min(200px, 60vw)', maxHeight: '70vh', overflow: 'auto' } : { marginTop: 12 }}>
      <div style={{ fontWeight: 700, marginBottom: 10, fontSize: 16 }}>{title}</div>
      <img src={url} alt="WMS Legend" style={{ display: 'block', width: '80%', height: 'auto', background: '#fff' }} />
    </div>
  )
}

