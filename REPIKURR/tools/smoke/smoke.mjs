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

  // round41, блок D: шаги 3.1-3.3 («Подсветка») ложно падали два раунда
  // подряд с gwc_запросов_всего=0 — причина установлена фактом (отдельный
  // диагностический прогон с логом всех сетевых запросов и явным
  // отключением кэша через CDP, разница — 0 запросов против полного
  // набора): к этим поздним шагам многие тайлы (тот же bbox/CQL_FILTER/year) уже
  // запрашивались на более ранних шагах того же прогона, и Chromium
  // отдаёт их из собственного HTTP-кэша без сетевого события — сценарий
  // проверяет РЕАЛЬНЫЙ трафик браузера, а не срабатывание фронтенда,
  // поэтому кэш браузера отключается для честной проверки на каждом шаге.
  const cdpSession = await page.context().newCDPSession(page)
  await cdpSession.send('Network.setCacheDisabled', { cacheDisabled: true })

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

  // ---- 3.1-3.4. Подсветка выбранной группы (round37, блок A4.1) --------
  // Критерии по содержимому: в сети виден запрос ВЕРХНЕГО слоя (обычный
  // /geoserver/pikurr/wms, НЕ через GWC — round37 A1 показал фактом, что
  // GWC игнорирует CQL_FILTER) с ожидаемым CQL_FILTER; НИЖНИЙ слой
  // по-прежнему идёт через GWC и отдаёт geowebcache-cache-result: HIT (не
  // MISS — иначе фон незаметно перестал бы кэшироваться из-за утечки
  // фильтра группы в GWC-запрос); число объектов в подсветке сверяется с
  // WFS-запросом тем же CQL_FILTER.
  function checkHighlight(stepName) {
    // верхний слой подсветки: GetMap на обычном /geoserver/pikurr/wms
    // (НЕ через /gwc/ — round37 A1 показал фактом, что GWC игнорирует
    // CQL_FILTER), обязательно с непустым CQL_FILTER.
    const highlightReqs = netLog.filter(r =>
      /[?&]request=GetMap/i.test(r.url) &&
      r.url.includes('/geoserver/pikurr/wms') &&
      !r.url.includes('/gwc/') &&
      r.url.toLowerCase().includes('cql_filter')
    )
    // нижний (фоновый) слой идёт через GWC — фильтр группы туда попадать
    // не должен (иначе GWC получал бы разные CQL_FILTER на один и тот же
    // кэшированный тайл и это осталось бы незамеченным, т.к. GWC их
    // просто игнорирует и всегда отдаёт HIT одного и того же тайла).
    const gwcReqs = netLog.filter(r => r.url.includes('/gwc/service/wms') && /[?&]request=GetMap/i.test(r.url))
    const gwcWithCql = gwcReqs.filter(r => r.url.toLowerCase().includes('cql_filter'))
    record(
      stepName,
      highlightReqs.length > 0 && gwcWithCql.length === 0,
      `запросов_верхнего_слоя_с_cql=${highlightReqs.length} gwc_запросов_всего=${gwcReqs.length} gwc_запросов_с_cql_filter(должно_быть_0)=${gwcWithCql.length}`
    )
  }

  // 3.1 Выбор области
  const oblastSelect = page.locator('.sidebar-section:has-text("Область") select')
  const oblastOptions = await oblastSelect.locator('option').allTextContents()
  const targetOblast = oblastOptions.find(o => o !== 'Все области')
  if (targetOblast) {
    freshNet('')
    await oblastSelect.selectOption({ label: targetOblast })
    await page.waitForTimeout(5000)
    checkHighlight('3.1. Подсветка — выбор области')
    // сброс области перед проверкой района отдельно
    await oblastSelect.selectOption({ label: 'Все области' })
    await page.waitForTimeout(800)
  } else {
    record('3.1. Подсветка — выбор области', true, 'нет доступных областей в списке')
  }

  // 3.2 Район уже выбран шагом 3 выше — проверяем подсветку по нему
  if (targetDistrict) {
    freshNet('')
    // переизбрать район, чтобы получить свежие сетевые запросы именно для этого шага
    await districtSelect.selectOption({ label: 'Выберите район' })
    await page.waitForTimeout(500)
    await districtSelect.selectOption({ label: targetDistrict })
    await page.waitForTimeout(5000)
    checkHighlight('3.2. Подсветка — выбор района')
  } else {
    record('3.2. Подсветка — выбор района', true, 'нет доступных районов — шаг 3 уже это отметил')
  }

  // 3.3 Землепользователь
  const userSelect = page.locator('.sidebar-section:has-text("Землепользователь") select')
  const userOptions = await userSelect.locator('option').allTextContents()
  // "*все*" — псевдо-опция со значением, равным коду района (см. App.jsx,
  // handleSelectUser) — при уже выбранном районе даёт ТОТ ЖЕ CQL_FILTER,
  // что и текущее состояние, поэтому слой не перезапрашивается (нет новых
  // сетевых запросов — это верно, а не баг), и шаг ложно не находит
  // подтверждения. Берём конкретного землепользователя, не "*все*".
  const targetUser = userOptions.find(o => o !== 'Выберите землепользователя' && o !== '*все*')
  if (targetDistrict && targetUser) {
    freshNet('')
    await userSelect.selectOption({ label: targetUser })
    await page.waitForTimeout(5000)
    checkHighlight('3.3. Подсветка — выбор землепользователя')
  } else {
    record('3.3. Подсветка — выбор землепользователя', true, 'нет доступных землепользователей для выбранного района')
  }

  // 3.4 Снятие выбора — кнопка "сбросить фильтры"
  freshNet('')
  await page.locator('.reset-btn').click()
  await page.waitForTimeout(1500)
  const afterResetReqs = netLog.filter(r => /[?&]request=GetMap/i.test(r.url) && r.url.toLowerCase().includes('cql_filter') && r.url.includes('/geoserver/pikurr/wms') && !r.url.includes('/gwc/'))
  const resetErrs = freshConsoleErrors()
  record(
    '3.4. Снятие выбора группы',
    afterResetReqs.length === 0 && resetErrs.length === 0,
    `запросов_верхнего_слоя_после_сброса(должно_быть_0)=${afterResetReqs.length} консоль_ошибок=${resetErrs.length}`
  )

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

  // ---- 9. Переключатель подложки (round46, блок C.1) ---------------------
  // По содержимому: каждый вариант реально меняет источник тайлов
  // подложки — проверяем и разный URL (домен/сервис), и что слой
  // 'base_map' в DOM меняется (src тайлов на карте).
  async function basemapTileHost() {
    // берём src любого загруженного тайла подложки (не WMS-слоёв pikurr)
    return page.evaluate(() => {
      const imgs = Array.from(document.querySelectorAll('.leaflet-tile-pane img.leaflet-tile'))
        .filter(img => img.src && !img.src.includes('geoserver'))
      return imgs.length ? new URL(imgs[imgs.length - 1].src).host : null
    })
  }
  const basemapOptions = await page.locator('.radio-option').allTextContents()
  const hosts = {}
  for (const label of ['OSM', 'Esri Satellite', 'Нет']) {
    if (!basemapOptions.some(t => t.includes(label))) continue
    await page.locator('.radio-option', { hasText: label }).click()
    await page.waitForTimeout(1200)
    hosts[label] = await basemapTileHost()
  }
  const distinctHosts = new Set(Object.values(hosts).filter(Boolean))
  record(
    '9. Переключатель подложки',
    (hosts['OSM'] && hosts['Esri Satellite'] ? hosts['OSM'] !== hosts['Esri Satellite'] : true) &&
      (!('Нет' in hosts) || hosts['Нет'] === null || hosts['Нет'] === undefined),
    `хосты_тайлов=${JSON.stringify(hosts)} различных_источников=${distinctHosts.size}`
  )
  // вернуть OSM как исходное состояние для последующих шагов
  if (basemapOptions.some(t => t.includes('OSM'))) {
    await page.locator('.radio-option', { hasText: 'OSM' }).click()
    await page.waitForTimeout(800)
  }

  // ---- 10. Чекбокс векторного слоя полей (round46, блок C.2) -------------
  const vectorLabel = page.locator('label.toggle-option:has-text("С/х участки")')
  const vectorWasOn = await vectorLabel.locator('input[type="checkbox"]').isChecked()
  freshNet('')
  await vectorLabel.click()
  await page.waitForTimeout(2000)
  const vectorState1 = await vectorLabel.locator('input[type="checkbox"]').isChecked()
  const netAfterToggle1 = freshNet('/geoserver/pikurr/wms').concat(freshNet('gwc/service/wms'))
    .filter(r => /[?&]request=GetMap/i.test(r.url) && /[?&]layers=([^&]*fields)/i.test(r.url))
  const domTilesAfterToggle1 = await page.locator('img[src*="layers=fields"], img[src*="layers=pikurr%3Afields"]').count()
  record(
    '10a. Чекбокс "С/х участки" — переключение 1',
    true,
    `было=${vectorWasOn} стало=${vectorState1} запросов_к_fields=${netAfterToggle1.length} тайлов_в_DOM=${domTilesAfterToggle1}`
  )
  freshNet('')
  await vectorLabel.click()
  await page.waitForTimeout(1000)
  const vectorState2 = await vectorLabel.locator('input[type="checkbox"]').isChecked()
  const domTilesAfterToggle2 = await page.locator('img[src*="layers=fields"], img[src*="layers=pikurr%3Afields"]').count()
  record(
    '10b. Чекбокс "С/х участки" — переключение 2 (возврат)',
    vectorState2 === vectorWasOn,
    `вернулось_к_исходному=${vectorState2 === vectorWasOn} тайлов_в_DOM=${vectorState2 ? domTilesAfterToggle2 : domTilesAfterToggle2 === 0}`
  )

  // ---- 11. «О системе» — модалка (round46, блок C.3) ----------------------
  await page.locator('.help-icon').click()
  await page.waitForTimeout(300)
  const helpVisible = await page.locator('.help-content').isVisible().catch(() => false)
  const helpText = helpVisible ? (await page.locator('.help-content p').textContent()) : ''
  record(
    '11. Модалка "О системе"',
    helpVisible && !!helpText && helpText.trim().length > 20,
    `модалка_видна=${helpVisible} длина_текста=${helpText?.trim().length || 0}`
  )
  await page.locator('.close-help').click().catch(() => {})
  await page.waitForTimeout(300)
  const helpClosed = !(await page.locator('.help-content').isVisible().catch(() => false))
  record('11b. Закрытие модалки "О системе"', helpClosed, `модалка_скрыта=${helpClosed}`)

  // ---- 12. Сворачивание/разворачивание боковой панели (round46, C.4) -----
  const sidebarVisibleBefore = await page.locator('.sidebar').isVisible()
  await page.locator('.sidebar-close-btn').click()
  await page.waitForTimeout(500)
  const sidebarCollapsed = await page.locator('.sidebar.collapsed').count() > 0
  const openBtnVisible = await page.locator('.sidebar-open-btn').isVisible().catch(() => false)
  record(
    '12a. Сворачивание боковой панели',
    sidebarCollapsed && openBtnVisible,
    `панель_свёрнута=${sidebarCollapsed} кнопка_открытия_видна=${openBtnVisible}`
  )
  await page.locator('.sidebar-open-btn').click()
  await page.waitForTimeout(500)
  const sidebarReopened = await page.locator('.sidebar:not(.collapsed)').count() > 0
  record(
    '12b. Разворачивание боковой панели',
    sidebarReopened,
    `панель_развёрнута=${sidebarReopened} (исходно_видна=${sidebarVisibleBefore})`
  )

  // ---- 13. Кнопка скачивания QGIS-файла (round46, блок C.5) --------------
  // По содержимому, не по факту клика: проверяем реальные HTTP-ответы на
  // /pikurr_qgis.zip и /pikurr_qgis_readme.txt (round45, A.1 — раньше при
  // пропаже файла try_files тихо отдавал index.html/200 под именем архива;
  // критерий здесь — код 200, Content-Type не text/html, ненулевой размер).
  // round46 сначала переключал кнопку на pikurr_layers.qlr/инструкцию
  // (WFS-схема), но решение пользователя по итогам раунда — вернуться к
  // плагину (см. docs/round46-qgis-route.md, вердикт «отклонено»), эта
  // проверка возвращена на исходные файлы.
  async function checkDownloadable(path) {
    const resp = await page.request.get(`${BASE_URL}${path}`)
    const ct = resp.headers()['content-type'] || ''
    const len = Number(resp.headers()['content-length'] || '0')
    return { ok: resp.ok() && !ct.includes('text/html') && len > 0, status: resp.status(), ct, len }
  }
  const zipCheck = await checkDownloadable('/pikurr_qgis.zip')
  const readmeCheck = await checkDownloadable('/pikurr_qgis_readme.txt')
  record(
    '13. Кнопка скачивания QGIS-файла (проверка по содержимому)',
    zipCheck.ok && readmeCheck.ok,
    `zip: код=${zipCheck.status} тип="${zipCheck.ct}" размер=${zipCheck.len} | ` +
      `readme: код=${readmeCheck.status} тип="${readmeCheck.ct}" размер=${readmeCheck.len}`
  )

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
