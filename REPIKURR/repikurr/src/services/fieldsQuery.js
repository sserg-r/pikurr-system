// round49, блок B: единая точка семантики "год -> typeName/фильтр" для
// слоя карты, границ (getbboxbyuser.xml) и статистики (getstatsbyuser.xml).
//
// До этой правки: слой карты (App.jsx, vectorTypeName) правильно
// переключался между pikurr:fields_latest (без года) и pikurr:fields +
// year=N (с годом), а границы/статистика (getbboxbyuser.xml/
// getstatsbyuser.xml) ходили ВСЕГДА в pikurr:fields БЕЗ условия года —
// подтверждено фактом (round48, docs/round48-qgis-plugin.md, блок A1;
// round49 перепроверил тем же способом, что использует сам плагин).
// Пока на проде один год, расхождение незаметно; при появлении второго
// года статистика/границы витрины считали бы по ВСЕМ годам сразу.
//
// group — код группы (область/район/землепользователь), тот же принцип,
// что App.jsx::groupCqlExpr: `nr_user LIKE '<code>%'`. Для явного
// фильтра по атрибуту district (как в плагине, round49 A2) здесь не
// используется — витрина всегда фильтрует по nr_user-префиксу (не
// меняем это поведение, не входит в объём этого раунда: блок B просит
// только выровнять typeName/year, не переписывать способ фильтрации
// по группе).

export function fieldsTypeName(year) {
  return year ? 'pikurr:fields' : 'pikurr:fields_latest'
}

// Собирает OGC-фильтр (XML) для WPS-шаблонов (getbboxbyuser.xml,
// getstatsbyuser.xml) — год (если задан) И группа по nr_user-префиксу.
export function buildOgcFilter(year, groupCode) {
  const groupPart = `<ogc:PropertyIsLike wildCard="*" singleChar="." escape="!">` +
    `<ogc:PropertyName>nr_user</ogc:PropertyName>` +
    `<ogc:Literal>${groupCode}*</ogc:Literal></ogc:PropertyIsLike>`
  if (year) {
    return `<ogc:Filter><ogc:And>` +
      `<ogc:PropertyIsEqualTo><ogc:PropertyName>year</ogc:PropertyName>` +
      `<ogc:Literal>${year}</ogc:Literal></ogc:PropertyIsEqualTo>` +
      `${groupPart}</ogc:And></ogc:Filter>`
  }
  return `<ogc:Filter>${groupPart}</ogc:Filter>`
}

// Тот же CQL, что App.jsx строит для карты (groupCqlExpr) — с условием
// года, если он выбран. Используется там, где нужен CQL_FILTER-стиль
// (не OGC XML), на случай будущего использования вне WPS-шаблонов.
export function buildCqlFilter(year, groupCode) {
  const group = `nr_user LIKE '${groupCode}%'`
  return year ? `year = ${year} AND ${group}` : group
}
