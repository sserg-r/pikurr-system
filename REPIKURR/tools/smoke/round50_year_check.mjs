// round50, блок A4: разовая диагностика (не постоянный тест) — витрина
// собрана локально (dist/, VITE_GEOSERVER_URL=прод), запущена локальным
// http-сервером, реальные WPS-запросы уходят на прод (CORS открыт,
// Access-Control-Allow-Origin: *, проверено фактом). year_district.json
// перехвачен и подменён (два года 2024/2025), чтобы проверить сценарий
// "смена года" — на самом проде сейчас только один год.
import { chromium } from 'playwright'

const BASE_URL = process.env.BASE_URL || 'http://localhost:5175'
const wpsBodies = []

const browser = await chromium.launch()
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', e => pageErrors.push(String(e)))

await page.route('**/static/year_district.json', route => {
  route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      years: [2024, 2025],
      districtsByYear: { '2024': ['2212'], '2025': ['2208', '2212', '2218', '2238', '2242', '2249', '2258'] },
      dataVersion: 'test',
    }),
  })
})

page.on('request', req => {
  if (req.method() === 'POST' && req.url().includes('/geoserver/wps')) {
    wpsBodies.push({ url: req.url(), body: req.postData() })
  }
})

await page.goto(BASE_URL, { waitUntil: 'networkidle' })
await page.waitForTimeout(1000)

function lastWps() {
  return wpsBodies[wpsBodies.length - 1]
}
function report(label) {
  const b = lastWps()
  const typeNameMatch = b?.body?.match(/typeName="([^"]+)"/)
  const yearMatch = b?.body?.match(/<ogc:PropertyName>year<\/ogc:PropertyName>\s*<ogc:Literal>(\d+)<\/ogc:Literal>/)
  console.log(`--- ${label} ---`)
  console.log('  typeName:', typeNameMatch?.[1], ' year в фильтре:', yearMatch?.[1] || 'ОТСУТСТВУЕТ')
}

// Сценарий 1: год 2025 -> область
const yearSelect = page.locator('.sidebar-section', { hasText: 'Год оценки' }).locator('select')
if (await yearSelect.count()) {
  await yearSelect.selectOption({ label: '2025' })
}
const oblastSelect = page.locator('.sidebar-section', { hasText: 'Область' }).locator('select')
await oblastSelect.selectOption({ index: 1 })
await page.waitForTimeout(1500)
report('Сценарий 1: год=2025, область выбрана')

// Сценарий 2: год 2025 -> район -> землепользователь
const districtSelect = page.locator('.sidebar-section', { hasText: 'Район' }).locator('select')
await districtSelect.selectOption({ index: 1 })
await page.waitForTimeout(1000)
const userSelect = page.locator('.sidebar-section', { hasText: 'Землепользователь' }).locator('select')
await userSelect.selectOption({ index: 1 })
await page.waitForTimeout(1500)
report('Сценарий 2: год=2025, район+землепользователь выбраны')

// Сценарий 3: смена года при выбранном районе (2025 -> 2024, которого
// на проде вообще нет — реальный пустой результат: AggregationResults=[],
// vec:Bounds — вырожденный охват). Блок B: карта не должна уехать,
// баннер "нет данных" должен появиться.
wpsBodies.length = 0
await yearSelect.selectOption({ label: '2024' })
await page.waitForTimeout(3000)
report('Сценарий 3: смена года 2025->2024 при выбранном районе/пользователе (useEffect)')

console.log('districtSelect value:', await districtSelect.inputValue().catch(() => 'н/д'))
console.log('userSelect value:', await userSelect.inputValue().catch(() => 'н/д'))
const bannerText = await page.locator('text=нет полей').first().textContent().catch(() => null)
console.log('Блок B: баннер "нет данных" виден:', !!bannerText, bannerText ? `("${bannerText.trim()}")` : '')

// JS-исключений на странице быть не должно (пустой результат — не ошибка)
console.log('Блок B: ошибок в консоли за время теста:', pageErrors.length, pageErrors)

await browser.close()
