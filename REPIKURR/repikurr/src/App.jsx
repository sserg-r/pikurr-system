import { useState } from 'react'
import './App.css'
import 'leaflet/dist/leaflet.css'
import Sidebar from './components/Sidebar'
import MapView from './components/MapView'
import WmsLegend from './components/WmsLegend'
import { getBboxByUser, getStatsByUser, getAllUsers, loadYearDistrictData } from './services/geoserver'
import { FiMenu } from 'react-icons/fi'

function App() {
  const [baseLayer, setBaseLayer] = useState('osm')
  const [bbox, setBbox] = useState(null)
  const [stats, setStats] = useState(null)
  const [usersByDistrict, setUsersByDistrict] = useState({})
  const [selectedUser, setSelectedUser] = useState('')
  const [selectedDistrict, setSelectedDistrict] = useState('')
  const [showVectors, setShowVectors] = useState(true)
  const [showMosaic, setShowMosaic] = useState(false)
  const [availableYears, setAvailableYears] = useState([])
  const [selectedYear, setSelectedYear] = useState(null)
  const [districtsByYear, setDistrictsByYear] = useState({})
  const [sidebarOpen, setSidebarOpen] = useState(true)

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
  if (!availableYears.length) {
    loadYearDistrictData()
      .then(({ years, districtsByYear: dby }) => {
        setAvailableYears(years)
        setDistrictsByYear(dby)
        if (years.length > 0) setSelectedYear(years[years.length - 1])
      })
      .catch(e => console.error(e))
  }

  // Сброс всех фильтров
  function handleReset() {
    setSelectedUser('')
    setSelectedDistrict('')
    setBbox(null)
    setStats(null)
    if (availableYears.length > 0)
      setSelectedYear(availableYears[availableYears.length - 1])
  }

  // автодействия при выборе пользователя
  async function handleSelectUser(userCode, districtId) {
    setSelectedUser(userCode)
    setSelectedDistrict(districtId !== undefined ? districtId : selectedDistrict)
    const isAll = userCode === '*'
    const cql = isAll && (districtId || selectedDistrict)
      ? `nr_user LIKE '${(districtId || selectedDistrict)}%'`
      : userCode
        ? `nr_user LIKE '${userCode}%'`
        : ''
    // bbox & stats
    const effectiveCode = isAll ? (districtId || selectedDistrict) : userCode
    const zoomCode = effectiveCode || districtId  // зум к району даже если юзер не выбран

    try {
      if (zoomCode) {
        const b = await getBboxByUser(zoomCode)
        setBbox(b)
      } else {
        setBbox(null)
      }
    } catch (e) { console.error(e) }

    try {
      if (effectiveCode) {
        const data = await getStatsByUser(effectiveCode)
        setStats(data)
      } else {
        setStats(null)
      }
    } catch (e) { console.error(e) }
  }
  const cqlExpr = (() => {
    const parts = []
    if (selectedYear) parts.push(`year = ${selectedYear}`)
    if (selectedUser) parts.push(`nr_user LIKE '${selectedUser}%'`)
    else if (selectedDistrict) parts.push(`nr_user LIKE '${selectedDistrict}%'`)
    return parts.length ? parts.join(' AND ') : undefined
  })()

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
        <MapView
          baseLayer={baseLayer}
          bbox={bbox}
          maxYear={availableYears.length > 0 ? availableYears[availableYears.length - 1] : null}
          cqlExpr={cqlExpr}
          showVectors={showVectors}
          showMosaic={showMosaic}
          selectedYear={selectedYear}
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
