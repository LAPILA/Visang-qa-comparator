// 검사 규칙: 프로젝트별 테스트 케이스·조건 기반 UI 규칙(서버 저장, 엑셀 가져오기) → 활성 규칙을 검사 설정의 조건으로 넘김.
const $ = selector => document.querySelector(selector);
const form = $('#ruleForm');
const KEY = 'm_qa_rules_v1';
const KINDS = new Set(['visible','count','text_length','overflow','attribute']);
const ATTRIBUTES = /^(?:id|class|role|title|type|disabled|hidden|maxlength|aria-[a-z-]+|data-[a-z0-9-]+)$/;
let projects = [], rules = [], selectedId = null, sessionToken = '';

function message(text, error = false) { $('#notice').textContent = text; $('#notice').className = `notice ${error ? 'error-notice' : 'success-notice'}`; }
function read(key) { try { const value = JSON.parse(localStorage.getItem(key) || '[]'); return Array.isArray(value) ? value : []; } catch { return []; } }
function projectId() { return $('#projectId').value; }
function current() { return rules.find(item => item.id === selectedId && item.projectId === projectId()); }
async function write(path, body) {
  const response = await fetch(path, { method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json', 'X-QA-Token': sessionToken }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `서버 오류 (${response.status})`);
  return data;
}
async function saveRule(rule) {
  await write('/api/rules/save', rule);
  rules = [rule, ...rules.filter(item => item.id !== rule.id)];
}
function validatePreconditions(items) {
  if (!Array.isArray(items) || items.length > 10) throw Error('선행 조건은 최대 10개의 JSON 배열이어야 합니다.');
  for (const item of items) {
    if (!item || typeof item !== 'object' || Array.isArray(item) ||
        Object.keys(item).some(key => !['selector','kind','expected','attribute','unit'].includes(key)) ||
        typeof item.selector !== 'string' || !item.selector.trim() || item.selector.length > 500 || !KINDS.has(item.kind) ||
        !Object.hasOwn(item, 'expected')) throw Error('선행 조건의 선택자·종류·기대값을 확인하세요.');
  }
  return items;
}
function syncKind() {
  const kind = form.elements.kind.value;
  $('#booleanField').classList.toggle('hidden', !['visible','overflow'].includes(kind));
  $('#numberField').classList.toggle('hidden', !['count','text_length'].includes(kind));
  $('#attributeField').classList.toggle('hidden', kind !== 'attribute');
  $('#textField').classList.toggle('hidden', kind !== 'attribute');
  $('#unitField').classList.toggle('hidden', kind !== 'text_length');
}
function fill(rule) {
  form.reset();
  form.elements.name.value = rule?.name || '';
  form.elements.ruleId.value = rule?.condition?.id || '';
  form.elements.urlPattern.value = rule?.condition?.url_pattern || '';
  form.elements.selector.value = rule?.condition?.selector || '';
  form.elements.kind.value = rule?.condition?.kind || 'visible';
  const expected = rule?.condition?.expected;
  if (typeof expected === 'boolean') form.elements.booleanExpected.value = String(expected);
  if (expected && typeof expected === 'object' && Number.isInteger(expected.equals)) form.elements.numberExpected.value = String(expected.equals);
  if (typeof expected === 'string') form.elements.textExpected.value = expected;
  form.elements.attribute.value = rule?.condition?.attribute || '';
  form.elements.unit.value = rule?.condition?.unit || 'codepoints';
  form.elements.preconditions.value = JSON.stringify(rule?.condition?.preconditions || [], null, 2);
  form.elements.automationReady.checked = rule?.automationReady !== false;
  for (const key of ['checkTarget','steps','expectedResult','preconditionsText','category1','category2','category3','testData','accountCondition','platform','browser','server']) {
    form.elements[key].value = rule?.caseData?.[key] || '';
  }
  $('#formTitle').textContent = rule ? '규칙 편집' : '규칙 만들기';
  $('#deleteRule').disabled = !rule;
  syncKind();
}
function render() {
  const list = $('#ruleList'); list.replaceChildren();
  const own = rules.filter(item => item.projectId === projectId());
  for (const rule of own) {
    const card = document.createElement('article'); card.className = `rule-item${rule.id === selectedId ? ' selected' : ''}`;
    const title = document.createElement('button'); title.type = 'button'; title.className = 'link';
    const strong = document.createElement('strong'); strong.textContent = rule.name;
    const detail = document.createElement('small'); detail.textContent = rule.automationReady === false
      ? `${rule.condition.id} · 수동 검토 / 자동화 매핑 필요`
      : `${rule.condition.id} · ${rule.condition.kind} · ${rule.condition.selector}`;
    if (rule.source?.fileName) detail.textContent += ` · ${rule.source.fileName} / ${rule.source.sheet} ${rule.source.row}행`;
    title.append(strong, detail); title.addEventListener('click', () => { selectedId = rule.id; fill(rule); render(); });
    const toggle = document.createElement('label'); toggle.className = 'rule-toggle';
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = Boolean(rule.enabled); checkbox.disabled = rule.automationReady === false;
    checkbox.setAttribute('aria-label', `${rule.name} 활성화`);
    checkbox.addEventListener('change', async () => {
      try { await saveRule({ ...rule, enabled: checkbox.checked }); render(); message(checkbox.checked ? '규칙을 활성화했습니다.' : '규칙을 비활성화했습니다.'); }
      catch (error) { checkbox.checked = !checkbox.checked; message(error.message, true); }
    });
    toggle.append(checkbox, document.createTextNode('활성')); card.append(title, toggle); list.append(card);
  }
  if (!own.length) { const empty = document.createElement('p'); empty.className = 'hint'; empty.textContent = projectId() ? '등록된 규칙이 없습니다.' : '먼저 프로젝트를 선택하세요.'; list.append(empty); }
}
function readForm() {
  if (!projectId()) { message('프로젝트를 먼저 선택하세요.', true); return null; }
  if (!form.reportValidity()) return null;
  try {
    const name = form.elements.name.value.trim(), id = form.elements.ruleId.value.trim(), kind = form.elements.kind.value;
    if (!name || !/^[A-Za-z0-9_.-]{1,100}$/.test(id)) throw Error('규칙 이름과 ID를 확인하세요.');
    if (rules.some(rule => rule.projectId === projectId() && rule.condition?.id === id && rule.id !== selectedId)) throw Error('같은 프로젝트에 동일한 규칙 ID가 있습니다.');
    const automationReady = form.elements.automationReady.checked;
    const selector = form.elements.selector.value.trim();
    if (automationReady && !selector) throw Error('자동 실행에는 요소 선택자가 필요합니다. 일반 테스트 케이스라면 자동 실행 체크를 해제하세요.');
    const condition = { id };
    if (automationReady) Object.assign(condition, { case: 'custom', selector, kind,
      preconditions: validatePreconditions(JSON.parse(form.elements.preconditions.value || '[]')) });
    else if (selector) Object.assign(condition, { selector, kind });
    const url = form.elements.urlPattern.value.trim(); if (url) condition.url_pattern = url;
    if (automationReady && ['visible','overflow'].includes(kind)) condition.expected = form.elements.booleanExpected.value === 'true';
    if (automationReady && ['count','text_length'].includes(kind)) {
      const value = Number(form.elements.numberExpected.value);
      if (!Number.isInteger(value) || value < 0 || value > 1000000) throw Error('기대 개수·길이는 0~1,000,000의 정수여야 합니다.');
      condition.expected = { equals: value };
      if (kind === 'text_length') condition.unit = form.elements.unit.value;
    }
    if (automationReady && kind === 'attribute') {
      const attribute = form.elements.attribute.value.trim();
      if (!ATTRIBUTES.test(attribute) || /password|token|secret|session|cookie|credential|auth|api.?key/i.test(attribute)) throw Error('표시용 속성 이름만 사용할 수 있습니다.');
      condition.attribute = attribute; condition.expected = form.elements.textExpected.value;
    }
    const caseData = {};
    for (const key of ['checkTarget','steps','expectedResult','preconditionsText','category1','category2','category3','testData','accountCondition','platform','browser','server']) {
      caseData[key] = form.elements[key].value.trim();
    }
    return { id: selectedId || crypto.randomUUID(), projectId: projectId(), name, condition, caseData, automationReady,
      source: current()?.source, enabled: automationReady && current()?.automationReady === false ? true : current()?.enabled ?? true,
      createdAt: current()?.createdAt || new Date().toISOString() };
  } catch (error) { message(error instanceof SyntaxError ? '선행 조건 JSON 형식을 확인하세요.' : error.message, true); return null; }
}
async function save() {
  const rule = readForm(); if (!rule) return null;
  try { await saveRule(rule); selectedId = rule.id; fill(rule); render(); message('검사 규칙을 저장했습니다.'); return rule; }
  catch (error) { message(error.message, true); return null; }
}

$('#projectId').addEventListener('change', () => { selectedId = null; fill(null); render(); });
$('#newRule').addEventListener('click', () => { selectedId = null; fill(null); render(); form.elements.name.focus(); });
form.elements.kind.addEventListener('change', syncKind);
form.addEventListener('submit', event => { event.preventDefault(); save(); });
$('#deleteRule').addEventListener('click', async () => {
  const rule = current(); if (!rule || !confirm(`“${rule.name}” 규칙을 삭제할까요?`)) return;
  try { await write('/api/rules/delete', { id: rule.id }); rules = rules.filter(item => item.id !== rule.id); selectedId = null; fill(null); render(); message('규칙을 삭제했습니다. 과거 검사 결과는 유지됩니다.'); }
  catch (error) { message(error.message, true); }
});
$('#applyRules').addEventListener('click', () => {
  if (!projectId()) { message('프로젝트를 먼저 선택하세요.', true); return; }
  const conditions = rules.filter(item => item.projectId === projectId() && item.enabled && item.automationReady !== false).map(item => item.condition);
  if (!conditions.length) { message('활성 규칙이 없습니다.', true); return; }
  if (conditions.length > 30) { message('한 번에 적용할 수 있는 조건은 최대 30개입니다.', true); return; }
  try { sessionStorage.setItem('m_pending_rules', JSON.stringify({ projectId: projectId(), conditions })); location.href = '/'; }
  catch { message('검사 화면으로 규칙을 전달하지 못했습니다.', true); }
});
async function loadProjects() {
  try {
    sessionToken = (await (await fetch('/api/bootstrap', { cache: 'no-store' })).json()).sessionToken || '';
    const response = await fetch('/api/projects', { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '프로젝트 목록을 불러오지 못했습니다.');
    projects = data.projects;
    const ruleResponse = await fetch('/api/rules', { cache: 'no-store' });
    const ruleData = await ruleResponse.json();
    if (!ruleResponse.ok) throw new Error(ruleData.error || '검사 규칙을 불러오지 못했습니다.');
    rules = ruleData.rules;
    const legacy = read(KEY).filter(item => item?.id && item?.projectId && item?.condition);
    const eligible = legacy.filter(item => projects.some(project => project.id === item.projectId));
    const missing = eligible.filter(item => !rules.some(saved => saved.id === item.id || (saved.projectId === item.projectId && saved.condition.id === item.condition.id)));
    let migrationError = null;
    if (missing.length) {
      try {
        await write('/api/rules/batch', { rules: missing });
        rules = (await (await fetch('/api/rules', { cache: 'no-store' })).json()).rules;
      } catch (error) { migrationError = error; }
    }
    if (legacy.length && eligible.length === legacy.length && !migrationError) localStorage.removeItem(KEY);
    $('#projectId').replaceChildren();
    for (const project of projects) { const option = document.createElement('option'); option.value = project.id; option.textContent = project.name; $('#projectId').append(option); }
    if (projects.length) $('#projectId').value = projects[0].id;
    fill(null); render(); message(migrationError ? `기존 브라우저 규칙을 저장소로 옮기지 못했습니다: ${migrationError.message}` :
      projects.length ? `${rules.length}개 규칙을 불러왔습니다. 프로젝트를 선택하세요.` : '등록된 프로젝트가 없습니다. 프로젝트 설정에서 먼저 만드세요.', Boolean(migrationError));
  } catch (error) { message(error.message, true); }
}
fetch('/api/bootstrap', { cache: 'no-store' }).then(r => r.json()).then(b => { if (b.version) $('#versionPill').textContent = `v${b.version} · LOCAL`; }).catch(() => {});
loadProjects();

function kindOf(value) {
  const key = String(value || '').trim().toLowerCase().replace(/\s/g, '');
  return ({ visible: 'visible', 표시여부: 'visible', 존재여부: 'visible', count: 'count', 요소개수: 'count', 개수: 'count',
    text_length: 'text_length', 텍스트길이: 'text_length', overflow: 'overflow', 넘침여부: 'overflow',
    attribute: 'attribute', 속성값: 'attribute' })[key] || null;
}
function expectedOf(kind, value) {
  const raw = String(value || '').trim();
  if (kind === 'visible' || kind === 'overflow') {
    if (['true','참','예','있음','표시','y','1'].includes(raw.toLowerCase())) return true;
    if (['false','거짓','아니오','없음','미표시','n','0'].includes(raw.toLowerCase())) return false;
    return null;
  }
  if (kind === 'count' || kind === 'text_length') {
    const number = Number(raw);
    return raw && Number.isInteger(number) && number >= 0 && number <= 1000000 ? { equals: number } : null;
  }
  return kind === 'attribute' && raw ? raw : null;
}
function hashText(value) {
  let hash = 2166136261;
  for (const character of value) { hash ^= character.charCodeAt(0); hash = Math.imul(hash, 16777619); }
  return (hash >>> 0).toString(36);
}
function keyFor(row, used) {
  const raw = String(row.caseId || '').trim();
  let base = raw.replace(/[^A-Za-z0-9_.-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 80);
  if (!base) base = `tc_${hashText(`${row.sourceSheet}:${row.sourceRow}:${raw}`)}`;
  let key = base, suffix = 2;
  while (used.has(key)) key = `${base.slice(0, 90)}_${suffix++}`;
  used.add(key);
  return key;
}
function ruleFromCase(row, fileName, used) {
  const id = keyFor(row, used);
  const name = String(row.title || row.checkTarget || row.caseId || `${row.sourceSheet} ${row.sourceRow}행`).trim().slice(0, 100);
  const kind = kindOf(row.kind), selector = String(row.selector || '').trim();
  const expected = expectedOf(kind, row.expectedValue);
  const ready = Boolean(selector && selector.length <= 500 && kind && expected !== null &&
    (kind !== 'attribute' || (ATTRIBUTES.test(row.attribute || '') && !/password|token|secret|session|cookie|credential|auth|api.?key/i.test(row.attribute))));
  const condition = { id };
  if (selector) condition.selector = selector.slice(0, 500);
  if (kind) condition.kind = kind;
  if (row.urlPattern) condition.url_pattern = String(row.urlPattern).slice(0, 2000);
  if (ready) {
    Object.assign(condition, { case: 'custom', expected, preconditions: [] });
    if (kind === 'attribute') condition.attribute = row.attribute;
    if (kind === 'text_length') condition.unit = ['codepoints','utf16'].includes(row.unit) ? row.unit : 'codepoints';
  }
  const caseData = {};
  for (const key of ['checkTarget','steps','expectedResult','preconditionsText','category1','category2','category3','testData','accountCondition','platform','browser','server']) caseData[key] = String(row[key] || '');
  return { id: crypto.randomUUID(), projectId: projectId(), name, condition, caseData,
    automationReady: ready, enabled: ready && !['false','아니오','n','0'].includes(String(row.enabled || '').trim().toLowerCase()),
    source: { fileName, sheet: row.sourceSheet, row: row.sourceRow, caseId: row.caseId || '' },
    createdAt: new Date().toISOString() };
}
async function importFile(file) {
  const summary = $('#importSummary');
  if (!projectId()) { message('업로드 전에 프로젝트를 선택하세요.', true); return; }
  if (!sessionToken) { message('화면을 새로고침한 뒤 다시 업로드해 주세요.', true); return; }
  if (!file || !/\.xlsx$/i.test(file.name) || file.size > 8_000_000) { message('.xlsx 파일(8MB 이하)을 선택하세요.', true); return; }
  summary.textContent = `${file.name} 읽는 중…`;
  try {
    const response = await fetch('/api/rules/import', { method: 'POST', cache: 'no-store',
      headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'X-QA-Token': sessionToken }, body: file });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `업로드 실패 (HTTP ${response.status})`);
    const used = new Set(rules.filter(rule => rule.projectId === projectId()).map(rule => rule.condition?.id));
    const sources = new Set(rules.filter(rule => rule.projectId === projectId()).map(rule => `${rule.source?.fileName}:${rule.source?.sheet}:${rule.source?.row}:${rule.source?.caseId || ''}`));
    const added = []; let duplicates = 0;
    for (const row of data.cases) {
      const sourceKey = `${file.name}:${row.sourceSheet}:${row.sourceRow}:${row.caseId || ''}`;
      if (sources.has(sourceKey)) { duplicates++; continue; }
      sources.add(sourceKey); added.push(ruleFromCase(row, file.name, used));
    }
    if (added.length) { await write('/api/rules/batch', { rules: added }); rules = [...added, ...rules]; }
    selectedId = added[0]?.id || selectedId; fill(current()); render();
    const ready = added.filter(rule => rule.automationReady).length;
    summary.textContent = `${file.name}: ${data.cases.length}행 읽음 · ${added.length}개 등록 · 자동 실행 ${ready}개 · 매핑 필요 ${added.length - ready}개 · 이미 가져온 행 ${duplicates}개`;
    message(added.length ? '엑셀 테스트 케이스를 등록했습니다. 목록에서 각 케이스를 열어 수정할 수 있습니다.' : '새로 등록할 행이 없습니다. 이미 가져온 파일인지 확인하세요.');
  } catch (error) { summary.textContent = ''; message(error.message, true); }
}
const dropZone = $('#ruleDropZone'), fileInput = $('#ruleFile');
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); fileInput.click(); } });
fileInput.addEventListener('change', () => { if (fileInput.files[0]) importFile(fileInput.files[0]); fileInput.value = ''; });
for (const type of ['dragenter','dragover']) dropZone.addEventListener(type, event => { event.preventDefault(); dropZone.classList.add('drag-over'); });
for (const type of ['dragleave','drop']) dropZone.addEventListener(type, event => { event.preventDefault(); dropZone.classList.remove('drag-over'); });
dropZone.addEventListener('drop', event => { if (event.dataTransfer.files[0]) importFile(event.dataTransfer.files[0]); });
