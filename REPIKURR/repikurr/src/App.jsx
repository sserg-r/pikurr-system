import { useEffect, useState } from 'react'
import './App.css'
import 'leaflet/dist/leaflet.css'
import Sidebar from './components/Sidebar'
import MapView from './components/MapView'
import WmsLegend from './components/WmsLegend'
import { getBboxByUser, getStatsByUser, getAllUsers, loadYearDistrictData, getFeatureCount } from './services/geoserver'
import { fieldsTypeName } from './services/fieldsQuery'
import { FiMenu } from 'react-icons/fi'

function App() {
  const [baseLayer, setBaseLayer] = useState('osm')
  const [bbox, setBbox] = useState(null)
  const [stats, setStats] = useState(null)
  const [usersByDistrict, setUsersByDistrict] = useState({})
  const [selectedUser, setSelectedUser] = useState('')
  const [selectedDistrict, setSelectedDistrict] = useState('')
  // round37, блок A2.1: третий уровень выбора — область (2-значный префикс
  // nr_user, тот же смысл, что и у района/землепользователя — LIKE-префикс
  // кода, см. handleSelectOblast).
  const [selectedOblast, setSelectedOblast] = useState('')
  // round37, блок A2.6: true, если у активной группы (область/район/
  // землепользователь) нет полей за текущий год — WFS resultType=hits
  // вернул 0 (см. эффект ниже). Показываем внятное сообщение вместо
  // пустой карты вместо того, чтобы молча зумить в никуда.
  const [groupEmpty, setGroupEmpty] = useState(false)
  const [showVectors, setShowVectors] = useState(true)
  const [showMosaic, setShowMosaic] = useState(false)
  const [availableYears, setAvailableYears] = useState([])
  const [selectedYear, setSelectedYear] = useState(null)
  const [districtsByYear, setDistrictsByYear] = useState({})
  const [sidebarOpen, setSidebarOpen] = useState(true)
  // round32, блок C: версия данных последней доставки (стабильна между
  // доставками) — заменяет случайный cache-buster на фронтенде.
  const [dataVersion, setDataVersion] = useState(null)
  // round33, блок C.1: раньше сбой этого запроса тонул в console.error —
  // пользователь видел карту без списка годов/районов и не понимал,
  // сломано что-то или так и должно быть. Явный баннер + повтор.
  const [yearDistrictError, setYearDistrictError] = useState(false)

  async function handleZoomTo(nrUser) {
    try {
      const b = await getBboxByUser(nrUser)
      setBbox(b)
    } catch (e) {
      console.error(e)
    }
  }

  async function handleFetchStats(nrUser) {
    try {
      const data = await getStatsByUser(nrUser)
      setStats(data)
    } catch (e) {
      console.error(e)
    }
  }
  async function loadUsers() {
    try {
      const fc = await getAllUsers()
      const grouped = {}
      const features = fc?.features || []
      for (const f of features) {
        const rn = f?.properties?.rn
        const usname = f?.properties?.usname
        const usern_co = f?.properties?.usern_co
        if (!rn || !usern_co) continue
        if (!grouped[rn]) grouped[rn] = []
        grouped[rn].push({ key: usern_co, label: usname || usern_co, value: usern_co })
      }
      Object.keys(grouped).forEach(k => grouped[k].sort((a,b)=>a.label.localeCompare(b.label,'ru')))

      Object.keys(grouped).forEach(rn => {
        grouped[rn].unshift({ key: `all_${rn}`, label: "*все*", value: rn });
      });
      // console.log(grouped);


      setUsersByDistrict(grouped)
    } catch (e) {
      console.error(e)
    }
  }

  // автозагрузка пользователей при старте
  if (!Object.keys(usersByDistrict).length) {
    loadUsers()
  }

  // автозагрузка доступных годов и маппинга район→год
  //
  // round29, блок C: раньше здесь сразу после загрузки списка годов
  // вызывался setSelectedYear(<последний год>) — а selectedYear=null
  // уже означает "последний год" (см. MapView.jsx: vectorLayer =
  // selectedYear ? 'pikurr:fields' : 'pikurr:fields_latest', и
  // effectiveYear = selectedYear ?? maxYear). Установка selectedYear
  // в КОНКРЕТНЫЙ год сразу после монтирования не меняла смысл (тот же
  // последний год), но меняла КЛЮЧ WMSTileLayer в MapView.jsx — React
  // размонтировал только что смонтированный слой fields_latest и
  // монтировал fields, а уже отправленные HTTP-запросы fields_latest
  // не отменялись Leaflet'ом и долетали до сервера вхолостую (round28,
  // A3/рычаг 7: 24 тайла на загрузку вместо 12, половина — впустую).
  // Не устанавливаем selectedYear автоматически — null и так рендерит
  // корректный (последний) год; explicit-выбор пользователем остаётся
  // (селектор года в Sidebar, handleReset ниже).
  if (!availableYears.length && !yearDistrictError) {
    loadYearDistrictData()
      .then(({ years, districtsByYear: dby, dataVersion: dv }) => {
        setAvailableYears(years)
        setDistrictsByYear(dby)
        setDataVersion(dv)
      })
      .catch(e => {
        console.error(e)
        setYearDistrictError(true)
      })
  }

  // Сброс всех фильтров
  function handleReset() {
    setSelectedUser('')
    setSelectedDistrict('')
    setSelectedOblast('')
    setBbox(null)
    setStats(null)
    // round29, блок C: null, не конкретный последний год — та же
    // причина, что и в автозагрузке выше (null уже значит "последний
    // год", явное значение только лишний раз переключает слой).
    setSelectedYear(null)
  }

  // round37, блок A2.1: выбор области — верхний уровень группировки, тот
  // же смысл LIKE-префикса, что у района ('2208') и землепользователя
  // (полный код) — nr_user начинается с 2-значного кода области (см.
  // constants.js: oblasts), поэтому `nr_user LIKE '<oblast>%'` работает
  // без изменений в шаблонах WPS (getbboxbyuser.xml подставляет
  // {{CQL_FILTER}} как обычный префикс, не как готовое CQL-выражение —
  // проверено фактом, round37 A1).
  async function handleSelectOblast(oblastId) {
    setSelectedOblast(oblastId)
    setSelectedDistrict('')
    setSelectedUser('')
    try {
      if (oblastId) {
        const b = await getBboxByUser(oblastId)
        setBbox(b)
        const data = await getStatsByUser(oblastId)
        setStats(data)
      } else {
        setBbox(null)
        setStats(null)
      }
    } catch (e) { console.error(e) }
  }

  // автодействия при выборе пользователя
  async function handleSelectUser(userCode, districtId) {
    setSelectedUser(userCode)
    setSelectedDistrict(districtId !== undefined ? districtId : selectedDistrict)
    const isAll = userCode === '*'
    // bbox & stats
    const effectiveCode = isAll ? (districtId || selectedDistrict) : userCode
    // round37, блок A2.1: если район/землепользователь сброшены (пусто), а
    // область всё ещё выбрана — падаем обратно на область, а не оставляем
    // карту в устаревшем виде (без этого снятие района "терялось" бы, пока
    // не снята и область явно).
    const zoomCode = effectiveCode || districtId || selectedOblast  // зум к району даже если юзер не выбран

    try {
      if (zoomCode) {
        // round49, блок B: год передаётся так же, как для слоя карты
        // (fieldsTypeName/vectorTypeName ниже) — раньше границы всегда
        // считались по pikurr:fields без условия года.
        const b = await getBboxByUser(zoomCode, selectedYear)
        setBbox(b)
      } else {
        setBbox(null)
      }
    } catch (e) { console.error(e) }

    try {
      const statsCode = effectiveCode || selectedOblast
      if (statsCode) {
        const data = await getStatsByUser(statsCode, selectedYear)
        setStats(data)
      } else {
        setStats(null)
      }
    } catch (e) { console.error(e) }
  }
  // round37, блок A2.1/A2.2: разделены год (фильтр фонового слоя — не
  // меняется при выборе группы, сохраняет попадания GWC) и группа
  // (область/район/землепользователь — фильтр верхнего слоя-подсветки,
  // приоритет — самый конкретный уровень из выбранных). `highlightCqlExpr`
  // (год+группа) — то же выражение, что и раньше использовалось для
  // всплывающей карточки (FeatureInfo), поведение клика не меняется.
  const yearCqlExpr = selectedYear ? `year = ${selectedYear}` : undefined
  const groupCqlExpr = selectedUser
    ? `nr_user LIKE '${selectedUser}%'`
    : selectedDistrict
      ? `nr_user LIKE '${selectedDistrict}%'`
      : selectedOblast
        ? `nr_user LIKE '${selectedOblast}%'`
        : undefined
  const highlightCqlExpr = [yearCqlExpr, groupCqlExpr].filter(Boolean).join(' AND ') || undefined
  const vectorTypeName = fieldsTypeName(selectedYear)

  // round37, блок A2.6: если в выбранной группе нет полей за текущий год —
  // явное сообщение вместо пустой карты. Пересчитывается при смене группы
  // или года; сброс группы снимает баннер.
  useEffect(() => {
    let cancelled = false
    if (!groupCqlExpr) {
      setGroupEmpty(false)
      return
    }
    getFeatureCount(vectorTypeName, groupCqlExpr)
      .then(n => { if (!cancelled) setGroupEmpty(n === 0) })
      .catch(e => { console.error(e); if (!cancelled) setGroupEmpty(false) })
    return () => { cancelled = true }
  }, [groupCqlExpr, vectorTypeName])

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden' }}>
      <Sidebar
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onReset={handleReset}
        baseLayer={baseLayer}
        setBaseLayer={setBaseLayer}
        usersByDistrict={usersByDistrict}
        onSelectUser={handleSelectUser}
        selectedOblast={selectedOblast}
        onSelectOblast={handleSelectOblast}
        showVectors={showVectors}
        setShowVectors={setShowVectors}
        showMosaic={showMosaic}
        setShowMosaic={setShowMosaic}
        statsData={stats}
        availableYears={availableYears}
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        districtsByYear={districtsByYear}
      />
      <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
        {yearDistrictError && (
          <div style={{
            position: 'absolute', top: 8, left: '50%', transform: 'translateX(-50%)',
            zIndex: 1000, background: '#fff3cd', border: '1px solid #ffcc00',
            borderRadius: 6, padding: '8px 16px', display: 'flex', alignItems: 'center',
            gap: 12, boxShadow: '0 2px 6px rgba(0,0,0,0.15)', fontSize: 14,
          }}>
            <span>Не удалось загрузить список годов и районов. Карта продолжает работать.</span>
            <button
              onClick={() => setYearDistrictError(false)}
              style={{ cursor: 'pointer', padding: '4px 10px', borderRadius: 4, border: '1px solid #ccc' }}
            >
              Повторить
            </button>
          </div>
        )}
        {/* Кнопка открытия панели (burger) — видна только когда панель скрыта */}
        {!sidebarOpen && (
          <button
            className="sidebar-open-btn"
            onClick={() => setSidebarOpen(true)}
            title="Открыть панель"
          >
            <FiMenu size={20} />
          </button>
        )}
        {groupEmpty && (
          <div style={{
            position: 'absolute', top: 8, left: '50%', transform: 'translateX(-50%)',
            zIndex: 1000, background: '#fff3cd', border: '1px solid #ffcc00',
            borderRadius: 6, padding: '8px 16px', boxShadow: '0 2px 6px rgba(0,0,0,0.15)', fontSize: 14,
          }}>
            В выбранной группе нет полей{selectedYear ? ` за ${selectedYear} год` : ''}.
          </div>
        )}
        <MapView
          baseLayer={baseLayer}
          bbox={bbox}
          maxYear={availableYears.length > 0 ? availableYears[availableYears.length - 1] : null}
          cqlExpr={yearCqlExpr}
          highlightCqlExpr={groupCqlExpr ? highlightCqlExpr : undefined}
          showVectors={showVectors}
          showMosaic={showMosaic}
          selectedYear={selectedYear}
          dataVersion={dataVersion}
        />
        {showMosaic && (
          <div style={{ position: 'absolute', right: 0, bottom: 32 }}>
            <WmsLegend layer="image_assessment" title="AI оценка" floating />
          </div>
        )}
      </div>
    </div>
  )
}

export default App
