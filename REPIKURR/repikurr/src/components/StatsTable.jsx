import './StatsTable.css';

const VALUE_LABELS = {
  forest:   'перевод в л/х',
  tillage:  'пахотное с/х',
  clearing: 'с/х после расчистки',
  meadow:   'луговое с/х',
}

const COLOR_MAP = {
  forest:   '#2C7D2C',
  tillage:  '#b85c06',
  meadow:   '#d9b530',
  clearing: '#0000CC',
}

export default function StatsTable({ data }) {
  if (!data) return null
  const rows = data?.AggregationResults || []
  // GeoServer WPS vec:Aggregate возвращает функции в порядке ["Count", "Sum"]
  // независимо от порядка Sum/Count в самом запросе (getstatsbyuser.xml) —
  // проверено на живом ответе: ["forest", 679, 1009.7] — 679 полей (Count),
  // 1009.7 га (Sum). Раньше здесь было наоборот ([, area, fieldCount]),
  // из-за чего в таблице подписи «Площадь» и «Полей» получали
  // переставленные значения.
  let totalArea  = 0
  let totalCount = 0
  rows.forEach(([, fieldCount, area]) => {
    totalCount += Number(fieldCount) || 0
    totalArea  += Number(area)       || 0
  })

  return (
    <div>
      <div style={{ fontWeight: 600, marginBottom: 6, fontSize: '0.88rem', textTransform: 'uppercase', letterSpacing: '0.03em', color: '#444' }}>
        Статистика
      </div>
      <table className="stats-table">
        <thead>
          <tr>
            <th>Класс</th>
            <th className="value-cell">Площадь, га</th>
            <th className="value-cell">Полей</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([val, fieldCount, area]) => (
            <tr key={val}>
              <td>
                <div className="stats-cell-label">
                  <span className="color-swatch" style={{ backgroundColor: COLOR_MAP[val] || '#999' }} />
                  {VALUE_LABELS[val] || val}
                </div>
              </td>
              <td className="value-cell">{Number(area).toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}</td>
              <td className="value-cell">{Number(fieldCount).toFixed(0)}</td>
            </tr>
          ))}
          <tr className="total-row">
            <td>Итого</td>
            <td className="value-cell">{totalArea.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}</td>
            <td className="value-cell">{totalCount.toFixed(0)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}
