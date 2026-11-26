/* 教材中的一条学习要求可以关联多个已有考点。同一细目可被多册引用。 */
const curriculum = KB.curriculum;
const cppUnitsById = new Map(KB.cpp_units.units.map(unit => [unit.id, unit]));
const curriculumEntries = curriculum.units.flatMap(unit =>
  unit.placements.map(row => ({unit, row})));
const curriculumBySource = new Map(curriculumEntries.map(entry => [entry.row.sourceId, entry]));

function curriculumParents(key) {
  return (curriculum.details[key] || curriculum.cppRefs[key])?.parents || [];
}

function parentLinks(keys) {
  return keys.map(key => T[key] ? topicLink(key) : esc(key.slice(1)) + '领域').join('、');
}

function curriculumTarget(key) {
  if (T[key]) return '已有考点 · ' + topicLink(key);
  const detail = curriculum.details[key];
  if (detail) return parentLinks(detail.parents) + ' › ' + esc(detail.name);
  const ref = curriculum.cppRefs[key];
  const unit = cppUnitsById.get(ref.unit);
  const fields = {phonics: '语音', vocab: '词汇', grammar: '语法', pragmatics: '交际'};
  const label = ref.items?.join(' / ') || (ref.field === 'phonics' ? unit.phonics.rule :
    ref.field === 'pragmatics' ? unit.pragmatics.zh : unit.theme);
  const ids = [ref.unit, ...(ref.alsoUnits || [])].join('、');
  return parentLinks(ref.parents) + ' › CPP ' + esc(ids + ' ' + fields[ref.field] + ' · ' + label);
}

function unitLocation(unit) {
  return unit.grade + '年级' + unit.semester + '册 · ' + (unit.unit === '待核' ? '单元待核' : unit.unit);
}

function curriculumForTopic(key) {
  const entries = curriculumEntries.filter(({row}) =>
    row.targets.some(target => target === key || curriculumParents(target).includes(key)));
  if (!entries.length) return '';
  const items = entries.map(({unit, row}) =>
    '<li><button type="button" class="currLink" data-placement="' + esc(row.sourceId) + '">' +
    esc(row.name) + '</button> <span class="meta">' + esc(unitLocation(unit)) + '</span></li>');
  return '<details><summary>教材单元与细目（' + items.length + ' 项）</summary><ul>' + items.join('') + '</ul></details>';
}

const cg = $('#currGrade'), cs = $('#currSemester'), cu = $('#currUnit'), cq = $('#currSearch');
function fillCurriculumUnits() {
  const units = curriculum.units.filter(u => u.grade === +cg.value && u.semester === cs.value);
  cu.innerHTML = '<option value="">全册</option>' + units.map(u =>
    '<option value="' + esc(u.unit) + '">' + esc(u.unit === '待核' ? '单元待核' : u.unit) + '</option>').join('');
}

function renderCurriculum() {
  const query = cq.value.trim().toLowerCase();
  const entries = curriculumEntries.filter(({unit, row}) => {
    if (unit.grade !== +cg.value || unit.semester !== cs.value || (cu.value && unit.unit !== cu.value)) return false;
    const terms = [row.name, row.objective, row.sourceId, unit.unit, ...(row.words || []), ...row.targets];
    row.targets.forEach(key => {
      terms.push(T[key]?.name || curriculum.details[key]?.name || curriculum.cppRefs[key]?.unit || '');
      curriculumParents(key).forEach(parent => terms.push(T[parent]?.name || parent));
    });
    return !query || terms.some(term => term.toLowerCase().includes(query));
  });
  $('#currCount').textContent = entries.length + ' 项';
  const sections = new Map();
  for (const {unit, row} of entries) {
    if (!sections.has(unit)) sections.set(unit, []);
    const words = row.words?.length ? '<p class="small">词语 · ' + esc(row.words.join('、')) + '</p>' : '';
    const note = row.note ? '<p class="meta">' + esc(row.note) + '</p>' : '';
    sections.get(unit).push('<li id="lesson-' + esc(row.sourceId) + '" tabindex="-1"><strong>' +
      esc(row.name) + '</strong><p>' + esc(row.objective) + '</p>' + words +
      '<div class="small">' + row.targets.map(curriculumTarget).join('<br>') + '</div>' + note + '</li>');
  }
  $('#currResults').innerHTML = [...sections].map(([unit, items]) =>
    '<section class="card"><h3>' + esc(unitLocation(unit)) + '</h3>' +
    (unit.unit === '待核' ? '<p class="meta">参考库核查了本册，尚未确定这些知识点对应哪一课。</p>' : '') +
    '<ul>' + items.join('') + '</ul></section>').join('') ||
    '<p class="card">' + (cg.value === '9' && cs.value === '下' ? '参考库当前没有九年级下册的独立条目。' : '本次筛选没有匹配的知识点。') + '</p>';
}

document.addEventListener('click', event => {
  const entry = curriculumBySource.get(event.target.dataset?.placement);
  if (!entry) return;
  cg.value = entry.unit.grade;
  cs.value = entry.unit.semester;
  fillCurriculumUnits();
  cu.value = entry.unit.unit;
  cq.value = '';
  renderCurriculum();
  switchTab('curriculum');
  document.getElementById('lesson-' + entry.row.sourceId)?.focus();
});
cg.onchange = cs.onchange = () => { fillCurriculumUnits(); renderCurriculum(); };
cu.onchange = cq.oninput = renderCurriculum;
fillCurriculumUnits();
renderCurriculum();
