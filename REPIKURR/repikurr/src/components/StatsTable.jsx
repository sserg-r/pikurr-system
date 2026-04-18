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
  let totalCount = 0
  let totalSum   = 0
  rows.forEach(([, area, fieldCount]) => {
    totalCount += Number(area)       || 0
    totalSum   += Number(fieldCount) || 0
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
          {rows.map(([val, area, fieldCount]) => (
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
            <td className="value-cell">{totalCount.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}</td>
            <td className="value-cell">{totalSum.toFixed(0)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}
