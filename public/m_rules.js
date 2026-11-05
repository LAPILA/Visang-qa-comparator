const $ = selector => document.querySelector(selector);
const form = $('#ruleForm');
const KEY = 'm_qa_rules_v1';
const PROJECTS = 'm_qa_projects_v1';
const KINDS = new Set(['visible','count','text_length','overflow','attribute']);
const ATTRIBUTES = /^(?:id|class|role|title|type|disabled|hidden|maxlength|aria-[a-z-]+|data-[a-z0-9-]+)$/;
let projects = [], rules = [], selectedId = null;

function message(text, error = false) { $('#notice').textContent = text; $('#notice').classList.toggle('error', error); }
function read(key) { try { const value = JSON.parse(localStorage.getItem(key) || '[]'); return Array.isArray(value) ? value : []; } catch { return []; } }
function projectId() { return $('#projectId').value; }
function current() { return rules.find(item => item.id === selectedId && item.projectId === projectId()); }
function saveRules(next) { try { localStorage.setItem(KEY, JSON.stringify(next)); rules = next; return true; } catch { message('브라우저에 규칙을 저장하지 못했습니다.', true); return false; } }
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
    const detail = document.createElement('small'); detail.textContent = `${rule.condition.id} · ${rule.condition.kind} · ${rule.condition.selector}`;
    title.append(strong, detail); title.addEventListener('click', () => { selectedId = rule.id; fill(rule); render(); });
    const toggle = document.createElement('label'); toggle.className = 'rule-toggle';
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = Boolean(rule.enabled);
    checkbox.setAttribute('aria-label', `${rule.name} 활성화`);
    checkbox.addEventListener('change', () => {
      const next = rules.map(item => item.id === rule.id ? { ...item, enabled: checkbox.checked } : item);
      if (saveRules(next)) { render(); message(checkbox.checked ? '규칙을 활성화했습니다.' : '규칙을 비활성화했습니다.'); }
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
    const condition = { id, case: 'custom', selector: form.elements.selector.value.trim(), kind,
      preconditions: validatePreconditions(JSON.parse(form.elements.preconditions.value || '[]')) };
    const url = form.elements.urlPattern.value.trim(); if (url) condition.url_pattern = url;
    if (['visible','overflow'].includes(kind)) condition.expected = form.elements.booleanExpected.value === 'true';
    if (['count','text_length'].includes(kind)) {
      const value = Number(form.elements.numberExpected.value);
      if (!Number.isInteger(value) || value < 0 || value > 1000000) throw Error('기대 개수·길이는 0~1,000,000의 정수여야 합니다.');
      condition.expected = { equals: value };
      if (kind === 'text_length') condition.unit = form.elements.unit.value;
    }
    if (kind === 'attribute') {
      const attribute = form.elements.attribute.value.trim();
      if (!ATTRIBUTES.test(attribute) || /password|token|secret|session|cookie|credential|auth|api.?key/i.test(attribute)) throw Error('표시용 속성 이름만 사용할 수 있습니다.');
      condition.attribute = attribute; condition.expected = form.elements.textExpected.value;
    }
    return { id: selectedId || crypto.randomUUID(), projectId: projectId(), name, condition,
      enabled: current()?.enabled ?? true, createdAt: current()?.createdAt || new Date().toISOString() };
  } catch (error) { message(error instanceof SyntaxError ? '선행 조건 JSON 형식을 확인하세요.' : error.message, true); return null; }
}
function save() {
  const rule = readForm(); if (!rule) return null;
  const next = selectedId ? rules.map(item => item.id === selectedId ? rule : item) : [rule, ...rules];
  if (!saveRules(next)) return null;
  selectedId = rule.id; fill(rule); render(); message('검사 규칙을 이 브라우저에 저장했습니다.'); return rule;
}

projects = read(PROJECTS).filter(item => item?.id && item?.name);
rules = read(KEY).filter(item => item?.id && item?.projectId && item?.condition);
for (const project of projects) { const option = document.createElement('option'); option.value = project.id; option.textContent = project.name; $('#projectId').append(option); }
if (projects.length) $('#projectId').value = projects[0].id;
$('#projectId').addEventListener('change', () => { selectedId = null; fill(null); render(); });
$('#newRule').addEventListener('click', () => { selectedId = null; fill(null); render(); form.elements.name.focus(); });
form.elements.kind.addEventListener('change', syncKind);
form.addEventListener('submit', event => { event.preventDefault(); save(); });
$('#deleteRule').addEventListener('click', () => {
  const rule = current(); if (!rule || !confirm(`“${rule.name}” 규칙을 삭제할까요?`)) return;
  if (!saveRules(rules.filter(item => item.id !== rule.id))) return;
  selectedId = null; fill(null); render(); message('규칙을 삭제했습니다. 과거 검사 결과는 유지됩니다.');
});
$('#applyRules').addEventListener('click', () => {
  if (!projectId()) { message('프로젝트를 먼저 선택하세요.', true); return; }
  const conditions = rules.filter(item => item.projectId === projectId() && item.enabled).map(item => item.condition);
  if (!conditions.length) { message('활성 규칙이 없습니다.', true); return; }
  if (conditions.length > 30) { message('한 번에 적용할 수 있는 조건은 최대 30개입니다.', true); return; }
  try { sessionStorage.setItem('m_pending_rules', JSON.stringify({ projectId: projectId(), conditions })); location.href = '/'; }
  catch { message('검사 화면으로 규칙을 전달하지 못했습니다.', true); }
});
fill(null); render(); message(projects.length ? '프로젝트를 선택하고 규칙을 등록하세요.' : '등록된 프로젝트가 없습니다. 프로젝트 설정에서 먼저 만드세요.');
