import { useEffect, useMemo, useState } from 'react'
import { distr, oblasts } from '../constants'
import StatsTable from './StatsTable'
import WmsLegend from './WmsLegend'

export default function Sidebar({ baseLayer, setBaseLayer, usersByDistrict, onSelectUser, showVectors, setShowVectors, showMosaic, setShowMosaic, statsData, availableYears, selectedYear, setSelectedYear, districtsByYear }) {
  const [oblastId, setOblastId] = useState('')
  const [districtId, setDistrictId] = useState('')
  const [nrUser, setNrUser] = useState('')

  // When year changes, reset district/oblast if they no longer have data for the new year
  useEffect(() => {
    const yearSet = selectedYear ? districtsByYear?.[selectedYear] : null
    if (!yearSet) return
    if (districtId && !yearSet.has(districtId)) {
      setDistrictId('')
      setNrUser('')
      onSelectUser('', '')
    }
    if (oblastId && ![...yearSet].some(d => d.substring(0, 2) === oblastId)) {
      setOblastId('')
    }
  }, [selectedYear, districtsByYear])

  const filteredDistricts = useMemo(() => {
    const yearSet = selectedYear ? districtsByYear?.[selectedYear] : null
    return Object.entries(distr).filter(([id]) => {
      if (oblastId && id.substring(0, 2) !== oblastId) return false
      if (!(usersByDistrict[id] && usersByDistrict[id].length > 0)) return false
      if (yearSet && !yearSet.has(id)) return false
      return true
    })
  }, [oblastId, usersByDistrict, selectedYear, districtsByYear])

  const usersForDistrict = useMemo(() => usersByDistrict[districtId] || [], [usersByDistrict, districtId])

  const activeOblasts = useMemo(() => {
    const yearSet = selectedYear ? districtsByYear?.[selectedYear] : null
    const presentPrefixes = new Set(
      Object.keys(usersByDistrict)
        .filter(id => usersByDistrict[id]?.length > 0)
        .filter(id => !yearSet || yearSet.has(id))
        .map(id => id.substring(0, 2))
    )
    return Object.entries(oblasts).filter(([prefix]) => presentPrefixes.has(prefix))
  }, [usersByDistrict, selectedYear, districtsByYear])
  
  const downloadQGISFiles = () => {
    // Скачивание ZIP файла
    const zipLink = document.createElement('a');
    zipLink.href = '/pikurr_qgis.zip';
    zipLink.download = 'pikurr_qgis.zip';
    document.body.appendChild(zipLink);
    zipLink.click();
    document.body.removeChild(zipLink);
    
    // Скачивание README с задержкой
    setTimeout(() => {
      const txtLink = document.createElement('a');
      txtLink.href = '/pikurr_qgis_readme.txt';
      txtLink.download = 'pikurr_qgis_readme.txt';
      document.body.appendChild(txtLink);
      txtLink.click();
      document.body.removeChild(txtLink);
    }, 100);
  };

  return (
    <div style={{ width: '20%', padding: '8px 8px 8px 8px', borderRight: '2px solid #e5e7eb', overflowY: 'auto' }}>
      
      
      {/* Кнопка скачивания QGIS плагина */}
      <div style={{ marginBottom: 8 }}>
        <button
          onClick={downloadQGISFiles}
          style={{
            padding: '4px 8px',
            backgroundColor: '#f0f0f0',
            border: '1px solid #ccc',
            borderRadius: 4,
            cursor: 'pointer'
          }}
          title="плагин для просмотра данных в QGIS"
        >
          qgis plugin
        </button>
      </div>
      <h3 style={{ margin: '8px 0' }}>ПИК УРР</h3>
      <div style={{ width:'100%', marginBottom: 8}}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Базовые карты</div>
        <div style={{ lineHeight: 1.2 }}>
          <label style={{ display: 'block', marginBottom: 4 }}>
            <input type="radio" name="basemap" checked={baseLayer==='none'} onChange={()=>setBaseLayer('none')} /> нет
          </label>
          <label style={{ display: 'block', marginBottom: 4 }}>
            <input type="radio" name="basemap" checked={baseLayer==='osm'} onChange={()=>setBaseLayer('osm')} /> OSM
          </label>
          <label style={{ display: 'block', marginBottom: 4 }}>
            <input type="radio" name="basemap" checked={baseLayer==='esri'} onChange={()=>setBaseLayer('esri')} /> Esri Satellite
          </label>
        </div>
      </div>

      <div style={{ marginBottom: 8 }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Слои</div>
        <div style={{ lineHeight: 1.2 }}>
          <label style={{ display: 'block', marginBottom: 4 }}>
            <input type="checkbox" checked={showMosaic} onChange={(e)=>setShowMosaic(e.target.checked)} /> AI оценка
          </label>
        </div>
      </div>

      {availableYears && availableYears.length > 1 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Год оценки</div>
          <select style={{ width: '100%' }} value={selectedYear || ''} onChange={(e) => setSelectedYear(e.target.value ? Number(e.target.value) : null)}>
            <option value="">Все годы</option>
            {availableYears.map(y => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </div>
      )}

      <div style={{ marginBottom: 8 }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Область</div>
        <select style={{ width: '100%' }} value={oblastId} onChange={(e) => {
          const v = e.target.value
          setOblastId(v)
          setDistrictId('')
          setNrUser('')
          onSelectUser('', '')
        }}>
          <option value="">Все области</option>
          {activeOblasts.map(([prefix, name]) => (
            <option key={prefix} value={prefix}>{name}</option>
          ))}
        </select>
      </div>

      <div style={{ marginBottom: 8 }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Районы</div>
        <select style={{ width: '100%' }} value={districtId} onChange={(e)=>{ const v = e.target.value; setDistrictId(v); setNrUser(''); onSelectUser('', v) }}>
          <option value="">Выберите район</option>
          {filteredDistricts.map(([id, name]) => (
            <option key={id} value={id}>{name}</option>
          ))}
        </select>
      </div>

      <div style={{ marginBottom: 8 }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Землепользователь</div>
        <select style={{ width: '100%' }} value={nrUser} onChange={(e)=>{ const v=e.target.value; setNrUser(v); onSelectUser(v, districtId) }} disabled={!districtId}>
          <option value="">Выберите землепользователя</option>
          {/* <option value="*">*все*</option>     */}
          
          {usersForDistrict.map(u => (
            <option key={u.key} value={u.value}>{u.label}</option>
          ))}
          {/* {usersForDistrict[0].value.substring(0, 4).map(u => (
            <option key={"*все*"} value={u}>{u}</option>
          ))} */}
        </select>
      </div>

      <div style={{ marginBottom: 8 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input type="checkbox" checked={showVectors} onChange={(e)=>setShowVectors(e.target.checked)} />
          с/х участки
        </label>
      </div>

      <StatsTable data={statsData} />
      {baseLayer==='wms' && <WmsLegend layer="image_assessment" />}
    </div>
  )
}

