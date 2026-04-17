const valueMap = {
  forest: 'перевод в л/х',
  tillage: 'пахотное с/х',
  clearing: 'с/х после расчистки',
  meadow: 'луговое с/х',
}

export default function StatsTable({ data }) {
  if (!data) return null
  const rows = data?.AggregationResults || []
  let totalCount = 0
  let totalSum = 0
  rows.forEach(([, count, sum]) => { totalCount += Number(count)||0; totalSum += Number(sum)||0 })

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 6 }}>Статистика</div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left', borderBottom: '1px solid #e5e7eb', padding: '6px 4px' }}>Класс</th>
            <th style={{ textAlign: 'right', borderBottom: '1px solid #e5e7eb', padding: '6px 4px' }}>Площадь, га</th>
            <th style={{ textAlign: 'right', borderBottom: '1px solid #e5e7eb', padding: '6px 4px' }}>Количество</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([val, count, sum]) => (
            <tr key={val}>
              <td style={{ padding: '6px 4px', borderBottom: '1px solid #f3f4f6', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{
                  display: 'inline-block',
                  width: '12px',
                  height: '12px',
                  backgroundColor: {
                    forest: '#2C7D2C',
                    tillage: '#b85c06',
                    meadow: '#d9b530',
                    clearing: '#0000CC'
                  }[val],
                  border: '1px solid #ccc'
                }}></span>
                {valueMap[val] || val}
              </td>
              <td style={{ padding: '6px 4px', textAlign: 'right', borderBottom: '1px solid #f3f4f6' }}>{Number(count).toFixed(1).toLocaleString('ru-RU')}</td>
              <td style={{ padding: '6px 4px', textAlign: 'right', borderBottom: '1px solid #f3f4f6' }}>{Number(sum).toFixed(0)}</td>
            </tr>
          ))}
          <tr>
            <td style={{ padding: '8px 4px', fontWeight: 600 }}>Итого</td>
            <td style={{ padding: '8px 4px', textAlign: 'right', fontWeight: 600 }}>{totalCount.toLocaleString('ru-RU')}</td>
            <td style={{ padding: '8px 4px', textAlign: 'right', fontWeight: 600 }}>{totalSum.toFixed(2)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

