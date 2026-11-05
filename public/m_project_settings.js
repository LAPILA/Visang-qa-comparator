// 프로젝트 설정: 브라우저에 저장하는 프로젝트·환경 목록. (원안: origin/1105_mia, 저장 키·동작 동일)
const $ = selector => document.querySelector(selector);
const form = $('#projectForm'), rows = $('#environmentRows'), list = $('#projectList'), notice = $('#notice');
const KEY = 'm_qa_projects_v1';
let projects = loadProjects();
let selectedId = projects[0]?.id || null;
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));

function message(value, error = false) { notice.textContent = value; notice.className = `notice ${error ? 'error-notice' : 'success-notice'}`; }
function normalized(project) {
  if (!project || typeof project.id !== 'string') return null;
  let environments = Array.isArray(project.environments) ? project.environments : [];
  if (!environments.length && project.baselineUrl) {
    environments = [{ name: project.baselineName || 'A', url: project.baselineUrl }];
    if (project.candidateUrl) environments.push({ name: project.candidateName || 'B', url: project.candidateUrl });
  }
  environments = environments.filter(item => item && typeof item.name === 'string' && typeof item.url === 'string')
    .map(item => ({ id: typeof item.id === 'string' ? item.id : uid(), name: item.name, url: item.url }));
  return { id: project.id, name: String(project.name || ''), environments };
}
function loadProjects() { try { const value = JSON.parse(localStorage.getItem(KEY) || '[]'); return Array.isArray(value) ? value.map(normalized).filter(Boolean) : []; } catch { return []; } }
function saveProjects(next) { try { localStorage.setItem(KEY, JSON.stringify(next)); projects = next; return true; } catch { message('브라우저 저장 공간에 프로젝트를 저장하지 못했습니다.', true); return false; } }
function field(labelText, name, value, type, maximum, placeholder) {
  const label = document.createElement('label'); label.textContent = labelText;
  const input = document.createElement('input'); Object.assign(input, { name, value, type, maxLength: maximum, placeholder, required: true });
  label.append(input); return label;
}
function addEnvironment(environment = { id: uid(), name: '', url: '' }) {
  const row = document.createElement('div'); row.className = 'environment-row'; row.dataset.id = environment.id;
  row.append(field('환경 이름', 'environmentName', environment.name, 'text', 50, '예: 운영'), field('환경 URL', 'environmentUrl', environment.url, 'url', 2000, 'https://example.com/'));
  const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'secondary danger'; remove.textContent = '삭제';
  remove.addEventListener('click', () => { if (rows.children.length <= 1) { message('환경은 최소 한 개가 필요합니다.', true); return; } row.remove(); message('환경을 목록에서 제거했습니다. 저장하면 반영됩니다.'); });
  row.append(remove); rows.append(row);
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
    const small = document.createElement('small'); small.textContent = project.environments.map(item => item.name).join(' · ') || '환경 없음'; button.append(small);
    button.addEventListener('click', () => { selectedId = project.id; fill(project); renderList(); });
    list.append(button);
  }
}
function readForm() {
  const environments = [...rows.querySelectorAll('.environment-row')].map(row => ({ id: row.dataset.id, name: row.querySelector('[name=environmentName]').value.trim(), url: row.querySelector('[name=environmentUrl]').value.trim() }));
  if (!form.elements.name.value.trim()) { message('프로젝트 이름을 입력하세요.', true); return null; }
  if (!environments.length || environments.some(item => !item.name || !item.url)) { message('모든 환경의 이름과 URL을 입력하세요.', true); return null; }
  for (const environment of environments) {
    try { const parsed = new URL(environment.url); if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) throw Error(); }
    catch { message(`“${environment.name}”의 URL을 확인하세요.`, true); return null; }
  }
  return { id: selectedId || uid(), name: form.elements.name.value.trim(), environments };
}
function save() {
  const project = readForm(); if (!project) return null;
  const next = selectedId ? projects.map(item => item.id === selectedId ? project : item) : [project, ...projects];
  if (!saveProjects(next)) return null;
  selectedId = project.id; renderList(); fill(project); message('프로젝트와 환경 목록을 이 브라우저에 저장했습니다.');
  return project;
}
$('#newProject').addEventListener('click', () => { selectedId = null; fill(null); renderList(); form.elements.name.focus(); });
$('#addEnvironment').addEventListener('click', () => { addEnvironment(); rows.lastElementChild.querySelector('input').focus(); });
form.addEventListener('submit', event => { event.preventDefault(); save(); });
$('#useProject').addEventListener('click', () => {
  const project = save(); if (!project) return;
  const [a, b] = project.environments;
  const draft = { projectId: project.id, baselineName: a.name, baselineUrl: a.url, candidateName: b?.name || '', candidateUrl: b?.url || '', testType: b ? 'comparison' : 'single' };
  try { sessionStorage.setItem('m_pending_project', JSON.stringify(draft)); location.href = '/'; } catch { message('검사 화면으로 설정을 전달하지 못했습니다.', true); }
});
$('#deleteProject').addEventListener('click', () => {
  const project = current(); if (!project || !confirm(`“${project.name}” 프로젝트를 삭제할까요? 기존 검사 결과는 유지됩니다.`)) return;
  if (!saveProjects(projects.filter(item => item.id !== project.id))) return;
  selectedId = projects[0]?.id || null; fill(current()); renderList(); message('프로젝트를 삭제했습니다. 기존 검사 이력은 유지됩니다.');
});
fetch('/api/bootstrap', { cache: 'no-store' }).then(r => r.json()).then(b => { if (b.version) $('#versionPill').textContent = `v${b.version} · LOCAL`; }).catch(() => {});
fill(current()); renderList(); message(`${projects.length}개 프로젝트가 이 브라우저에 저장되어 있습니다.`);
