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
export async function loadYearDistrictData() {
  const url = `${WFS_BASE_URL}?service=WFS&version=1.0.0&request=GetFeature&typeName=pikurr:fields&propertyName=year,nr_user&outputFormat=application%2Fjson&maxFeatures=300000`
  const json = await fetchJSON(url)
  const map = {}
  for (const f of (json.features || [])) {
    const year = f.properties?.year
    const nr = f.properties?.nr_user
    if (!year || !nr) continue
    const district = String(nr).substring(0, 4)
    if (!map[year]) map[year] = new Set()
    map[year].add(district)
  }
  const years = Object.keys(map).map(Number).sort((a, b) => a - b)
  return { years, districtsByYear: map }
}

export function getLegendUrl(layer) {
  const url = `${WMS_BASE_URL}?SERVICE=WMS&REQUEST=GetLegendGraphic&FORMAT=image/png&LAYER=${encodeURIComponent(layer)}`
  return url
   // return `${WMS_BASE_URL}?SERVICE=WMS&REQUEST=GetLegendGraphic&FORMAT=image/png&TRANSPARENT=true&LAYER=${encodeURIComponent(layer)}`
}

