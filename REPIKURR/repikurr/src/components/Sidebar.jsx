import { useEffect, useMemo, useState } from 'react';
import { distr, oblasts } from '../constants';
import StatsTable from './StatsTable';
import WmsLegend from './WmsLegend';
import { FiMap, FiPackage, FiLayers, FiFilter, FiUser, FiCalendar, FiDownload, FiHelpCircle, FiX, FiGlobe, FiChevronsLeft } from 'react-icons/fi';
import './Sidebar.css';

const HELP_TEXT = 'Система отражает оценку спонтанной растительности сельскохозяйственных угодий на основе анализа данных дистанционного зондирования с использованием ИИ-технологий.';

export default function Sidebar({
  isOpen, onClose,
  baseLayer, setBaseLayer,
  usersByDistrict, onSelectUser,
  showVectors, setShowVectors,
  showMosaic, setShowMosaic,
  statsData,
  availableYears, selectedYear, setSelectedYear,
  districtsByYear,
}) {
  const [oblastId, setOblastId]   = useState('');
  const [districtId, setDistrictId] = useState('');
  const [nrUser, setNrUser]       = useState('');
  const [showHelp, setShowHelp]   = useState(false);

  // При смене года — сбрасываем район/землепользователь если у них нет данных за этот год
  useEffect(() => {
    const yearSet = selectedYear ? districtsByYear?.[selectedYear] : null;
    if (!yearSet) return;
    if (districtId && !yearSet.has(districtId)) {
      setDistrictId('');
      setNrUser('');
      onSelectUser('', '');
    }
    if (oblastId && ![...yearSet].some(d => d.substring(0, 2) === oblastId)) {
      setOblastId('');
    }
  }, [selectedYear, districtsByYear]);

  const activeOblasts = useMemo(() => {
    const yearSet = selectedYear ? districtsByYear?.[selectedYear] : null;
    const prefixes = new Set(
      Object.keys(usersByDistrict)
        .filter(id => usersByDistrict[id]?.length > 0)
        .filter(id => !yearSet || yearSet.has(id))
        .map(id => id.substring(0, 2))
    );
    return Object.entries(oblasts).filter(([p]) => prefixes.has(p));
  }, [usersByDistrict, selectedYear, districtsByYear]);

  const filteredDistricts = useMemo(() => {
    const yearSet = selectedYear ? districtsByYear?.[selectedYear] : null;
    return Object.entries(distr).filter(([id]) => {
      if (oblastId && id.substring(0, 2) !== oblastId) return false;
      if (!(usersByDistrict[id]?.length > 0)) return false;
      if (yearSet && !yearSet.has(id)) return false;
      return true;
    });
  }, [oblastId, usersByDistrict, selectedYear, districtsByYear]);

  const usersForDistrict = useMemo(
    () => usersByDistrict[districtId] || [],
    [usersByDistrict, districtId]
  );

  const downloadQGISFiles = () => {
    const zipLink = document.createElement('a');
    zipLink.href = '/pikurr_qgis.zip';
    zipLink.download = 'pikurr_qgis.zip';
    document.body.appendChild(zipLink);
    zipLink.click();
    document.body.removeChild(zipLink);
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
    <div className={`sidebar${isOpen ? '' : ' collapsed'}`}>

      {/* Заголовок */}
      <div className="sidebar-header">
        <div className="sidebar-header-top">
          <h2>ПИК УРР</h2>
          <button className="sidebar-close-btn" onClick={onClose} title="Свернуть панель">
            <FiChevronsLeft size={18} />
          </button>
        </div>
        <div className="subtitle-container">
          <p className="subtitle">Оценка сельскохозяйственных угодий</p>
          <button className="help-icon" onClick={() => setShowHelp(true)} title="О системе">
            <FiHelpCircle size={15} />
          </button>
        </div>
      </div>

      {/* QGIS плагин */}
      <div className="sidebar-section">
        <div className="section-title"><FiPackage size={16} /><span>Плагин для QGIS</span></div>
        <button className="download-btn" onClick={downloadQGISFiles} title="Скачать плагин для QGIS">
          <FiDownload size={15} />
          скачать плагин
        </button>
      </div>

      {/* Базовые карты */}
      <div className="sidebar-section">
        <div className="section-title"><FiMap size={16} /><span>Базовые карты</span></div>
        <div className="radio-group">
          {[
            { value: 'none',  label: 'Нет' },
            { value: 'osm',   label: 'OSM' },
            { value: 'esri',  label: 'Esri Satellite' },
          ].map(opt => (
            <label key={opt.value} className="radio-option">
              <input type="radio" name="basemap" checked={baseLayer === opt.value} onChange={() => setBaseLayer(opt.value)} />
              <span className="radio-custom"></span>
              {opt.label}
            </label>
          ))}
        </div>
      </div>

      {/* Слои */}
      <div className="sidebar-section">
        <div className="section-title"><FiLayers size={16} /><span>Слои</span></div>
        <label className="toggle-option">
          <input type="checkbox" checked={showMosaic} onChange={e => setShowMosaic(e.target.checked)} />
          <span className="toggle-custom"></span>
          AI оценка
        </label>
        <label className="toggle-option">
          <input type="checkbox" checked={showVectors} onChange={e => setShowVectors(e.target.checked)} />
          <span className="toggle-custom"></span>
          С/х участки
        </label>
      </div>

      {/* Год оценки */}
      {availableYears && availableYears.length > 1 && (
        <div className="sidebar-section">
          <div className="section-title"><FiCalendar size={16} /><span>Год оценки</span></div>
          <select
            value={selectedYear ?? ''}
            onChange={e => setSelectedYear(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">Все годы</option>
            {availableYears.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
      )}

      {/* Область */}
      <div className="sidebar-section">
        <div className="section-title"><FiGlobe size={16} /><span>Область</span></div>
        <select
          value={oblastId}
          onChange={e => {
            const v = e.target.value;
            setOblastId(v);
            setDistrictId('');
            setNrUser('');
            onSelectUser('', '');
          }}
        >
          <option value="">Все области</option>
          {activeOblasts.map(([prefix, name]) => (
            <option key={prefix} value={prefix}>{name}</option>
          ))}
        </select>
      </div>

      {/* Район */}
      <div className="sidebar-section">
        <div className="section-title"><FiFilter size={16} /><span>Район</span></div>
        <select
          value={districtId}
          onChange={e => {
            const v = e.target.value;
            setDistrictId(v);
            setNrUser('');
            onSelectUser('', v);
          }}
        >
          <option value="">Выберите район</option>
          {filteredDistricts.map(([id, name]) => (
            <option key={id} value={id}>{name}</option>
          ))}
        </select>
      </div>

      {/* Землепользователь */}
      <div className="sidebar-section">
        <div className="section-title"><FiUser size={16} /><span>Землепользователь</span></div>
        <select
          value={nrUser}
          disabled={!districtId}
          onChange={e => {
            const v = e.target.value;
            setNrUser(v);
            onSelectUser(v, districtId);
          }}
        >
          <option value="">Выберите землепользователя</option>
          {usersForDistrict.map(u => (
            <option key={u.key} value={u.value}>{u.label}</option>
          ))}
        </select>
      </div>

      {/* Статистика */}
      <div className="stats-section">
        <StatsTable data={statsData} />
      </div>

      {baseLayer === 'wms' && <WmsLegend layer="image_assessment" />}

      {/* Help overlay */}
      {showHelp && (
        <div className="help-overlay" onClick={() => setShowHelp(false)}>
          <div className="help-content" onClick={e => e.stopPropagation()}>
            <button className="close-help" onClick={() => setShowHelp(false)}>
              <FiX size={18} />
            </button>
            <p>{HELP_TEXT}</p>
          </div>
        </div>
      )}
    </div>
  );
}
