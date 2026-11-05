const form = document.querySelector('#projectForm');
const rows = document.querySelector('#environmentRows');
const list = document.querySelector('#projectList');
const notice = document.querySelector('#notice');
let projects = [], selectedId = null, token = '';
function message(value, error = false) { notice.textContent = value; notice.classList.toggle('error', error); }
async function request(path, body) {
  const options = { cache: 'no-store' };
  if (body) { options.method = 'POST'; options.headers = { 'Content-Type': 'application/json', 'X-QA-Token': token }; options.body = JSON.stringify(body); }
  const response = await fetch(path, options), data = await response.json();
  if (!response.ok) throw new Error(data.error || `서버 오류 (${response.status})`);
  return data;
}
function field(labelText, name, value, type, maximum, placeholder) {
  const label = document.createElement('label'); label.textContent = labelText;
  const input = document.createElement('input');
  Object.assign(input, { name, value, type, maxLength: maximum, placeholder, required: true });
  label.append(input); return label;
}
function addEnvironment(environment = { id: crypto.randomUUID(), name: '', url: '' }) {
  const row = document.createElement('div'); row.className = 'environment-row'; row.dataset.id = environment.id;
  row.append(field('환경 이름', 'environmentName', environment.name, 'text', 50, '예: 운영'), field('환경 URL', 'environmentUrl', environment.url, 'url', 2000, 'https://example.com/'));
  const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'button danger'; remove.textContent = '삭제';
  remove.setAttribute('aria-label', `${environment.name || '빈 환경'} 삭제`);
  remove.addEventListener('click', () => { if (rows.children.length <= 1) { message('환경은 최소 한 개가 필요합니다.', true); return; } row.remove(); message('환경을 목록에서 제거했습니다. 저장하면 반영됩니다.'); });
  row.append(remove); rows.append(row);
}
function current() { return projects.find(project => project.id === selectedId) || null; }
function fill(project) {
  form.reset(); form.elements.name.value = project?.name || ''; rows.replaceChildren();
  for (const environment of project?.environments?.length ? project.environments : [{ id: crypto.randomUUID(), name: '', url: '' }]) addEnvironment(environment);
  document.querySelector('#formTitle').textContent = project ? '프로젝트 편집' : '프로젝트 만들기';
  document.querySelector('#deleteProject').disabled = !project;
}
function renderList() {
  list.replaceChildren();
  for (const project of projects) {
    const button = document.createElement('button'); button.type = 'button'; button.className = `project-item${selectedId === project.id ? ' selected' : ''}`;
    const title = document.createElement('strong'); title.textContent = project.name;
    const count = document.createElement('small'); count.textContent = `등록 환경 ${project.environments.length}개`;
    button.append(title, count); button.addEventListener('click', () => { selectedId = project.id; fill(project); renderList(); }); list.append(button);
  }
  if (!projects.length) { const empty = document.createElement('p'); empty.className = 'hint'; empty.textContent = '등록된 프로젝트가 없습니다.'; list.append(empty); }
}
function readForm() {
  if (!form.reportValidity()) return null;
  const environments = [...rows.children].map(row => ({ id: row.dataset.id, name: row.querySelector('[name=environmentName]').value.trim(), url: row.querySelector('[name=environmentUrl]').value.trim() }));
  if (!environments.length || environments.some(item => !item.name || !item.url)) { message('모든 환경의 이름과 URL을 입력하세요.', true); return null; }
  for (const environment of environments) {
    try { const parsed = new URL(environment.url); if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) throw Error(); }
    catch { message(`“${environment.name}”의 URL을 확인하세요.`, true); return null; }
  }
  return { id: selectedId || crypto.randomUUID(), name: form.elements.name.value.trim(), environments };
}
async function save() {
  const draft = readForm(); if (!draft) return null;
  try {
    const { project } = await request('/api/projects/save', draft);
    projects = [project, ...projects.filter(item => item.id !== project.id)]; selectedId = project.id; renderList(); fill(project);
    message('프로젝트와 환경 목록을 DB에 저장했습니다.'); return project;
  } catch (error) { message(error.message, true); return null; }
}
document.querySelector('#newProject').addEventListener('click', () => { selectedId = null; fill(null); renderList(); form.elements.name.focus(); });
document.querySelector('#addEnvironment').addEventListener('click', () => { addEnvironment(); rows.lastElementChild.querySelector('input').focus(); });
form.addEventListener('submit', event => { event.preventDefault(); save(); });
document.querySelector('#useProject').addEventListener('click', async () => {
  const project = await save(); if (!project) return;
  const [a, b] = project.environments;
  sessionStorage.setItem('m_pending_project', JSON.stringify({ projectId: project.id, baselineName: a.name, baselineUrl: a.url, candidateName: b?.name || '', candidateUrl: b?.url || '', testType: b ? 'comparison' : 'single' }));
  location.href = '/';
});
document.querySelector('#deleteProject').addEventListener('click', async () => {
  const project = current(); if (!project || !confirm(`“${project.name}” 프로젝트를 삭제할까요? 기존 검사 결과는 유지됩니다.`)) return;
  try { await request('/api/projects/delete', { id: project.id }); projects = projects.filter(item => item.id !== project.id); selectedId = projects[0]?.id || null; fill(current()); renderList(); message('프로젝트를 삭제했습니다. 기존 검사 이력은 유지됩니다.'); }
  catch (error) { message(error.message, true); }
});
async function init() {
  try {
    token = (await request('/api/bootstrap')).sessionToken;
    projects = (await request('/api/projects')).projects;
    let legacy = [];
    try { legacy = JSON.parse(localStorage.getItem('m_qa_projects_v1') || '[]'); } catch { /* Invalid old cache is ignored. */ }
    if (Array.isArray(legacy) && legacy.length) {
      for (const project of legacy) {
        if (projects.some(item => item.id === project.id)) continue;
        const oldEnvironments = project.environments?.length ? project.environments : [
          { name: project.baselineName || 'A', url: project.baselineUrl },
          ...(project.candidateUrl ? [{ name: project.candidateName || 'B', url: project.candidateUrl }] : [])
        ];
        const environments = oldEnvironments.map(item => ({ id: item.id || crypto.randomUUID(), name: item.name, url: item.url }));
        const saved = (await request('/api/projects/save', { id: project.id, name: project.name, environments })).project;
        projects.unshift(saved);
      }
      localStorage.removeItem('m_qa_projects_v1');
    }
    selectedId = projects[0]?.id || null; fill(current()); renderList(); message(`${projects.length}개 프로젝트를 DB에서 불러왔습니다.`);
  }
  catch (error) { message(error.message, true); }
}
init();
