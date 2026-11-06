// 프로젝트 설정: 서버 저장소(이 PC 설정 파일 또는 로컬 PostgreSQL)의 프로젝트·환경·환경별 로그인 정보.
// 원안: origin/1105_mia. 비밀번호는 저장할 때만 보내고 응답에는 hasPassword만 돌아옵니다.
const $ = selector => document.querySelector(selector);
const form = $('#projectForm'), rows = $('#environmentRows'), list = $('#projectList'), notice = $('#notice');
const LEGACY_KEY = 'm_qa_projects_v1';
let projects = [], selectedId = null, token = '';
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx'.replace(/x/g, () => (Math.random() * 16 | 0).toString(16)));

function message(value, error = false) { notice.textContent = value; notice.className = `notice ${error ? 'error-notice' : 'success-notice'}`; }
async function request(path, body) {
  const options = { cache: 'no-store', headers: { Accept: 'application/json' } };
  if (body) { options.method = 'POST'; options.headers['Content-Type'] = 'application/json'; options.headers['X-QA-Token'] = token; options.body = JSON.stringify(body); }
  const response = await fetch(path, options);
  let data; try { data = await response.json(); } catch { throw new Error(`서버 응답을 읽을 수 없습니다. (HTTP ${response.status})`); }
  if (!response.ok) throw new Error(data.error || `서버 오류 (HTTP ${response.status})`);
  return data;
}
function field(labelText, name, value, type, maximum, placeholder, required = true) {
  const label = document.createElement('label'); label.textContent = labelText;
  const input = document.createElement('input'); Object.assign(input, { name, value, type, maxLength: maximum, placeholder, required });
  input.autocomplete = type === 'password' ? 'new-password' : 'off';
  label.append(input); return label;
}
function addEnvironment(environment = { id: uid(), name: '', url: '' }) {
  const row = document.createElement('div'); row.className = 'environment-row'; row.dataset.id = environment.id;
  row.append(field('환경 이름', 'environmentName', environment.name, 'text', 50, '예: 운영'), field('환경 URL', 'environmentUrl', environment.url, 'url', 2000, 'https://example.com/'));
  const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'secondary danger env-remove'; remove.textContent = '삭제';
  remove.setAttribute('aria-label', `${environment.name || '빈 환경'} 삭제`);
  remove.addEventListener('click', () => { if (rows.children.length <= 1) { message('환경은 최소 한 개가 필요합니다.', true); return; } row.remove(); message('환경을 목록에서 제거했습니다. 저장하면 반영됩니다.'); });
  row.append(remove);
  const login = document.createElement('div'); login.className = 'environment-login-fields';
  login.append(field('로그인 페이지 URL · 선택', 'loginUrl', environment.loginUrl || '', 'url', 2000, '비우면 자동 탐지', false),
    field('로그인 ID · 선택', 'loginId', environment.loginId || '', 'text', 200, '테스트 계정 ID', false),
    field('비밀번호 · 선택', 'loginPassword', '', 'password', 500, environment.hasPassword ? '저장됨 · 변경할 때만 입력' : '비밀번호 입력', false));
  const clear = document.createElement('label'); clear.className = 'clear-password';
  const box = document.createElement('input'); box.type = 'checkbox'; box.name = 'clearPassword'; box.disabled = !environment.hasPassword;
  box.addEventListener('change', () => { const password = login.querySelector('[name=loginPassword]'); password.disabled = box.checked; if (box.checked) password.value = ''; });
  clear.append(box, document.createTextNode('저장된 비밀번호 삭제'));
  login.append(clear); row.append(login); rows.append(row);
}
const current = () => projects.find(project => project.id === selectedId) || null;
function fill(project) {
  form.reset(); form.elements.name.value = project?.name || ''; rows.replaceChildren();
  for (const environment of project?.environments?.length ? project.environments : [{ id: uid(), name: '', url: '' }]) addEnvironment(environment);
  $('#formTitle').textContent = project ? '프로젝트 편집' : '프로젝트 만들기';
  $('#deleteProject').disabled = !project;
}
function renderList() {
  list.replaceChildren();
  if (!projects.length) { const p = document.createElement('p'); p.className = 'empty compact'; p.textContent = '아직 프로젝트가 없습니다. 오른쪽에서 만들어 보세요.'; list.append(p); return; }
  for (const project of projects) {
    const button = document.createElement('button'); button.type = 'button'; button.className = `project-item${project.id === selectedId ? ' selected' : ''}`;
    button.textContent = project.name || '이름 없음';
    const small = document.createElement('small');
    small.textContent = project.environments.map(item => item.name + (item.hasPassword ? ' 🔒' : '')).join(' · ') || '환경 없음';
    button.append(small);
    button.addEventListener('click', () => { selectedId = project.id; fill(project); renderList(); });
    list.append(button);
  }
}
function readForm() {
  if (!form.reportValidity()) return null;
  const environments = [...rows.querySelectorAll('.environment-row')].map(row => ({
    id: row.dataset.id, name: row.querySelector('[name=environmentName]').value.trim(), url: row.querySelector('[name=environmentUrl]').value.trim(),
    loginUrl: row.querySelector('[name=loginUrl]').value.trim(), loginId: row.querySelector('[name=loginId]').value.trim(),
    password: row.querySelector('[name=loginPassword]').value, clearPassword: row.querySelector('[name=clearPassword]').checked }));
  if (!form.elements.name.value.trim()) { message('프로젝트 이름을 입력하세요.', true); return null; }
  if (!environments.length || environments.some(item => !item.name || !item.url)) { message('모든 환경의 이름과 URL을 입력하세요.', true); return null; }
  for (const environment of environments) {
    for (const [key, label] of [['url', 'URL'], ['loginUrl', '로그인 URL']]) {
      if (!environment[key]) continue;
      try { const parsed = new URL(environment[key]); if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) throw Error(); }
      catch { message(`“${environment.name}”의 ${label}을 확인하세요.`, true); return null; }
    }
    if (environment.password && !environment.loginId) { message(`“${environment.name}”에 비밀번호만 있고 로그인 ID가 없습니다.`, true); return null; }
  }
  return { id: selectedId || uid(), name: form.elements.name.value.trim(), environments };
}
async function save() {
  const draft = readForm(); if (!draft) return null;
  try {
    const { project } = await request('/api/projects/save', draft);
    projects = [project, ...projects.filter(item => item.id !== project.id)]; selectedId = project.id; renderList(); fill(project);
    message('프로젝트와 환경 목록을 저장했습니다. 비밀번호는 암호화되어 화면에 다시 표시되지 않습니다.'); return project;
  } catch (error) { message(error.message, true); return null; }
}
async function migrateLegacy() {
  // 예전 버전이 브라우저(localStorage)에 저장한 프로젝트는 처음 한 번 서버 저장소로 옮깁니다.
  let legacy = [];
  try { legacy = JSON.parse(localStorage.getItem(LEGACY_KEY) || '[]'); } catch { legacy = []; }
  if (!Array.isArray(legacy) || !legacy.length) return 0;
  let moved = 0;
  for (const project of legacy) {
    if (!project?.id || projects.some(item => item.id === project.id)) continue;
    const old = project.environments?.length ? project.environments : [
      { name: project.baselineName || 'A', url: project.baselineUrl },
      ...(project.candidateUrl ? [{ name: project.candidateName || 'B', url: project.candidateUrl }] : [])];
    const environments = old.filter(item => item?.url).map(item => ({ id: /^[0-9a-f-]{36}$/i.test(item.id || '') ? item.id : uid(), name: item.name || 'A', url: item.url }));
    if (!environments.length) continue;
    try {
      const id = /^[0-9a-f-]{36}$/i.test(project.id) ? project.id : uid();
      projects.unshift((await request('/api/projects/save', { id, name: String(project.name || '이름 없음').slice(0, 60), environments })).project); moved += 1;
    } catch { return moved; /* keep the legacy copy if the move failed */ }
  }
  localStorage.removeItem(LEGACY_KEY);
  return moved;
}
$('#newProject').addEventListener('click', () => { selectedId = null; fill(null); renderList(); form.elements.name.focus(); });
$('#addEnvironment').addEventListener('click', () => { addEnvironment(); rows.lastElementChild.querySelector('input').focus(); });
form.addEventListener('submit', event => { event.preventDefault(); save(); });
$('#useProject').addEventListener('click', async () => {
  const project = await save(); if (!project) return;
  const [a, b] = project.environments;
  const draft = { projectId: project.id, baselineName: a.name, baselineUrl: a.url, candidateName: b?.name || '', candidateUrl: b?.url || '', testType: b ? 'comparison' : 'single' };
  try { sessionStorage.setItem('m_pending_project', JSON.stringify(draft)); location.href = '/'; } catch { message('검사 화면으로 설정을 전달하지 못했습니다.', true); }
});
$('#deleteProject').addEventListener('click', async () => {
  const project = current(); if (!project || !confirm(`“${project.name}” 프로젝트를 삭제할까요? 기존 검사 결과는 유지됩니다.`)) return;
  try { await request('/api/projects/delete', { id: project.id }); projects = projects.filter(item => item.id !== project.id); selectedId = projects[0]?.id || null; fill(current()); renderList(); message('프로젝트를 삭제했습니다. 기존 검사 이력은 유지됩니다.'); }
  catch (error) { message(error.message, true); }
});
async function init() {
  try {
    const bootstrap = await request('/api/bootstrap');
    token = bootstrap.sessionToken || '';
    if (bootstrap.version) $('#versionPill').textContent = `v${bootstrap.version} · LOCAL`;
    const data = await request('/api/projects');
    projects = data.projects || [];
    $('#storagePill').textContent = `저장소 · ${data.storage?.label || '알 수 없음'}`;
    const moved = await migrateLegacy();
    selectedId = projects[0]?.id || null; fill(current()); renderList();
    message(`${projects.length}개 프로젝트를 불러왔습니다.${moved ? ` 브라우저에 있던 ${moved}개를 서버 저장소로 옮겼습니다.` : ''}`);
  } catch (error) { fill(null); renderList(); message(error.message, true); }
}
init();
