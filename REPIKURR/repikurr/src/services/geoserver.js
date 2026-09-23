import { WPS_BASE_URL, WMS_BASE_URL, WFS_BASE_URL } from '../constants'

async function fetchText(url, options) {
  const resp = await fetch(url, options)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.text()
}

async function fetchJSON(url, options) {
  const resp = await fetch(url, options)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

export async function getAllUsers() {
  const body = await (await fetch('/getallusers.xml')).text()
  const url = `${WPS_BASE_URL}`
  const res = await fetchJSON(url, {
    method: 'POST',
    headers: { 'Content-Type': 'text/xml' },
    body,
  })
  return res
}

export async function getStatsByUser(cqlFilter) {
  let tpl = await (await fetch('/getstatsbyuser.xml')).text()
  tpl = tpl.replace('{{CQL_FILTER}}', cqlFilter)
  const url = `${WPS_BASE_URL}`
  const res = await fetchJSON(url, {
    method: 'POST',
    headers: { 'Content-Type': 'text/xml' },
    body: tpl,
  })
  return res
}

export async function getBboxByUser(cqlFilter) {
  let tpl = await (await fetch('/getbboxbyuser.xml')).text()
  tpl = tpl.replace('{{CQL_FILTER}}', cqlFilter)
  const url = `${WPS_BASE_URL}`
  const xml = await fetchText(url, {
    method: 'POST',
    headers: { 'Content-Type': 'text/xml' },
    body: tpl,
  })
  const m = xml.match(/<ows:LowerCorner>([^<]+)<\/ows:LowerCorner>.*?<ows:UpperCorner>([^<]+)<\/ows:UpperCorner>/)
  if (!m) throw new Error('BBox parse error')
  const [minx, miny] = m[1].split(' ').map(Number)
  const [maxx, maxy] = m[2].split(' ').map(Number)
  return { minx, miny, maxx, maxy }
}

// Loads available years AND district→year mapping in one request.
// Returns { years: number[], districtsByYear: { [year]: Set<districtId4char> } }
//
// round23, задача 1: раньше — WFS-запрос ко ВСЕМ объектам pikurr:fields
// (тянул геометрию и все поля каждого из 55784+ объектов только чтобы
// построить выпадающие списки годов/районов, ~12с). Данные между
// доставками не меняются, поэтому список считает deliver.py один раз на
// доставку (write_year_district_lookup()) и отдаёт статикой через Caddy —
// GeoServer в этом запросе больше не участвует (замер: 12с → ~0.5с).
export async function loadYearDistrictData() {
  const json = await fetchJSON('/static/year_district.json')
  const map = {}
  for (const [year, districts] of Object.entries(json.districtsByYear || {})) {
    map[year] = new Set(districts)
  }
  const years = (json.years || []).slice().sort((a, b) => a - b)
  // round32, блок C: `dataVersion` — метка последней доставки
  // (deliver.py, write_year_district_lookup()), меняется ТОЛЬКО при
  // доставке. Используется вместо Date.now() как параметр URL тайла —
  // между доставками URL стабилен (кэшируется браузером/GWC).
  return { years, districtsByYear: map, dataVersion: json.dataVersion || null }
}

export function getLegendUrl(layer) {
  const url = `${WMS_BASE_URL}?SERVICE=WMS&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER=${encodeURIComponent(layer)}`
  return url
   // return `${WMS_BASE_URL}?SERVICE=WMS&REQUEST=GetLegendGraphic&FORMAT=image/png&TRANSPARENT=true&LAYER=${encodeURIComponent(layer)}`
}

