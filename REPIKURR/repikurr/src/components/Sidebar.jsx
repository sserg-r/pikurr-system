import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { distr, oblasts } from '../constants';
import StatsTable from './StatsTable';
import WmsLegend from './WmsLegend';
import { FiMap, FiPackage, FiLayers, FiFilter, FiUser, FiCalendar, FiDownload, FiHelpCircle, FiX, FiGlobe, FiChevronsLeft, FiRefreshCw } from 'react-icons/fi';
import './Sidebar.css';

const HELP_TEXT = 'Система отражает оценку спонтанной растительности сельскохозяйственных угодий на основе анализа данных дистанционного зондирования с использованием ИИ-технологий.';

export default function Sidebar({
  isOpen, onClose, onReset,
  baseLayer, setBaseLayer,
  usersByDistrict, onSelectUser,
  // round37, блок A2.1: область — теперь управляемое (не локальное)
  // состояние, приходит от App вместе с onSelectOblast — иначе сброс
  // области сменой года (эффект ниже) молча расходился бы с фильтром
  // группы в App (локальный oblastId сбрасывался, а App.selectedOblast —
  // нет, подсветка продолжала бы фильтровать по уже неактуальной области).
  selectedOblast, onSelectOblast,
  showVectors, setShowVectors,
  showMosaic, setShowMosaic,
  statsData,
  availableYears, selectedYear, setSelectedYear,
  districtsByYear,
}) {
  const oblastId = selectedOblast || '';
  const [districtId, setDistrictId] = useState('');
  const [nrUser, setNrUser]       = useState('');
  const [showHelp, setShowHelp]   = useState(false);
  const [qgisDownloadError, setQgisDownloadError] = useState('');

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
      onSelectOblast?.('');
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

  function handleReset() {
    onSelectOblast?.('');
    setDistrictId('');
    setNrUser('');
    onSelectUser?.('', '');
    onReset?.();
  }

  // round46, блок B.1: раньше клик по кнопке безусловно создавал и
  // "нажимал" <a download> — при пропаже файла на сервере try_files
  // отдаёт index.html (200, text/html) под именем архива, и пользователь
  // тихо получает битый файл вместо архива/qlr. Теперь перед скачиванием
  // каждый файл проверяется по содержимому (код ответа + Content-Type —
  // не HTML — и ненулевой размер), а не только по факту клика.
  async function fetchAndSaveFile(url, filename) {
    let resp;
    try {
      resp = await fetch(url);
    } catch {
      throw new Error(`не удалось обратиться к серверу (${url})`);
    }
    const contentType = resp.headers.get('content-type') || '';
    const contentLength = Number(resp.headers.get('content-length') || '0');
    if (!resp.ok || contentType.includes('text/html') || contentLength === 0) {
      throw new Error(`файл недоступен (${url}, код ${resp.status}, тип "${contentType}")`);
    }
    const blob = await resp.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(objectUrl);
  }

  const downloadQGISFiles = async () => {
    setQgisDownloadError('');
    try {
      await fetchAndSaveFile('/pikurr_layers.qlr', 'pikurr_layers.qlr');
      await fetchAndSaveFile('/pikurr_qgis_instructions.txt', 'pikurr_qgis_instructions.txt');
    } catch (e) {
      setQgisDownloadError(
        `Не удалось скачать файл для QGIS: ${e.message}. Попробуйте позже или сообщите администратору.`
      );
    }
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

      {/* Доступ из QGIS (round46: файл определения слоёв вместо
          плагина-прототипа — см. docs/round46-qgis-route.md) */}
      <div className="sidebar-section">
        <div className="section-title"><FiPackage size={16} /><span>Данные для QGIS</span></div>
        <button className="download-btn" onClick={downloadQGISFiles} title="Скачать файл слоёв для QGIS">
          <FiDownload size={15} />
          скачать для QGIS
        </button>
        {qgisDownloadError && (
          <p className="qgis-download-error" role="alert">{qgisDownloadError}</p>
        )}
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
            onSelectOblast?.(v);
            setDistrictId('');
            setNrUser('');
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

      {/* Сброс фильтров */}
      <div className="sidebar-section">
        <button className="reset-btn" onClick={handleReset} title="Сбросить все фильтры">
          <FiRefreshCw size={14} />
          сбросить фильтры
        </button>
      </div>

      {/* Статистика */}
      <div className="stats-section">
        <StatsTable data={statsData} />
      </div>

      {baseLayer === 'wms' && <WmsLegend layer="image_assessment" />}

      {/* Help overlay — рендерим в document.body через портал, иначе overflow:auto сайдбара обрезает fixed-позиционирование */}
      {showHelp && createPortal(
        <div className="help-overlay" onClick={() => setShowHelp(false)}>
          <div className="help-content" onClick={e => e.stopPropagation()}>
            <button className="close-help" onClick={() => setShowHelp(false)}>
              <FiX size={18} />
            </button>
            <p>{HELP_TEXT}</p>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}
