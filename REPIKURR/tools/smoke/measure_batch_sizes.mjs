// round40, блок A1/A2: точный подсчёт размера пачки тайловых запросов на
// реальном фронтенде по каждому типу действия из модели нагрузки
// capacity_k6.js — не приближение (round28 A3 устарело: до подсветки
// группы round37 и до зачистки 2024 round39), а свежий факт с работающей
// витрины, тем же Playwright, что smoke.mjs (claude-in-chrome в этой
// сессии не подключён — см. docs/round40-capacity.md).
//
// Запуск: BASE_URL=https://geobotany.of.by node measure_batch_sizes.mjs

import { chromium } from 'playwright'

const BASE_URL = process.env.BASE_URL || 'https://geobotany.of.by'
const HEADLESS = process.env.HEADLESS !== 'false'

async function main() {
  const browser = await chromium.launch({ headless: HEADLESS })
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })

  let netLog = []
  page.on('response', resp => {
    const url = resp.url()
    if (/[?&]request=GetMap/i.test(url) && (url.includes('/gwc/service/wms') || url.includes('/geoserver/pikurr/wms'))) {
      netLog.push({ url, status: resp.status() })
    }
  })
  function drain() {
    const n = netLog.length
    netLog = []
    return n
  }

  const results = {}

  // 1. Загрузка страницы
  await page.goto(BASE_URL, { waitUntil: 'networkidle' })
  await page.waitForTimeout(500)
  results.page_load = drain()

  // 2. Сдвиг карты (pan) — на уже загруженной странице, без выбора года/района
  const mapBox = await page.locator('.leaflet-container').boundingBox()
  if (mapBox) {
    const cx = mapBox.x + mapBox.width / 2
    const cy = mapBox.y + mapBox.height / 2
    drain()
    await page.mouse.move(cx, cy)
    await page.mouse.down()
    await page.mouse.move(cx - 250, cy - 150, { steps: 15 })
    await page.mouse.up()
    await page.waitForTimeout(1500)
    results.pan = drain()
  } else {
    results.pan = 'нет .leaflet-container'
  }

  // 3. Включение слоя AI-оценки (растр)
  const mosaicLabel = page.locator('label.toggle-option:has-text("AI оценка")')
  if (await mosaicLabel.count() > 0) {
    drain()
    await mosaicLabel.click()
    await page.waitForTimeout(3000)
    results.raster_toggle = drain()
    await mosaicLabel.click() // выключить обратно, не оставлять состояние
    await page.waitForTimeout(1000)
  } else {
    results.raster_toggle = 'переключатель "AI оценка" не найден'
  }

  // 4. Клик по полю (GetFeatureInfo — 1 запрос, не тайл, отдельно от netLog фильтра выше)
  let clickReqs = 0
  const onResp = resp => {
    if (/[?&]request=GetFeatureInfo/i.test(resp.url())) clickReqs++
  }
  page.on('response', onResp)
  if (mapBox) {
    const cx = mapBox.x + mapBox.width / 2
    const cy = mapBox.y + mapBox.height / 2
    const offsets = [[0, 0], [40, 0], [-40, 0], [0, 40], [0, -40], [80, 40], [-80, -40]]
    for (const [dx, dy] of offsets) {
      await page.mouse.click(cx + dx, cy + dy)
      await page.waitForTimeout(600)
      if (clickReqs > 0) break
    }
  }
  page.off('response', onResp)
  results.click_getfeatureinfo_requests = clickReqs

  console.log(JSON.stringify(results, null, 2))
  await browser.close()
}

main().catch(e => { console.error(e); process.exit(1) })
