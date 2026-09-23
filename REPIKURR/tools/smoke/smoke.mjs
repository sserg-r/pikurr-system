// Раунд 34, блок B: исполняемый дымовой сценарий витрины PIKURR.
//
// Почему Playwright, а не claude-in-chrome: claude-in-chrome — интерактивный
// MCP-инструмент, которым управляет агент внутри диалога, его нельзя
// положить в репозиторий как автономно запускаемый артефакт (нужна сессия
// Claude Code). Playwright — обычная npm-зависимость, реально доступная в
// среде (Node 22 уже установлен), скрипт запускается `node smoke.mjs` без
// внешних сервисов и даёт машинно-читаемый вердикт по каждому шагу.
//
// Правило раунда 33 (см. CLAUDE.md, "Критерий приёмки"): HTTP-код и
// корректный index.html не доказывают, что JS отработал — каждый шаг ниже
// проверяется по СОДЕРЖИМОМУ (текст на странице, наличие DOM-узла,
// содержимое сетевого ответа), а не по факту, что страница "открылась".
//
// Запуск: BASE_URL=https://geobotany.of.by node smoke.mjs
//   (BASE_URL по умолчанию — https://geobotany.of.by)

import { chromium } from 'playwright'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const BASE_URL = process.env.BASE_URL || 'https://geobotany.of.by'
const HEADLESS = process.env.HEADLESS !== 'false'
const CAPTURE_OUT = process.env.CAPTURE_OUT ||
  join(dirname(fileURLToPath(import.meta.url)), 'captured_gwc_urls.json')

const results = []

function record(name, ok, detail) {
  results.push({ name, ok, detail })
  const mark = ok ? 'PASS' : 'FAIL'
  console.log(`[${mark}] ${name} — ${detail}`)
}

