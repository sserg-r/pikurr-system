// round50, блок B.3: проверка функции getBboxByUser() напрямую (не через
// весь UI) — надёжнее, чем гонка состояний Sidebar/App при моканых годах.
// 2024 год не существует на проде вообще (единственный реальный год —
// 2025) — гарантированно пустая выборка.
import { readFileSync } from 'node:fs'
const BASE = 'https://geobotany.of.by'
// round50: шаблон — ЛОКАЛЬНЫЙ (round49/50 правки ещё не задеплоены на
// прод, там всё ещё старая версия с {{CQL_FILTER}}) — сам GeoServer/WPS
// не менялись, меняется только фронтенд-шаблон, поэтому тестируем
// локальный файл против реального прод-GeoServer.
const LOCAL_TPL = readFileSync(new URL('../../repikurr/public/getbboxbyuser.xml', import.meta.url), 'utf-8')

function fieldsTypeName(year) {
  return year ? 'pikurr:fields' : 'pikurr:fields_latest'
}
function buildOgcFilter(year, groupCode) {
  const groupPart = `<ogc:PropertyIsLike wildCard="*" singleChar="." escape="!">` +
    `<ogc:PropertyName>nr_user</ogc:PropertyName>` +
    `<ogc:Literal>${groupCode}*</ogc:Literal></ogc:PropertyIsLike>`
  if (year) {
    return `<ogc:Filter><ogc:And>` +
      `<ogc:PropertyIsEqualTo><ogc:PropertyName>year</ogc:PropertyName>` +
      `<ogc:Literal>${year}</ogc:Literal></ogc:PropertyIsEqualTo>` +
      `${groupPart}</ogc:And></ogc:Filter>`
  }
  return `<ogc:Filter>${groupPart}</ogc:Filter>`
}

async function getBboxByUser(cqlFilter, year) {
  const xml = LOCAL_TPL.replace('{{TYPENAME}}', fieldsTypeName(year))
                 .replace('{{FILTER}}', buildOgcFilter(year, cqlFilter))
  const resp = await fetch(`${BASE}/geoserver/wps`, {
    method: 'POST', headers: { 'Content-Type': 'text/xml' }, body: xml,
  })
  const text = await resp.text()
  const m = text.match(/<ows:LowerCorner>([^<]+)<\/ows:LowerCorner>.*?<ows:UpperCorner>([^<]+)<\/ows:UpperCorner>/)
  if (!m) throw new Error('BBox parse error: ' + text.slice(0, 200))
  const [minx, miny] = m[1].split(' ').map(Number)
  const [maxx, maxy] = m[2].split(' ').map(Number)
  if (maxx < minx || maxy < miny) return null
  return { minx, miny, maxx, maxy }
}

const withData = await getBboxByUser('2212000055', null)
console.log('Реальный землепользователь, без года (fields_latest):', JSON.stringify(withData))
console.assert(withData !== null, 'ОШИБКА: реальные данные не должны давать null')

const noYear2024 = await getBboxByUser('2212000055', 2024)
console.log('Реальный землепользователь, year=2024 (не существует):', JSON.stringify(noYear2024))
console.assert(noYear2024 === null, 'ОШИБКА: несуществующий год должен давать null (было: ' + JSON.stringify(noYear2024) + ')')

console.log(noYear2024 === null && withData !== null ? '\nPASS: getBboxByUser() корректно различает пустой и непустой результат' : '\nFAIL')