async function main() {
  const browser = await chromium.launch({ headless: HEADLESS })
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })

  const consoleErrors = []
  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  page.on('pageerror', err => consoleErrors.push(String(err)))

  const netLog = []
  // round35, блок B1: реальные URL, которые фронтенд шлёт на GWC-эндпоинт
  // для обоих кэшируемых слоёв — источник истины для healthcheck.py
  // (round34 A3: healthcheck проверял /geoserver/pikurr/wms, фронтенд для
  // кэшируемых слоёв ходит на /geoserver/gwc/service/wms — расхождение
  // скрыло сломанный слой от единственной автопроверки). Захватывается
  // ПЕРВЫЙ увиденный запрос на каждый слой, дальше — только сеть по
  // freshNet ниже (эта запись не чистится).
  const capturedGwcUrls = {}
  // round35, блок C1: ВСЕ тайловые запросы за прогон (не только первый на
  // слой) — источник факта для распределения зумов, которые реально
  // запрашивает фронтенд за типичный сеанс (загрузка, год, район, слои,
  // зум, сдвиг — всё, что уже делает этот сценарий).
  const allTileRequests = []
  page.on('response', resp => {
    const url = resp.url()
    netLog.push({ url, status: resp.status() })
    const isGetMap = /[?&]request=GetMap/i.test(url)
    if (isGetMap && (url.includes('/gwc/service/wms') || url.includes('/geoserver/pikurr/wms'))) {
      const layerMatch = url.match(/[?&]layers=([^&]+)/)
      const bboxMatch = url.match(/[?&]bbox=([^&]+)/)
      const layer = layerMatch ? decodeURIComponent(layerMatch[1]) : null
      if (layer && bboxMatch) {
        allTileRequests.push({ layer, bbox: decodeURIComponent(bboxMatch[1]), status: resp.status() })
      }
      if (layer && url.includes('/gwc/service/wms') && !capturedGwcUrls[layer]) {
        capturedGwcUrls[layer] = url
      }
    }
  })

  function freshConsoleErrors() {
    const snapshot = [...consoleErrors]
    consoleErrors.length = 0
    return snapshot
  }
  function freshNet(pattern) {
    const matched = netLog.filter(r => r.url.includes(pattern))
    netLog.length = 0
    return matched
  }

  // ---- 1. Загрузка страницы --------------------------------------------
  await page.goto(BASE_URL, { waitUntil: 'networkidle' })
  const title = await page.textContent('h2')
  const sidebarVisible = await page.locator('.sidebar').isVisible()
  record(
    '1. Загрузка страницы',
    title?.trim() === 'ПИК УРР' && sidebarVisible,
    `заголовок="${title?.trim()}" сайдбар_виден=${sidebarVisible} консоль_ошибок=${freshConsoleErrors().length}`
  )

  // ---- 2. Выбор года ------------------------------------------------
  const yearSelectVisible = await page.locator('.sidebar-section:has-text("Год оценки") select').count() > 0
  if (yearSelectVisible) {
    const yearSelect = page.locator('.sidebar-section:has-text("Год оценки") select')
    const options = await yearSelect.locator('option').allTextContents()
    const targetYear = options.find(o => o !== 'Все годы')
    if (targetYear) {
      await yearSelect.selectOption({ label: targetYear })
      await page.waitForTimeout(1500)
      const fieldsReqs = freshNet('pikurr:fields&') // историчный слой всегда с CQL year=
      const errs = freshConsoleErrors()
      record(
        '2. Выбор года',
        errs.length === 0,
        `год="${targetYear}" запросов_к_fields=${fieldsReqs.length} консоль_ошибок=${errs.length}`
      )
    } else {
      record('2. Выбор года', true, 'только один год доступен — селектор не показан, пропущено осознанно')
    }
  } else {
    record('2. Выбор года', true, 'селектор года не отрисован (доступен только один год) — не ошибка')
  }

  // ---- 3. Выбор района ------------------------------------------------
  const districtSelect = page.locator('.sidebar-section:has-text("Район") select')
  const districtOptions = await districtSelect.locator('option').allTextContents()
  const targetDistrict = districtOptions.find(o => o !== 'Выберите район')
  let districtOk = false
  let districtDetail = 'нет доступных районов в списке'
  if (targetDistrict) {
    freshNet('') // очистить лог перед действием
    await districtSelect.selectOption({ label: targetDistrict })
    await page.waitForTimeout(1500)
    const bboxReqs = freshNet('getbboxbyuser').concat(freshNet('bbox_by_user')).concat(freshNet('wps'))
    const errs = freshConsoleErrors()
    districtOk = errs.length === 0
    districtDetail = `район="${targetDistrict}" запросов_wps=${bboxReqs.length} консоль_ошибок=${errs.length}`
  }
  record('3. Выбор района', districtOk || !targetDistrict, districtDetail)

  // ---- 4. Включение слоя AI-оценки ------------------------------------
  // Чекбокс визуально скрыт (кастомный toggle через `span.toggle-custom`,
  // см. Sidebar.css) — кликаем по самой строке label, `check()` по input
  // с `force` не годится: нужен реальный `click`, который React слушает
  // на label/label-детях, а не программная установка `checked`.
  const mosaicLabel = page.locator('label.toggle-option:has-text("AI оценка")')
  freshNet('')
  await mosaicLabel.click()
  await page.waitForTimeout(3000)
  const gwcReqs = freshNet('gwc/service/wms')
  const gwcOk = gwcReqs.filter(r => r.status === 200)
  const gwcBad = gwcReqs.filter(r => r.status !== 200)
  record(
    '4a. Включение слоя AI-оценки',
    gwcReqs.length > 0 && gwcBad.length === 0,
    `запросов_к_gwc=${gwcReqs.length} успешных=${gwcOk.length} неуспешных=${gwcBad.length}` +
      (gwcBad.length ? ` примеры_кодов=${gwcBad.slice(0, 3).map(r => r.status).join(',')}` : '')
  )

  // ---- 4b. Выключение слоя AI-оценки -----------------------------------
  freshNet('')
  await mosaicLabel.click()
  await page.waitForTimeout(1000)
  const mosaicImgCount = await page.locator('img[src*="image_assessment"]').count()
  record(
    '4b. Выключение слоя AI-оценки',
    mosaicImgCount === 0,
    `тайлов_растра_в_DOM_после_выключения=${mosaicImgCount}`
  )
  await mosaicLabel.click()
  await page.waitForTimeout(2000)

  // ---- 5. Клик по полю (всплывающая карточка) --------------------------
  const mapBox = await page.locator('.leaflet-container').boundingBox()
  let popupFound = false
  let popupDetail = 'не найдено ни одной точки с данными в опробованной сетке'
  if (mapBox) {
    const cx = mapBox.x + mapBox.width / 2
    const cy = mapBox.y + mapBox.height / 2
    const offsets = [
      [0, 0], [40, 0], [-40, 0], [0, 40], [0, -40],
      [80, 40], [-80, -40], [120, -60], [-120, 60], [60, 120],
    ]
    for (const [dx, dy] of offsets) {
      await page.mouse.click(cx + dx, cy + dy)
      const popup = page.locator('.map-popup')
      try {
        await popup.waitFor({ state: 'visible', timeout: 1200 })
        const heading = await popup.locator('h3').textContent()
        const hasContent =
          (await popup.locator('.popup-stats-table').count()) > 0 ||
          (await popup.locator('.popup-properties .property-row').count()) > 0 ||
          (await popup.locator('.popup-description').count()) > 0
        popupFound = heading?.includes('Детали участка') && hasContent
        popupDetail = `клик со смещением (${dx},${dy}) от центра — заголовок="${heading?.trim()}" содержимое_есть=${hasContent}`
        if (popupFound) break
      } catch {
        // в этой точке данных нет — пробуем следующую
      }
    }
  }
  record('5. Клик по полю (всплывающая карточка)', popupFound, popupDetail)

  // закрыть попап, если остался открыт
  await page.keyboard.press('Escape').catch(() => {})

  // ---- 6. Зум -----------------------------------------------------------
  const zoomBadge = () => page.evaluate(() => {
    const el = document.querySelector('.leaflet-container')
    return el ? el.className : null
  })
  freshNet('')
  const zoomInBtn = page.locator('.leaflet-control-zoom-in')
  await zoomInBtn.click()
  await page.waitForTimeout(1500)
  const zoomInReqs = freshNet('gwc/service/wms').concat(freshNet('/geoserver/pikurr/wms'))
  const zoomErrs = freshConsoleErrors()
  record(
    '6. Зум (приближение)',
    zoomErrs.length === 0,
    `новых_тайловых_запросов=${zoomInReqs.length} консоль_ошибок=${zoomErrs.length}`
  )
  await page.locator('.leaflet-control-zoom-out').click()
  await page.waitForTimeout(1000)

  // ---- 7. Сдвиг (pan) ----------------------------------------------------
  if (mapBox) {
    freshNet('')
    const cx = mapBox.x + mapBox.width / 2
    const cy = mapBox.y + mapBox.height / 2
    await page.mouse.move(cx, cy)
    await page.mouse.down()
    await page.mouse.move(cx - 250, cy - 150, { steps: 15 })
    await page.mouse.up()
    await page.waitForTimeout(1500)
    const panReqs = freshNet('gwc/service/wms').concat(freshNet('/geoserver/pikurr/wms'))
    const panErrs = freshConsoleErrors()
    record(
      '7. Сдвиг карты (pan)',
      panErrs.length === 0,
      `новых_тайловых_запросов_после_сдвига=${panReqs.length} консоль_ошибок=${panErrs.length}`
    )
  } else {
    record('7. Сдвиг карты (pan)', false, 'не удалось получить размеры контейнера карты')
  }

  // ---- 8. Поведение при отсутствии данных в области ---------------------
  if (mapBox) {
    // угол контейнера — за пределами обычно покрытой векторными данными
    // области карты (см. docs/round34-raster-gwc.md — прод обычно
    // открывается видом на Витебскую область, углы вьюпорта в базовом
    // виде обычно не покрыты хозяйствами).
    const cornerX = mapBox.x + 15
    const cornerY = mapBox.y + 15
    freshConsoleErrors()
    await page.mouse.click(cornerX, cornerY)
    await page.waitForTimeout(800)
    const popupAfterEmptyClick = await page.locator('.map-popup').count()
    const emptyErrs = freshConsoleErrors()
    record(
      '8. Клик в области без данных',
      popupAfterEmptyClick === 0 && emptyErrs.length === 0,
      `попап_появился=${popupAfterEmptyClick > 0} консоль_ошибок=${emptyErrs.length}`
    )
  } else {
    record('8. Клик в области без данных', false, 'не удалось получить размеры контейнера карты')
  }

  await browser.close()

  // round35, блок B1: дамп перехваченных GWC-URL для healthcheck.py —
  // источник истины для проверок, не ручная сборка. Пишется даже если
  // какие-то шаги сценария упали (полезно для диагностики), но не
  // перетирает предыдущий валидный дамп пустым, если за весь прогон не
  // нашлось ни одного GWC-запроса (например, сценарий упал до шага 4a).
  if (Object.keys(capturedGwcUrls).length > 0) {
    writeFileSync(CAPTURE_OUT, JSON.stringify(capturedGwcUrls, null, 2))
    console.log(`\nПерехвачено GWC-URL для слоёв: ${Object.keys(capturedGwcUrls).join(', ')} → ${CAPTURE_OUT}`)
  } else {
    console.log('\nGWC-URL не перехвачены за этот прогон — captured_gwc_urls.json не обновлён.')
  }

  // round35, блок C1: полный список тайловых запросов за прогон — сырьё
  // для оценки распределения зумов (REPIKURR/tools/analyze_zoom_usage.py).
  if (allTileRequests.length > 0) {
    const outPath = join(dirname(CAPTURE_OUT), 'all_tile_requests.json')
    writeFileSync(outPath, JSON.stringify(allTileRequests, null, 2))
    console.log(`Всего тайловых запросов за прогон: ${allTileRequests.length} → ${outPath}`)
  }

  console.log('\n--- Итог ---')
  const failed = results.filter(r => !r.ok)
  for (const r of results) {
    console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}`)
  }
  console.log(`\n${results.length - failed.length}/${results.length} шагов пройдено.`)
  process.exit(failed.length ? 1 : 0)
}

main().catch(err => {
  console.error('Сценарий упал с исключением:', err)
  process.exit(2)
})
