const $ = selector => document.querySelector(selector);
const STATUS = ['PASS', 'FAIL', 'DIFF', 'SKIP', 'BLOCKED', 'ERROR', 'REVIEW'];
const REVIEW_LABELS = { UNREVIEWED: '미검수', VERIFIED_OK: '정상 확인', BUG_CONFIRMED: '버그 확정', EXPECTED_DIFFERENCE: '정상 차이', FALSE_POSITIVE: '오탐', RETEST_REQUIRED: '재검 필요' };
const TYPE_LABELS = { comparison: '환경 비교 QA', single: '단일 환경 QA', regression: '회귀 테스트', conditional: '조건 기반 UI QA', UNSPECIFIED: '목적 기록 없음' };
const MODE_LABELS = { combined: '화면 + 등록된 기능', visual: '화면 비교', discovery: '탐색만 · 화면 비교 안 함', UNSPECIFIED: '모드 기록 없음' };
const SCOPE_LABELS = { approved_paths: '승인한 경로만', same_origin_readonly: '환경 내부 읽기 전용 링크 탐색' };
const ISSUE_LABELS = { JS_ERROR_AFTER_POLICY_BLOCK: '차단 후 JS 오류', CONSOLE_ERROR_AFTER_POLICY_BLOCK: '차단 후 콘솔 오류', REQUEST_ABORTED: '요청 중단 · 원인 미확정', REQUEST_CANCELLED_BY_RUNNER: '검사 도구가 취소한 요청' };
const ENV_LABELS = { a: '환경 A', b: '환경 B', comparison: 'A/B 비교', unknown: '환경 미기록' };
const CATEGORY_LABELS = { HTTP: 'HTTP 응답', NETWORK: '연결·전송', JAVASCRIPT: 'JavaScript', API: 'API 계약', RESOURCE: '이미지·정적 파일', NAVIGATION: '링크·이동', STRUCTURE: 'DOM·구조', FUNCTIONAL: '기능 동작', VISUAL: '시각·레이아웃', DATA: '데이터·표시 조건', AUTH: '인증·권한', TEST_INFRA: '검사 도구', UNREGISTERED: '분류 미등록' };
const REGRESSION_LABELS = { NEW: '신규 발견', RECURRING: '재발·지속', RESOLVED_CANDIDATE: '해결 후보', NOT_RETESTED: '재검되지 않음', NON_COMPARABLE: '비교 불가', UNEVALUATED: '회귀 미평가' };
const SELECT_FILTERS = ['regionFilter', 'testTypeFilter', 'environmentFilter', 'categoryFilter', 'subtypeFilter', 'severityFilter', 'reviewStatusFilter', 'regressionFilter'];
const CONDITION_EXAMPLE = [{ id: 'notice.empty', case: 'empty', url_pattern: '/demo/*', selector: '#empty-state', kind: 'visible', expected: true, preconditions: [{ selector: '#notice-list li', kind: 'count', expected: { equals: 0 } }] }];
const JOB_LABELS = { running: '실행 중', awaiting_auth: '로그인 대기', done: '완료', cancelled: '중단', error: '실행 오류' };
const state = { token: '', profiles: [], jobs: [], selectedId: null, activeId: null, report: null, job: null, filter: 'ALL', polling: null, pollErrors: 0, submitting: false, findingMap: new Map() };

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = String(value);
    else if (key === 'hidden' || key === 'disabled') node[key] = Boolean(value);
    else node.setAttribute(key, String(value));
  }
  for (const child of children) if (child) node.append(child);
  return node;
}
function visible(node, show) { node.classList.toggle('hidden', !show); }
function showError(message) { $('#errorSection').textContent = message; visible($('#errorSection'), true); }
function clearError() { visible($('#errorSection'), false); }
function showSuccess(message) { $('#successSection').textContent = message; visible($('#successSection'), true); }
function asText(value) { if (value == null) return '—'; return typeof value === 'string' ? value : JSON.stringify(value, null, 2); }
function dateText(value) {
  if (!value) return '시각 정보 없음';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date);
}
function safeUrl(value, localOnly = false) {
  if (!value || typeof value !== 'string') return null;
  try {
    const url = new URL(value, location.origin);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    if (localOnly && url.origin !== location.origin) return null;
    return url.href;
  } catch { return null; }
}
function link(value, title) {
  const href = safeUrl(value);
  return href ? el('a', { href, target: '_blank', rel: 'noopener noreferrer', text: title || value }) : el('span', { text: title || value || 'URL 없음' });
}
function badge(status) { return el('span', { class: `status ${STATUS.includes(status) ? status : 'UNKNOWN'}`, text: status || '미기록' }); }
function numeric(value) { return typeof value === 'number' && Number.isFinite(value) ? value : null; }
function metric(value) { return numeric(value) ?? '—'; }

async function api(path, { method = 'GET', body, signal } = {}) {
  const headers = { Accept: 'application/json' };
  if (method !== 'GET') { headers['Content-Type'] = 'application/json'; headers['X-QA-Token'] = state.token; }
  const response = await fetch(path, { method, headers, body: body == null ? undefined : JSON.stringify(body), cache: 'no-store', signal });
  let data;
  try { data = await response.json(); } catch { throw new Error(`서버 응답을 읽을 수 없습니다. (HTTP ${response.status})`); }
  if (!response.ok) {
    const message = typeof data.error === 'string' ? data.error : data.error?.message || data.message || `요청이 실패했습니다. (HTTP ${response.status})`;
    const error = new Error(message); error.status = response.status; error.data = data; throw error;
  }
  return data;
}

function profileById(id) { return state.profiles.find(profile => profile.id === id); }
function profileLabel(id) { return profileById(id)?.label || id || '사용자 지정'; }
function localProjects() {
  try { const value = JSON.parse(localStorage.getItem('m_qa_projects_v1') || '[]'); return Array.isArray(value) ? value : []; }
  catch { return []; }
}
function selectedProject() { return localProjects().find(project => project.id === $('#projectId').value); }
function registeredEnvironments() {
  const project = selectedProject();
  if (project) return (Array.isArray(project.environments) ? project.environments : []).filter(item => item?.id && item?.name && item?.url)
    .map(item => ({ id: `project:${item.id}`, label: item.name, url: item.url }));
  const entries = profileById($('#profileId').value)?.environments;
  return Array.isArray(entries) ? entries : [];
}
function populateProjects(preferred = '') {
  const select = $('#projectId');
  select.replaceChildren(el('option', { value: '', text: '프로젝트 선택 안 함' }));
  for (const project of localProjects().filter(item => item?.id && item?.name)) select.append(el('option', { value: project.id, text: project.name }));
  select.value = [...select.options].some(option => option.value === preferred) ? preferred : '';
}
function chooseProject() {
  const project = selectedProject();
  if (!project) { applyProfile(); return; }
  $('#profileId').value = 'custom';
  applyProfile();
  const environments = registeredEnvironments();
  for (const [side, entry] of [['baseline', environments[0]], ['candidate', environments[1]]]) {
    if (entry) { $(`#${side}EnvironmentId`).value = entry.id; chooseEnvironment(side); }
  }
  if (!environments[1]) $('#testType').value = 'single';
  updateTestType();
}
function syncEnvironmentSelection(side) {
  const value = $(`#${side}Url`).value.trim();
  const entry = registeredEnvironments().find(environment => environment.url === value);
  $(`#${side}EnvironmentId`).value = entry?.id || 'custom';
}
function chooseEnvironment(side) {
  const entry = registeredEnvironments().find(environment => environment.id === $(`#${side}EnvironmentId`).value);
  if (entry) { $(`#${side}Url`).value = entry.url; $(`#${side}Name`).value = entry.label || entry.id; }
  updateCrawlScopeHint();
}
function populateEnvironmentSelectors(profile) {
  const environments = registeredEnvironments();
  for (const side of ['baseline', 'candidate']) {
    const select = $(`#${side}EnvironmentId`);
    select.replaceChildren(el('option', { value: 'custom', text: environments.length ? '직접 입력' : '직접 입력 · 등록 환경 없음' }));
    for (const entry of environments) select.append(el('option', { value: entry.id, text: entry.label || entry.id }));
    const defaultId = selectedProject() ? null : profile[`${side}EnvironmentId`] || profile.defaults?.[`${side}EnvironmentId`];
    if (environments.some(entry => entry.id === defaultId)) { select.value = defaultId; chooseEnvironment(side); }
    else syncEnvironmentSelection(side);
  }
}
function reportType(report = state.report, job = state.job) { return report?.testType || job?.testType || report?.manifest?.testType || 'UNSPECIFIED'; }
function reportMode(report = state.report, job = state.job) { return report?.mode || report?.manifest?.mode || job?.mode || job?.options?.mode || 'UNSPECIFIED'; }
function environmentName(side, report = state.report, job = state.job) {
  const key = side === 'a' ? 'baseline' : 'candidate';
  return report?.inventory?.environments?.find(item => item.id === side)?.name || job?.options?.[`${key}_name`] || job?.options?.[`${key}Name`] || side.toUpperCase();
}
function differenceText(value) { const difference = numeric(value); return difference == null ? reportMode() === 'discovery' ? '미계산 · 탐색만' : '비교 불가' : `${difference.toFixed(2)}%`; }
function canonicalEnvironment(value) { return ({ baseline: 'a', candidate: 'b', both: 'comparison' })[value] || value || 'unknown'; }
function rowFindings(item) { return (item.findingIds || []).map(id => state.findingMap.get(id)).filter(Boolean); }
function rowMeta(item) {
  const findings = rowFindings(item);
  const unique = values => [...new Set(values.filter(Boolean))];
  const environmentValues = findings.map(finding => finding.environment);
  if (!environmentValues.length) {
    if (item.environment) environmentValues.push(item.environment);
    else { if (item.baseline) environmentValues.push('a'); if (item.candidate) environmentValues.push('b'); }
  }
  return { findings, environments: unique(environmentValues.map(canonicalEnvironment)), categories: unique(item.categories?.length ? item.categories : findings.map(f => f.category)), subtypes: unique(item.subtypes?.length ? item.subtypes : findings.map(f => f.subtype)), severity: item.severity || findings[0]?.severity || 'UNEVALUATED', regression: item.regression?.classification || 'UNEVALUATED', regressions: item.regression?.classifications?.length ? item.regression.classifications : [item.regression?.classification || 'UNEVALUATED'] };
}
function reviewIssue(item) { return item.review?.issueRef || item.issueRef || ''; }
function absoluteIssueUrl(value) { try { const parsed = new URL(value); return ['http:', 'https:'].includes(parsed.protocol) && !parsed.username && !parsed.password ? parsed.href : null; } catch { return null; } }
function selectOptions(id, values, labels = {}, emptyLabel = '모두') {
  const select = $(`#${id}`), previous = select.value;
  select.replaceChildren(el('option', { value: 'ALL', text: emptyLabel }));
  for (const value of [...new Set(values)].filter(Boolean)) select.append(el('option', { value, text: labels[value] || value }));
  select.value = [...select.options].some(option => option.value === previous) ? previous : 'ALL';
}

function updateTestType() {
  const type = $('#testType').value, comparison = type === 'comparison';
  visible($('#candidateField'), comparison); $('#candidateUrl').required = comparison; $('#candidateUrl').disabled = !comparison;
  visible($('#candidateNameField'), comparison); $('#candidateName').required = comparison; $('#candidateName').disabled = !comparison;
  visible($('#candidateEnvironmentField'), comparison); $('#candidateEnvironmentId').disabled = !comparison;
  document.querySelector('.environment-registry-fields').classList.toggle('single-target', !comparison);
  document.querySelector('.environment-fields').classList.toggle('single-target', !comparison);
  visible($('#pairStartPagesField'), comparison); $('#pairStartPages').disabled = !comparison;
  $('#baselineLabel').textContent = comparison ? '기준 A URL' : '검사 대상 A URL';
  document.querySelector('.url-fields').classList.toggle('single-target', !comparison);
  visible($('#rememberedIdBField'), comparison);
  visible($('#previousRunField'), type === 'regression'); $('#previousRunId').disabled = type !== 'regression'; $('#previousRunId').required = type === 'regression';
  visible($('#conditionsPanel'), type === 'conditional');
  $('#conditions').disabled = type !== 'conditional';
  $('#testTypeHint').textContent = { comparison: '동일 제품의 A/B를 각각 검사한 뒤 승인된 페이지와 영역을 비교합니다.', single: '대상 A만 방문해 HTTP·JS·리소스와 등록된 계약을 검사합니다. B와 비교하지 않습니다.', regression: '대상 A를 새로 검사한 뒤 선택한 과거 실행과 비교합니다. 범위·규칙·화면 조건이 다르면 비교 불가이며, 누락을 해결로 확정하지 않습니다.', conditional: '대상 A의 현재 화면에서 명시한 조건과 기대값을 읽기 전용으로 검사합니다.' }[type];
  updateRememberedInputs();
  updateCrawlScopeHint();
}
function updateCrawlScopeHint() {
  const origins = ['baselineUrl', ...($('#testType').value === 'comparison' ? ['candidateUrl'] : [])].map((id, index) => {
    try { const url = new URL($(`#${id}`).value); return `${index ? 'B' : 'A'}: ${url.origin}`; } catch { return `${index ? 'B' : 'A'}: URL 입력 필요`; }
  }).join(' · ');
  $('#crawlScopeHint').textContent = `${SCOPE_LABELS[$('#crawlScope').value] || '탐색 범위 확인 필요'} · ${origins}`;
}
function updatePreviousRuns() {
  const select = $('#previousRunId'), previous = select.value;
  select.replaceChildren(el('option', { value: '', text: '과거 실행을 선택하세요' }));
  for (const job of state.jobs.filter(job => job.state === 'done')) select.append(el('option', { value: job.id, text: `${dateText(job.startedAt)} · ${job.operatorId || '담당자 미기록'} · ${TYPE_LABELS[job.testType] || '이전 실행'} · ${String(job.id).slice(0, 8)}` }));
  if ([...select.options].some(option => option.value === previous)) select.value = previous;
}
function updateStartButton() {
  $('#startBtn').disabled = !state.token || Boolean(state.activeId) || state.submitting || Boolean(profileById($('#profileId').value)?.disabled);
  $('#startText').textContent = state.submitting ? '검사 시작 중…' : state.activeId ? '검사 진행 중' : '검사 시작';
  $('#loadRunSettings').disabled = !state.job?.options || Boolean(state.activeId);
  $('#configureVisualMode').disabled = !state.job?.options || Boolean(state.activeId);
}

function applyProfile({ restoreRememberedIds = true } = {}) {
  const profile = profileById($('#profileId').value);
  if (!profile) return;
  const defaults = profile.defaults || {};
  $('#maxActions').max = profile.id === 'synthetic-demo' ? '200' : '50';
  $('#baselineUrl').value = profile.baselineUrl || defaults.baselineUrl || '';
  $('#candidateUrl').value = profile.candidateUrl || defaults.candidateUrl || '';
  $('#baselineName').value = defaults.baselineName || profile.baselineName || 'A';
  $('#candidateName').value = defaults.candidateName || profile.candidateName || 'B';
  $('#crawlScope').value = defaults.crawlScope || profile.crawlScope || 'approved_paths';
  populateEnvironmentSelectors(profile);
  $('#profileHint').textContent = profile.description || '등록한 시작 URL과 승인된 동작만 검사합니다.';
  const fallback = { mode: 'combined', maxPages: 10, maxDepth: 2, maxActions: 20, timeoutSeconds: 300, visualThreshold: 2 };
  for (const [name, value] of Object.entries(fallback)) $(`#${name}`).value = defaults[name] ?? value;
  $('#pairStartPages').checked = defaults.pairStartPages ?? profile.pairStartPages ?? true;
  for (const name of ['aliases', 'regions', 'safeActions', 'scenarioIds', 'conditions', 'privateMaskSelectors']) $(`#${name}`).value = JSON.stringify(defaults[name] || profile[name] || [], null, 2);
  for (const name of ['allowedPaths', 'allowedHosts', 'resourceHosts']) $(`#${name}`).value = (defaults[name] || profile[name] || []).join('\n');
  $('#manualLogin').checked = defaults.manualLogin ?? false;
  if (restoreRememberedIds) loadRememberedIds();
  updateTestType();
  updateStartButton();
}

function loadRunSettings({ visual = false } = {}) {
  const job = state.job, options = job?.options;
  if (!options || typeof options !== 'object') { showError('이 실행에는 원래 설정이 저장되어 있지 않습니다. 검사 설정을 직접 확인해 주세요.'); return; }
  const read = (snake, camel) => options[snake] ?? options[camel];
  const profileId = read('profile_id', 'profileId') || job.profileId;
  $('#projectId').value = '';
  $('#profileId').value = profileById(profileId) ? profileId : 'custom';
  $('#testType').value = read('test_type', 'testType') || job.testType || job.report?.testType || 'comparison';
  $('#previousRunId').value = '';
  applyProfile({ restoreRememberedIds: false });
  const fields = { baselineUrl: 'baseline_url', candidateUrl: 'candidate_url', baselineName: 'baseline_name', candidateName: 'candidate_name', crawlScope: 'crawl_scope', operatorId: 'operator_id', testType: 'test_type', previousRunId: 'previous_run_id', mode: 'mode', maxPages: 'max_pages', maxDepth: 'max_depth', maxActions: 'max_actions', timeoutSeconds: 'timeout_seconds', visualThreshold: 'visual_threshold' };
  for (const [id, snake] of Object.entries(fields)) {
    const value = read(snake, id);
    if (value != null) $(`#${id}`).value = value;
  }
  if (!Object.keys(TYPE_LABELS).includes($('#testType').value)) $('#testType').value = 'comparison';
  for (const [id, snake] of Object.entries({ pairStartPages: 'pair_start_pages', manualLogin: 'manual_login' })) {
    const value = read(snake, id);
    if (typeof value === 'boolean') $(`#${id}`).checked = value;
  }
  const jsonFields = { aliases: 'route_aliases', regions: 'regions', safeActions: 'safe_actions', scenarioIds: 'scenario_ids', conditions: 'conditions', privateMaskSelectors: 'private_mask_selectors' };
  for (const [id, snake] of Object.entries(jsonFields)) {
    const value = read(snake, id);
    if (Array.isArray(value)) $(`#${id}`).value = JSON.stringify(value, null, 2);
  }
  for (const [id, snake] of Object.entries({ allowedPaths: 'allowed_paths', allowedHosts: 'allowed_hosts', resourceHosts: 'resource_hosts' })) {
    const value = read(snake, id);
    if (Array.isArray(value)) $(`#${id}`).value = value.join('\n');
  }
  if (visual) $('#mode').value = 'visual';
  syncEnvironmentSelection('baseline'); syncEnvironmentSelection('candidate');
  updateTestType(); updateStartButton(); clearError();
  $('#settingsTitle').scrollIntoView({ behavior: 'smooth', block: 'start' });
  showSuccess(`실행 ${String(job.id).slice(0, 8)}의 입력 설정을 불러왔습니다.${visual ? ' 검사 모드를 화면 비교로 변경했습니다.' : ''} 새 옵션의 기록이 없으면 현재 프로필 기본값을 사용합니다. 설정을 확인한 뒤 검사 시작을 눌러 주세요. 자동으로 실행하지 않았으며 저장된 결과는 유지됩니다.`);
}

function rememberKey() {
  const operator = $('#operatorId').value.trim();
  const profile = $('#profileId').value;
  return operator && profile ? `qa-comparator.ids.v1:${encodeURIComponent(operator)}:${encodeURIComponent(profile)}` : null;
}
function loadRememberedIds() {
  let saved = null;
  try { const key = rememberKey(); if (key) saved = JSON.parse(localStorage.getItem(key) || 'null'); } catch { /* Local storage may be unavailable. */ }
  $('#rememberIds').checked = Boolean(saved?.enabled);
  $('#rememberedIdA').value = typeof saved?.a === 'string' ? saved.a : '';
  $('#rememberedIdB').value = typeof saved?.b === 'string' ? saved.b : '';
  updateRememberedInputs();
}
function updateRememberedInputs() {
  const enabled = $('#rememberIds').checked;
  $('#rememberedIdA').disabled = !enabled;
  $('#rememberedIdB').disabled = !enabled || $('#testType').value !== 'comparison';
}
function saveRememberedIds() {
  const key = rememberKey();
  if (!key) { if ($('#rememberIds').checked) showError('아이디를 기억하려면 실행 담당자와 프로필을 먼저 입력해 주세요.'); return; }
  try {
    if ($('#rememberIds').checked) localStorage.setItem(key, JSON.stringify({ enabled: true, a: $('#rememberedIdA').value, b: $('#rememberedIdB').value }));
    else localStorage.removeItem(key);
  } catch { showError('이 브라우저에서 아이디 메모를 저장할 수 없습니다. 검사는 저장 없이 실행할 수 있습니다.'); }
}

function readArray(id) {
  let value;
  try { value = JSON.parse($(`#${id}`).value.trim() || '[]'); } catch { throw new Error(`고급 설정의 ${id}를 올바른 JSON 배열로 입력해 주세요.`); }
  if (!Array.isArray(value)) throw new Error(`고급 설정의 ${id}는 JSON 배열이어야 합니다.`);
  return value;
}
function buildPayload() {
  const payload = { profileId: $('#profileId').value, operatorId: $('#operatorId').value.trim(), baselineUrl: $('#baselineUrl').value.trim(), baselineName: $('#baselineName').value.trim(), baselineEnvironmentId: $('#baselineEnvironmentId').value.startsWith('project:') ? 'custom' : $('#baselineEnvironmentId').value, crawlScope: $('#crawlScope').value, testType: $('#testType').value, mode: $('#mode').value, manualLogin: $('#manualLogin').checked };
  if (!payload.operatorId) throw new Error('실행 담당자를 입력해 주세요.');
  if (!payload.baselineName) throw new Error('A 환경 이름을 입력해 주세요.');
  if (!safeUrl(payload.baselineUrl)) throw new Error('아이디·비밀번호를 포함하지 않은 http 또는 https 대상 URL을 입력해 주세요.');
  if (payload.testType === 'comparison') { payload.candidateUrl = $('#candidateUrl').value.trim(); payload.candidateName = $('#candidateName').value.trim(); payload.candidateEnvironmentId = $('#candidateEnvironmentId').value.startsWith('project:') ? 'custom' : $('#candidateEnvironmentId').value; payload.pairStartPages = $('#pairStartPages').checked; if (!safeUrl(payload.candidateUrl)) throw new Error('올바른 비교 B URL을 입력해 주세요.'); if (!payload.candidateName) throw new Error('B 환경 이름을 입력해 주세요.'); }
  if (payload.testType === 'regression') { payload.previousRunId = $('#previousRunId').value; if (!payload.previousRunId) throw new Error('회귀 비교의 기준이 될 과거 실행을 선택해 주세요.'); }
  if (payload.testType === 'conditional') { payload.conditions = readArray('conditions'); if (!payload.conditions.length) throw new Error('조건 기반 검사에 사용할 conditions를 한 개 이상 입력해 주세요.'); }
  for (const name of ['maxPages', 'maxDepth', 'maxActions', 'timeoutSeconds', 'visualThreshold']) payload[name] = Number($(`#${name}`).value);
  for (const name of ['aliases', 'regions', 'safeActions', 'scenarioIds', 'privateMaskSelectors']) payload[name] = readArray(name);
  if (payload.privateMaskSelectors.length > 30 || payload.privateMaskSelectors.some(selector => typeof selector !== 'string' || !selector.trim())) throw new Error('privateMaskSelectors는 비어 있지 않은 선택자 문자열을 최대 30개까지 입력할 수 있습니다.');
  for (const name of ['allowedPaths', 'allowedHosts', 'resourceHosts']) payload[name] = $(`#${name}`).value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
  if (payload.allowedPaths.some(value => ['*', '/*', '**', '/**'].includes(value)) || [...payload.allowedHosts, ...payload.resourceHosts].some(value => value.includes('*'))) throw new Error('전체 허용(*) 대신 검토한 경로와 정확한 호스트를 입력해 주세요.');
  if (payload.scenarioIds.some(id => typeof id !== 'string')) throw new Error('scenarioIds는 문자열 ID 배열이어야 합니다.');
  return payload;
}

async function refreshHistory() {
  const data = await api('/api/scans');
  state.jobs = Array.isArray(data.scans) ? data.scans : [];
  renderHistory();
  updatePreviousRuns();
  return state.jobs;
}
function renderHistory() {
  const list = $('#historyList'); list.replaceChildren();
  if (!state.jobs.length) { list.append(el('p', { class: 'empty compact', text: '아직 실행 기록이 없습니다. 합성 데모로 첫 검사를 시작해 보세요.' })); return; }
  for (const job of state.jobs) {
    const button = el('button', { type: 'button', class: `history-item${state.selectedId === job.id ? ' selected' : ''}`, 'aria-label': `${profileLabel(job.profileId)} ${dateText(job.startedAt)} 실행 열기` });
    button.append(el('div', { class: 'history-top' }, [el('span', { class: 'history-title', text: profileLabel(job.profileId || job.report?.profileId) }), el('span', { class: `job-state ${job.state || ''}`, text: JOB_LABELS[job.state] || job.state || '기록' })]));
    button.append(el('div', { class: 'history-meta', text: `${job.operatorId || job.report?.operatorId || '담당자 정보 없음'} · ${dateText(job.startedAt)}\n${TYPE_LABELS[job.testType || job.report?.testType] || '목적 기록 없음'} · ${String(job.id || '').slice(0, 8)}` }));
    button.addEventListener('click', () => loadJob(job.id).catch(error => showError(error.message)));
    list.append(button);
  }
}

function updateProgress(job) {
  const active = ['running', 'awaiting_auth'].includes(job.state);
  if (!active) { if (state.activeId === job.id) visible($('#progressSection'), false); return; }
  visible($('#progressSection'), true);
  $('#progressTitle').textContent = job.state === 'awaiting_auth' ? '수동 로그인 대기' : '검사 실행 중';
  $('#progressMeta').textContent = `${job.operatorId || '담당자'} · ${profileLabel(job.profileId)} · ${dateText(job.startedAt)}`;
  $('#progressText').textContent = job.progress || '검사를 진행하고 있습니다.';
  visible($('#authPanel'), job.state === 'awaiting_auth');
  const side = ['a', 'baseline'].includes(String(job.authSide).toLowerCase()) ? '기준 A' : ['b', 'candidate'].includes(String(job.authSide).toLowerCase()) ? '비교 B' : job.authSide || '현재';
  $('#authText').textContent = `${side} 환경의 열린 브라우저에서 직접 로그인해 주세요. 직접 로그인을 확인한 뒤 계속을 누르면 검사를 진행합니다.`;
  $('#continueBtn').disabled = false;
  $('#cancelBtn').disabled = false;
}
async function loadJob(id, { scroll = true } = {}) {
  const job = await api(`/api/scans/${encodeURIComponent(id)}`);
  state.selectedId = id; state.job = job;
  if (job.report) renderReport(job.report, job); else { state.report = null; visible($('#resultSection'), false); }
  if (['running', 'awaiting_auth'].includes(job.state)) { state.activeId = id; updateProgress(job); startPolling(id); }
  else if (state.activeId === id) { state.activeId = null; if (state.polling?.id === id) { clearTimeout(state.polling.timer); state.polling = null; } visible($('#progressSection'), false); }
  if (job.error && job.state === 'error') showError(job.error);
  renderHistory(); updateStartButton();
  if (scroll && job.report) $('#resultSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
  return job;
}
function startPolling(id) {
  if (state.polling?.id === id) return;
  if (state.polling) clearTimeout(state.polling.timer);
  state.polling = { id, timer: null };
  state.pollErrors = 0;
  schedulePoll(id);
}
function schedulePoll(id) {
  if (state.polling?.id !== id) return;
  state.polling.timer = setTimeout(() => pollJob(id), 1200);
}
async function pollJob(id) {
  if (state.polling?.id !== id) return;
  try {
    const job = await api(`/api/scans/${encodeURIComponent(id)}`);
    state.pollErrors = 0;
    updateProgress(job);
    if (state.selectedId === id) { state.job = job; if (job.report && (!state.report || ['done', 'cancelled', 'error'].includes(job.state))) renderReport(job.report, job); }
    if (['done', 'cancelled', 'error'].includes(job.state)) {
      state.activeId = null; state.polling = null; updateStartButton();
      visible($('#progressSection'), false);
      if (job.state === 'error') showError(job.error || '검사 실행 중 오류가 발생했습니다.');
      if (job.state === 'cancelled') showSuccess('실행을 중단했습니다. 수집된 결과가 있으면 미완료 상태와 함께 표시합니다.');
      await refreshHistory();
      return;
    }
  } catch (error) {
    state.pollErrors += 1;
    $('#progressText').textContent = `상태 조회를 다시 시도합니다. (${state.pollErrors}회) ${error.message}`;
    if (state.pollErrors >= 5) showError('서버 상태를 조회하지 못하고 있습니다. 검사 완료로 처리하지 않았습니다. 연결을 확인하거나 실행 이력을 새로고침해 주세요.');
  }
  schedulePoll(id);
}

function renderIssues(items = []) {
  const list = el('div', { class: 'error-list' });
  if (!items.length) { list.append(el('span', { class: 'mini-meta', text: '수집된 관찰 오류 없음 · 기능 전체 통과를 뜻하지 않습니다.' })); return list; }
  for (const item of items) {
    const row = el('div', { class: `error-item ${STATUS.includes(item.level) ? item.level : ''}` });
    row.append(el('span', { class: 'error-type', text: `[${ISSUE_LABELS[item.category] || item.category || 'OBSERVATION'}]` }), el('span', { text: item.message || item.reason || '' }));
    if (item.policyInterference || ['JS_ERROR_AFTER_POLICY_BLOCK', 'CONSOLE_ERROR_AFTER_POLICY_BLOCK'].includes(item.category)) row.append(el('p', { class: 'mini-meta', text: `${item.category} · 정책 영향 가능성 / 원인 미확정. 차단 이후에 관찰됐다는 전후관계이며, 차단이 원인이라고 확정하지 않습니다.` }));
    const cause = item.cause || item.causeCandidate || item.causeCandidates;
    if (cause) row.append(el('p', { class: 'mini-meta', text: `원인 관련 근거: ${asText(cause)}` }));
    if (item.relatedBlockedRequests?.length) row.append(el('p', { class: 'mini-meta', text: `관련 차단 요청: ${asText(item.relatedBlockedRequests)}` }));
    if (item.url) row.append(el('div', { class: 'mini-meta' }, [link(item.url)]));
    list.append(row);
  }
  return list;
}
function renderSite(site, name) {
  const box = el('div', { class: 'detail-box' }, [el('h4', { text: name })]);
  if (!site) { box.append(el('p', { class: 'mini-meta', text: '이 환경에서 대응 페이지를 확인하지 못했습니다. 미발견은 페이지가 없다는 확정 판정이 아닙니다.' })); return box; }
  box.append(link(site.url), el('p', { class: 'mini-meta', text: `HTTP ${site.statusCode ?? '—'} · ${site.title || '제목 정보 없음'}` }));
  if (site.finalUrl && site.finalUrl !== site.url) box.append(el('p', { class: 'mini-meta' }, [el('span', { text: '최종 URL: ' }), link(site.finalUrl)]));
  box.append(renderIssues(site.issues));
  return box;
}
function imageCard(value, title, emptyText = '이미지 없음 / 비교 불가') {
  const url = safeUrl(value, true);
  if (!url) return el('figure', { class: 'screenshot' }, [el('div', { class: 'screenshot-placeholder', text: emptyText }), el('figcaption', { text: title })]);
  const card = el('a', { class: 'screenshot', href: url, target: '_blank', rel: 'noopener noreferrer' });
  const img = el('img', { src: url, loading: 'lazy', alt: `${title} 증거 이미지` });
  img.addEventListener('error', () => { img.replaceWith(el('div', { class: 'screenshot-placeholder', text: '증거 이미지를 불러올 수 없습니다.' })); }, { once: true });
  card.append(img, el('figcaption', { text: `${title} · 확대 보기` })); return card;
}
function renderChecks(checks = []) {
  const list = el('div', { class: 'check-list' });
  if (!checks.length) { list.append(el('p', { class: 'mini-meta', text: '기능 assertion 기록이 없습니다. 페이지 방문만으로 기능을 PASS 처리하지 않습니다.' })); return list; }
  for (const check of checks) {
    const row = el('div', { class: 'check-item' });
    row.append(el('div', { class: 'check-top' }, [el('span', { class: 'check-name', text: check.check_id || check.id || '검증 항목' }), badge(check.status)]));
    row.append(el('p', { class: 'check-reason', text: [check.scenario_id, check.step_id, check.reason_code, check.message || check.reason].filter(Boolean).join(' · ') }));
    if (check.preconditions != null) row.append(el('div', { class: 'value-block' }, [el('span', { text: '사전 조건' }), el('pre', { text: asText(check.preconditions) })]));
    if (check.expected != null || check.actual != null) row.append(el('div', { class: 'values-grid' }, [el('div', { class: 'value-block' }, [el('span', { text: '기대 결과' }), el('pre', { text: asText(check.expected) })]), el('div', { class: 'value-block' }, [el('span', { text: '실제 결과' }), el('pre', { text: asText(check.actual) })])]));
    const evidence = Array.isArray(check.evidence) ? check.evidence : [];
    for (const item of evidence) {
      const path = typeof item === 'string' ? item : item.url || item.path;
      const href = safeUrl(path, true);
      if (href) row.append(el('p', { class: 'mini-meta' }, [link(href, '검증 증거 보기')]));
    }
    list.append(row);
  }
  return list;
}
function renderFindings(item) {
  const findings = rowFindings(item);
  const box = el('div', { class: 'finding-list' });
  if (!findings.length) { box.append(el('p', { class: 'mini-meta', text: Array.isArray(state.report?.findings) ? '이 행에 연결된 구조화 발견 사항이 없습니다. 검증식과 관찰 로그를 함께 확인하세요.' : '이전 보고서에 구조화 분류가 기록되지 않았습니다. 당시 자동 상태와 원본 관찰을 그대로 표시합니다.' })); return box; }
  for (const finding of findings) {
    const card = el('article', { class: 'finding-card' });
    card.append(el('div', { class: 'check-top' }, [el('strong', { class: 'check-name', text: finding.summary || finding.subtype || '발견 사항' }), badge(finding.status)]));
    card.append(el('p', { class: 'finding-meta', text: `${CATEGORY_LABELS[finding.category] || finding.category || '분류 미등록'} / ${finding.subtype || '유형 미등록'} · ${finding.severity || '심각도 미평가'} · ${ENV_LABELS[canonicalEnvironment(finding.environment)] || finding.environment}` }));
    card.append(el('p', { class: 'mini-meta', text: `관찰 ${metric(finding.occurrenceCount)}회 · 최초 ${dateText(finding.firstSeenAt)} · 최근 ${dateText(finding.lastSeenAt)}` }));
    card.append(el('p', { class: 'mini-meta', text: [finding.checkId, finding.scenarioId, finding.stepId].filter(Boolean).join(' · ') }));
    if (finding.tags?.length) card.append(el('div', { class: 'tags' }, finding.tags.map(tag => el('span', { class: 'tag', text: asText(tag) }))));
    const candidates = finding.causeCandidates || finding.cause_candidates;
    card.append(el('p', { class: 'mini-meta', text: candidates?.length ? `원인 후보: ${asText(candidates)}` : '원인 후보 미평가 · 같은 원인으로 확정하지 않습니다.' }));
    if (finding.policyInterference || finding.subtype === 'POLICY_INTERFERENCE') card.append(el('p', { class: 'mini-meta', text: '정책 영향 가능성 / 원인 미확정 · 차단 뒤 관찰된 오류이며 앱 결함이나 인과관계가 확정된 것은 아닙니다.' }));
    if (Array.isArray(finding.observations) && finding.observations.length) {
      const observations = el('details', { class: 'sub-details' }, [el('summary', { text: '원시 관찰과 관련 차단 요청 보기' })]);
      observations.append(renderIssues(finding.observations)); card.append(observations);
    }
    for (const evidence of Array.isArray(finding.evidence) ? finding.evidence : []) {
      const url = typeof evidence === 'string' ? evidence : evidence.url || evidence.path;
      if (safeUrl(url, true)) card.append(el('p', { class: 'mini-meta' }, [link(url, '연결된 증거 보기')]));
    }
    box.append(card);
  }
  return box;
}
function actionList(item) {
  return [['기준 A', item.baseline], ['비교 B', item.candidate]].flatMap(([side, site]) => (site?.actions || []).map(action => ({ ...action, side })));
}
function renderActions(item) {
  const actions = actionList(item);
  const details = el('details', { class: 'sub-details' }, [el('summary', { text: `발견한 버튼·링크와 실행 제외 사유 (${actions.length})` })]);
  const list = el('div', { class: 'inventory-list' });
  if (!actions.length) list.append(el('p', { class: 'mini-meta', text: '기록된 동작 후보가 없습니다. 모든 클릭 가능 요소를 검사했다는 뜻은 아닙니다.' }));
  for (const action of actions) {
    const row = el('div', { class: 'inventory-item' });
    const name = action.name || action.text || action.label || action.selector || action.href || action.id || '이름 없는 요소';
    const status = action.status || action.state || (action.executed ? '실행됨' : action.allowed ? '허용됨' : 'SKIP');
    row.append(el('div', { class: 'inventory-top' }, [el('span', { class: 'inventory-name', text: `${action.side} · ${name}` }), el('span', { class: 'tag', text: status })]));
    row.append(el('p', { class: 'check-reason', text: [action.type || action.role, action.risk, action.reason_code || action.reason, action.selector].filter(Boolean).join(' · ') }));
    list.append(row);
  }
  details.append(list); return details;
}
function renderReview(item) {
  const runId = state.selectedId;
  const review = item.review || { status: 'UNREVIEWED', revision: 0, events: [] };
  const box = el('section', { class: 'review-box' }, [el('h4', { text: `QA 최종 검수 · ${REVIEW_LABELS[review.status] || review.status} · v${review.revision ?? 0}` })]);
  const form = el('form', { class: 'review-form' });
  const reviewer = el('input', { required: true, maxlength: '50', autocomplete: 'off', 'aria-label': '검수 담당자' }); reviewer.value = $('#operatorId').value || state.job?.operatorId || '';
  const select = el('select', { 'aria-label': '최종 검수 상태', required: true });
  for (const [value, label] of Object.entries(REVIEW_LABELS)) select.append(el('option', { value: value === 'UNREVIEWED' ? '' : value, text: label, disabled: value === 'UNREVIEWED' }));
  select.value = review.status && review.status !== 'UNREVIEWED' ? review.status : '';
  const reason = el('textarea', { rows: '1', required: true, maxlength: '2000', placeholder: '판정 근거 또는 재검 사유', 'aria-label': '검수 사유' });
  const issueRef = el('input', { type: 'url', maxlength: '2000', autocomplete: 'off', placeholder: '이미 등록한 이슈의 URL · 선택', 'aria-label': '기존 이슈 URL' }); issueRef.value = reviewIssue(item);
  const button = el('button', { type: 'submit', class: 'secondary', text: '검수 저장' });
  form.append(el('label', { class: 'field' }, [el('span', { text: '검수 담당자' }), reviewer]), el('label', { class: 'field' }, [el('span', { text: '최종 검수' }), select]), el('label', { class: 'field reason-field' }, [el('span', { text: '사유' }), reason]), el('label', { class: 'field issue-field' }, [el('span', { text: '기존 이슈 연결 · 자동 등록하지 않음' }), issueRef]), button);
  const feedback = el('p', { class: 'review-feedback hidden', role: 'status' });
  form.addEventListener('submit', async event => {
    event.preventDefault(); button.disabled = true;
    const resultId = item.id || item.result_id;
    try {
      if (!resultId) throw new Error('결과 식별자가 없어 검수를 저장할 수 없습니다.');
      if (!reviewer.value.trim() || !reason.value.trim()) throw new Error('검수 담당자와 사유를 입력해 주세요.');
      if (issueRef.value.trim() && !absoluteIssueUrl(issueRef.value.trim())) throw new Error('기존 이슈의 http 또는 https URL을 입력해 주세요. 자격증명이 포함된 URL은 사용할 수 없습니다.');
      await api(`/api/scans/${encodeURIComponent(runId)}/reviews`, { method: 'POST', body: { resultId, reviewer: reviewer.value.trim(), status: select.value, reason: reason.value.trim(), issueRef: issueRef.value.trim(), expectedRevision: review.revision ?? 0 } });
      const job = await api(`/api/scans/${encodeURIComponent(runId)}`);
      const updated = job.report?.results?.find(result => (result.id || result.result_id) === resultId);
      if (updated && state.selectedId === runId) { Object.assign(item, updated); renderReport(job.report, job); const index = job.report.results.indexOf(updated); const row = $(`#result-row-${index}`); if (row) row.open = true; }
      showSuccess('검수 이력을 저장했습니다. 자동 검사 판정은 유지됩니다.');
    } catch (error) {
      feedback.textContent = error.status === 409 ? '다른 담당자가 먼저 검수했습니다. 현재 결과를 다시 열어 최신 검수 이력을 확인한 뒤 저장해 주세요. 입력한 사유는 유지됩니다.' : error.message;
      feedback.classList.add('error'); visible(feedback, true);
    } finally { button.disabled = false; }
  });
  box.append(form, feedback);
  box.append(el('p', { class: 'mini-meta' }, reviewIssue(item) ? [el('span', { text: '연결된 이슈: ' }), link(reviewIssue(item), '기존 이슈 열기')] : [el('span', { text: '이슈 미등록 · 연결 여부는 외부 서비스에서 자동 확인하지 않습니다.' })]));
  const events = Array.isArray(review.events) ? review.events : [];
  if (events.length) {
    const history = el('details', { class: 'sub-details review-history' }, [el('summary', { text: `검수 이력 ${events.length}건` })]);
    for (const event of [...events].reverse()) {
      const entry = el('div', { class: 'review-event', text: `${event.reviewer || event.actor || '담당자'} · ${REVIEW_LABELS[event.status || event.new_status] || event.status || event.new_status || ''} · ${dateText(event.timestamp || event.createdAt)}\n${event.reason || ''}` });
      if (event.issueRef) entry.append(el('div', {}, [link(event.issueRef, '당시 연결한 이슈')]));
      history.append(entry);
    }
    box.append(history);
  }
  return box;
}
function rowFor(item, index) {
  const meta = rowMeta(item);
  const row = el('details', { class: 'result-row', id: `result-row-${index}` });
  const main = el('summary', { class: 'row-main' });
  const paired = Boolean(item.baseline && item.candidate);
  const titleSummary = paired ? `A: ${item.baseline.title || '제목 미기록'} / B: ${item.candidate.title || '제목 미기록'}` : item.baseline ? `A: ${item.baseline.title || '제목 미기록'}` : item.candidate ? `B: ${item.candidate.title || '제목 미기록'}` : '제목 정보 없음';
  const primary = el('div', {}, [el('div', { class: 'pathname', text: item.key === '__ROOT__' ? '홈 페이지' : item.key || item.page_class || '페이지' }), el('div', { class: 'desc', text: titleSummary })]);
  if (item.region_id) primary.append(el('div', { class: 'region-label', text: item.region_id }));
  primary.append(el('div', { class: 'observation-summary', text: meta.findings[0]?.summary || (item.checks || []).find(check => check.status !== 'PASS')?.reason_code || '구조화 관찰 요약 미등록' }));
  primary.append(el('div', { class: 'desc', text: `${paired ? 'A/B 대응 페이지 · ' : ''}관찰: ${meta.environments.map(value => ENV_LABELS[value] || value).join(' · ') || '환경 미기록'} · ${meta.regressions.map(value => REGRESSION_LABELS[value] || value).join(' / ')}` }));
  const flags = Array.isArray(item.flags) ? item.flags : [];
  const tags = el('div', { class: 'tags' });
  const summaryTags = meta.categories.length ? [...meta.categories.slice(0, 2).map(category => CATEGORY_LABELS[category] || category), meta.subtypes[0], meta.severity === 'UNEVALUATED' ? '심각도 미평가' : meta.severity].filter(Boolean) : flags.slice(0, 3);
  for (const tag of summaryTags) tags.append(el('span', { class: 'tag', text: tag }));
  if (!summaryTags.length) tags.append(el('span', { class: 'tag', text: '분류 미등록' }));
  const difference = numeric(item.visual?.differencePercent);
  main.append(primary, badge(item.status), tags, el('span', { class: 'diff-value', text: differenceText(item.visual?.differencePercent) }), el('span', { class: 'review-tag' }, [el('span', {}, [el('span', { text: REVIEW_LABELS[item.review?.status] || '미검수' }), el('span', { class: 'issue-state', text: reviewIssue(item) ? '이슈 연결됨' : '이슈 미등록' })]), el('span', { class: 'expand-mark', text: '⌄', 'aria-hidden': 'true' })]));
  const details = el('div', { class: 'details' });
  if (item.match) {
    const match = el('details', { class: 'sub-details match-details' }, [el('summary', { text: `매칭 이유 보기 · ${item.match.method || '미확정'}` })]);
    match.append(el('p', { class: 'mini-meta', text: `방법: ${item.match.method || '미기록'} · 확신도 ${item.match.confidence ?? '미기록'} · 대응 규칙 확정: ${item.match.approved === true ? '예' : item.match.approved === false ? '아니오' : '미기록'}` }));
    match.append(el('p', { class: 'mini-meta', text: `근거: ${asText(item.match.reason || item.match.reasons || item.match.evidence || '매칭 근거 미기록')}` }));
    if (item.match.method === 'SELECTED_START_PAGES') match.append(el('p', { class: 'mini-meta', text: '입력한 시작 URL 쌍을 같은 기능으로 비교하도록 설정한 결과입니다. 경로·제목이 달라도 시작 페이지끼리 연결하며, 그 밖의 탐색 페이지에는 이 규칙을 적용하지 않습니다.' }));
    details.append(match);
  }
  const type = reportType(), compare = type === 'comparison' || (type === 'UNSPECIFIED' && Boolean(item.candidate));
  if (item.regression) details.append(el('p', { class: 'mini-meta', text: `회귀: ${REGRESSION_LABELS[meta.regression] || meta.regression} · 과거 실행 ${state.report?.previousRunId || state.report?.regression?.previousRunId || state.job?.previousRunId || '참조 미기록'}` }));
  details.append(el('div', { class: `detail-grid${compare ? '' : ' single-target'}` }, compare ? [renderSite(item.baseline, '기준 A'), renderSite(item.candidate, '비교 B')] : [renderSite(item.baseline || item.candidate, type === 'regression' ? '현재 실행 · 대상 A' : '검사 대상 A')]));
  const images = compare ? [imageCard(item.baseline?.screenshot, '기준 A 화면'), imageCard(item.candidate?.screenshot, '비교 B 화면'), imageCard(item.visual?.url, '차이 영역', reportMode() === 'discovery' ? '탐색 모드에서는 차이 이미지를 만들지 않습니다.' : '이미지 없음 / 비교 불가')] : [imageCard((item.baseline || item.candidate)?.screenshot, type === 'regression' ? '현재 실행 화면' : '대상 A 화면')];
  details.append(el('h4', { class: 'evidence-title', text: `화면 증거${compare ? ` · ${difference == null ? differenceText(null) : `차이율 ${difference.toFixed(2)}%`}` : ''}` }), el('div', { class: `screenshot-grid${compare ? '' : ' single-target'}` }, images));
  if (item.visual?.note) details.append(el('p', { class: 'mini-meta', text: item.visual.note }));
  details.append(el('h4', { class: 'evidence-title', text: '연결된 발견 사항 · 중복 관찰과 근거' }), renderFindings(item), el('h4', { class: 'evidence-title', text: '실행한 검증식과 기대 결과' }), renderChecks(item.checks), renderActions(item), renderReview(item));
  row.append(main, details); return row;
}

function addMappingDraft(proposal) {
  try {
    if (state.activeId) throw new Error('현재 실행을 마친 뒤 매핑 설정을 변경해 주세요.');
    const environments = state.report?.inventory?.environments || [];
    const seedA = environments.find(item => item.id === 'a')?.seedUrl;
    const seedB = environments.find(item => item.id === 'b')?.seedUrl;
    if ($('#testType').value !== 'comparison' || !seedA || !seedB || safeUrl($('#baselineUrl').value.trim()) !== safeUrl(seedA) || safeUrl($('#candidateUrl').value.trim()) !== safeUrl(seedB)) throw new Error('이 페이지 목록의 A/B 시작 URL과 현재 검사 설정이 다릅니다. 먼저 ‘이 실행 설정 불러오기’를 누르거나 같은 A/B URL을 입력한 뒤 매핑을 추가해 주세요.');
    if (![proposal?.baseline, proposal?.candidate].every(value => typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') && value.length <= 500)) throw new Error('엔진이 기록한 A/B 페이지 키가 없어 매핑을 만들 수 없습니다. URL을 임의로 변환하지 않습니다.');
    const aliases = readArray('aliases');
    if (aliases.some(item => item?.baseline === proposal.baseline || item?.candidate === proposal.candidate)) throw new Error('이 A 또는 B 페이지 키가 기존 매핑에 있습니다. aliases 입력란에서 중복·대응 관계를 먼저 확인해 주세요.');
    const names = new Set(aliases.map(item => item?.page_class));
    const base = typeof proposal.page_class === 'string' && proposal.page_class.trim() ? proposal.page_class.trim().slice(0, 90) : 'inventory-page';
    let pageClass = base, suffix = 2;
    while (names.has(pageClass)) pageClass = `${base}-${suffix++}`;
    aliases.push({ baseline: proposal.baseline, candidate: proposal.candidate, page_class: pageClass });
    $('#aliases').value = JSON.stringify(aliases, null, 2);
    $('#aliases').closest('details').open = true;
    $('#aliases').scrollIntoView({ behavior: 'smooth', block: 'center' });
    clearError();
    showSuccess(`매핑 JSON에 ${pageClass}를 추가했습니다. 현재 보고서의 후보·판정은 바꾸거나 승인 저장하지 않았습니다. 대응 관계와 설정을 검토한 뒤 새 검사를 시작해야 적용됩니다.`);
  } catch (error) { showError(error.message); }
}
function mappingButton(proposal, available = true) {
  const valid = typeof proposal?.baseline === 'string' && typeof proposal?.candidate === 'string';
  const button = el('button', { type: 'button', class: 'secondary', text: '매핑 JSON에 추가', disabled: !valid || !available });
  if (!valid) button.title = '엔진의 A/B 페이지 키 기록이 없습니다.';
  else if (!available) button.title = '이미 다른 대응에 사용된 후보입니다. 기존 매핑을 먼저 검토하세요.';
  button.addEventListener('click', () => addMappingDraft(proposal));
  return button;
}
function matchEvidence(value) {
  return el('pre', { class: 'inventory-evidence', text: asText(value == null ? '근거 미기록' : value) });
}
function renderInventory(report, job) {
  const inventory = report.inventory, pagesRoot = $('#pageInventory'), matchesRoot = $('#matchInventory');
  pagesRoot.replaceChildren(); matchesRoot.replaceChildren();
  visible($('#inventoryCsvLink'), Boolean(inventory));
  $('#inventoryCsvLink').href = `/api/scans/${encodeURIComponent(job.id)}/inventory.csv`;
  if (!inventory) { pagesRoot.append(el('p', { class: 'mini-meta', text: '이 실행에는 환경별 페이지 목록이 기록되지 않았습니다. 기존 결과에서 목록이나 후보를 임의로 만들어 표시하지 않습니다.' })); return; }
  const environments = Array.isArray(inventory.environments) ? inventory.environments : [];
  const grid = el('div', { class: 'environment-inventory-grid' });
  for (const environment of environments) {
    const box = el('section', { class: 'environment-inventory', 'data-environment': environment.id || 'unknown' });
    box.append(el('h3', { text: `${String(environment.id || '?').toUpperCase()} · ${environment.name || '이름 미기록'}` }));
    box.append(el('p', { class: 'mini-meta' }, [el('span', { text: '시작 URL: ' }), link(environment.seedUrl)]));
    box.append(el('p', { class: 'inventory-counts', text: `발견 ${metric(environment.discoveredCount)} · 방문 ${metric(environment.visitedCount)} · 보류 ${metric(environment.deferredCount)}` }));
    const pages = Array.isArray(environment.pages) ? environment.pages : [];
    if (!pages.length) box.append(el('p', { class: 'mini-meta', text: '기록된 페이지 없음 · 사이트에 페이지가 없다는 뜻은 아닙니다.' }));
    for (const page of pages) {
      const entry = el('details', { class: 'inventory-page' }, [el('summary', { text: page.title || page.pageKey || page.url || '제목 미기록' })]);
      entry.append(el('p', { class: 'mini-meta' }, [link(page.url)]));
      if (page.finalUrl && page.finalUrl !== page.url) entry.append(el('p', { class: 'mini-meta' }, [el('span', { text: '최종 URL: ' }), link(page.finalUrl)]));
      entry.append(el('p', { class: 'mini-meta', text: `페이지 키: ${page.pageKey ?? '미기록'} · HTTP ${page.statusCode ?? '—'} · 동작 후보 ${metric(page.actionCount)} · 캡처 준비 ${page.captureReady === true ? '완료' : page.captureReady === false ? '미완료' : '미기록'}` }));
      entry.append(el('p', { class: 'mini-meta', text: `발견 경로: ${asText(page.navigationTrail)}` }));
      const signature = el('details', { class: 'sub-details' }, [el('summary', { text: '페이지 구조·기능 특징 보기' }), matchEvidence(page.signature)]);
      entry.append(signature); box.append(entry);
    }
    grid.append(box);
  }
  pagesRoot.append(grid);
  const matches = Array.isArray(inventory.matches) ? inventory.matches : [];
  matchesRoot.append(el('h3', { text: '페이지 대응 규칙과 검토 후보' }), el('p', { class: 'helper', text: '후보는 근거를 검토할 대상입니다. ‘매핑 JSON에 추가’는 현재 설정만 수정하며, 다음 실행 전에 담당자가 대응 관계를 확인해야 합니다. 현재 결과나 검수 기록을 자동 승인하지 않습니다.' }));
  if (!matches.length) matchesRoot.append(el('p', { class: 'mini-meta', text: '기록된 매칭 결과 없음' }));
  for (const match of matches) {
    const card = el('article', { class: 'inventory-match' });
    card.append(el('div', { class: 'check-top' }, [el('strong', { text: match.key || match.id || '페이지 대응' }), el('span', { class: 'tag', text: match.approved === true ? '등록된 대응 규칙' : '확정 전 · 검토 대상' })]));
    card.append(el('p', { class: 'mini-meta', text: `방법: ${match.method || '미기록'} · 근거: ${asText(match.reason)}` }));
    const urls = el('div', { class: 'inventory-match-urls' });
    urls.append(el('p', { class: 'mini-meta' }, [el('span', { text: 'A: ' }), match.baselineUrl ? link(match.baselineUrl) : el('span', { text: '대응 페이지 미확정' })]), el('p', { class: 'mini-meta' }, [el('span', { text: 'B: ' }), match.candidateUrl ? link(match.candidateUrl) : el('span', { text: '대응 페이지 미확정' })]));
    card.append(urls, el('details', { class: 'sub-details' }, [el('summary', { text: '매칭 근거 보기' }), matchEvidence(match.evidence)]));
    if (match.approved !== true && match.baselineKey && match.candidateKey) card.append(mappingButton({ baseline: match.baselineKey, candidate: match.candidateKey, page_class: match.key }, match.aliasSafe !== false));
    for (const candidate of Array.isArray(match.candidates) ? match.candidates : []) {
      const option = el('div', { class: 'inventory-candidate' });
      option.append(el('strong', { text: candidate.available === false ? '후보 · 다른 대응에 사용됨' : 'REVIEW · 매칭 후보' }), el('p', { class: 'mini-meta' }, [link(candidate.url)]));
      option.append(el('p', { class: 'mini-meta', text: `페이지 키: ${candidate.key || '미기록'} · ${candidate.method || '방법 미기록'} · ${asText(candidate.reason)}` }));
      option.append(el('details', { class: 'sub-details' }, [el('summary', { text: '후보 근거 보기' }), matchEvidence(candidate.evidence)]));
      option.append(mappingButton(candidate.alias, candidate.available !== false));
      card.append(option);
    }
    matchesRoot.append(card);
  }
}
function searchText(item) {
  return [item.key, item.region_id, item.baseline?.title, item.candidate?.title, item.baseline?.url, item.candidate?.url, ...(item.flags || []), ...(item.baseline?.issues || []).flatMap(issue => [issue.category, issue.message]), ...(item.candidate?.issues || []).flatMap(issue => [issue.category, issue.message]), ...(item.checks || []).flatMap(check => [check.check_id, check.scenario_id, check.reason_code]), ...rowFindings(item).flatMap(finding => [finding.summary, finding.category, finding.subtype, finding.fingerprint]), reviewIssue(item)].filter(Boolean).join(' ').toLowerCase();
}
function renderRows() {
  const rows = $('#resultRows'); rows.replaceChildren();
  const needle = $('#searchFilter').value.trim().toLowerCase();
  const region = $('#regionFilter').value;
  const min = $('#diffMin').value === '' ? null : Number($('#diffMin').value);
  const max = $('#diffMax').value === '' ? null : Number($('#diffMax').value);
  const invalidRange = min != null && max != null && min > max;
  visible($('#filterWarning'), invalidRange);
  const results = state.report?.results || [];
  let shown = 0;
  results.forEach((item, index) => {
    if (invalidRange || (state.filter !== 'ALL' && item.status !== state.filter) || (region !== 'ALL' && (item.region_id || '__PAGE__') !== region) || (needle && !searchText(item).includes(needle))) return;
    const meta = rowMeta(item);
    const selections = { testTypeFilter: [item.testType || reportType()], environmentFilter: meta.environments.length ? meta.environments : ['unknown'], categoryFilter: meta.categories.length ? meta.categories : ['UNREGISTERED'], subtypeFilter: meta.subtypes.length ? meta.subtypes : ['UNREGISTERED'], severityFilter: [meta.severity], reviewStatusFilter: [item.review?.status || 'UNREVIEWED'], regressionFilter: meta.regressions };
    if (Object.entries(selections).some(([id, values]) => $(`#${id}`).value !== 'ALL' && !values.includes($(`#${id}`).value))) return;
    const difference = numeric(item.visual?.differencePercent);
    if (difference == null) { if (!$('#includeNull').checked) return; }
    else if ((min != null && difference < min) || (max != null && difference > max)) return;
    rows.append(rowFor(item, index)); shown += 1;
  });
  $('#resultCount').textContent = `${shown} / ${results.length}개 결과 행`;
  visible($('#emptyMessage'), shown === 0);
}
function setFilter(value) {
  state.filter = value;
  for (const button of document.querySelectorAll('[data-filter]')) { const active = button.dataset.filter === value; button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active)); }
}
function resetResultFilters() {
  setFilter('ALL'); $('#searchFilter').value = ''; for (const id of SELECT_FILTERS) $(`#${id}`).value = 'ALL'; $('#diffMin').value = ''; $('#diffMax').value = ''; $('#includeNull').checked = true;
}
function openAttention(index) {
  resetResultFilters(); renderRows();
  const row = $(`#result-row-${index}`); if (row) { row.open = true; row.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
}
async function openPreviousEvidence(previousId, finding = null) {
  resetResultFilters();
  const job = await loadJob(previousId, { scroll: false });
  const previousRows = new Set((finding?.previousRowIds || []).map(String));
  const rows = job.report?.results || [];
  const matching = rows.map((row, index) => ({ row, index })).filter(({ row }) => previousRows.has(String(row.id || row.result_id)) || (finding?.previousFindingId && (row.findingIds || []).includes(finding.previousFindingId)));
  for (const { index } of matching) { const node = $(`#result-row-${index}`); if (node) node.open = true; }
  const target = matching.length ? $(`#result-row-${matching[0].index}`) : $('#resultSection');
  target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  showSuccess(`과거 실행 ${String(previousId).slice(0, 8)}의 증거를 표시 중입니다. 필터를 초기화했습니다.${finding && !matching.length ? ' 연결된 행을 특정하지 못했으므로 과거 실행의 전체 결과에서 확인해 주세요.' : ''}`);
}
function renderRegression(report, job) {
  const root = $('#regressionSummary'); root.replaceChildren();
  const regression = report.regression;
  if (!regression) { root.append(el('p', { class: 'mini-meta', text: '회귀 미평가 · 과거 실행과 비교한 근거가 없습니다.' })); return; }
  const heading = regression.comparable === true ? '과거 / 현재 실행 비교' : regression.comparable === false ? '회귀 비교 불가 · 해결 여부를 확정하지 않습니다' : '회귀 비교 가능 여부 미평가';
  const details = el('details', { class: 'regression-details' }, [el('summary', { text: heading })]);
  const previousId = report.previousRunId || regression.previousRunId || job.previousRunId;
  details.append(el('p', { class: 'mini-meta', text: `과거 ${previousId || '참조 미기록'} → 현재 ${job.id}` }));
  if (previousId) { const button = el('button', { type: 'button', class: 'secondary', text: '과거 실행 근거 열기' }); button.addEventListener('click', () => openPreviousEvidence(previousId).catch(error => showError(error.message))); details.append(button); }
  if (regression.reasons?.length) details.append(el('p', { class: 'mini-meta', text: regression.reasons.map(asText).join(' · ') }));
  const counts = el('div', { class: 'coverage-summary' });
  for (const [classification, count] of Object.entries(regression.summary || {})) counts.append(el('span', {}, [el('span', { text: REGRESSION_LABELS[classification] || classification }), el('strong', { text: metric(count) })]));
  details.append(counts);
  for (const finding of regression.findings || []) {
    const current = state.findingMap.get(finding.currentFindingId);
    const copy = el('div', { class: 'regression-detail-copy' }, [el('div', { text: current?.summary || finding.summary || '과거 발견 사항' }), el('p', { class: 'mini-meta', text: `페이지 ${finding.pageKey || '미기록'} · 검증식 ${finding.checkId || '미기록'}` }), el('p', { class: 'mini-meta', text: `판정 근거: ${finding.reason || '미기록'}` })]);
    const entry = el('div', { class: 'regression-finding' }, [el('span', { class: 'tag', text: REGRESSION_LABELS[finding.classification] || finding.classification || '미평가' }), copy]);
    if (previousId && (finding.previousFindingId || finding.previousRowIds?.length)) {
      const button = el('button', { type: 'button', class: 'secondary', text: '이전 증거 보기' });
      button.addEventListener('click', () => openPreviousEvidence(previousId, finding).catch(error => showError(error.message)));
      entry.append(button);
    }
    details.append(entry);
  }
  details.append(el('p', { class: 'mini-meta', text: '해결 후보는 재검 근거를 확인한 뒤 최종 검수합니다. 검사 누락은 해결로 처리하지 않습니다.' }));
  root.append(details);
}
function renderReport(report, job) {
  state.report = report;
  state.job = job;
  state.findingMap = new Map((report.findings || []).map(finding => [finding.id, finding]));
  const results = Array.isArray(report.results) ? report.results : [];
  const totals = report.totals || {};
  const stats = $('#stats'); stats.replaceChildren();
  const counts = [['ALL', '결과 행', totals.resultRows ?? results.length], ...STATUS.map(status => [status, status, totals[status.toLowerCase()] ?? results.filter(item => item.status === status).length])];
  for (const [status, title, count] of counts) stats.append(el('div', { class: `stat ${status}` }, [el('span', { text: title }), el('strong', { text: metric(count) })]));
  $('#resultMeta').textContent = `${TYPE_LABELS[reportType(report, job)] || reportType(report, job)} · ${MODE_LABELS[reportMode(report, job)] || reportMode(report, job)} · ${job.operatorId || report.operatorId || '담당자 정보 없음'} · ${profileLabel(job.profileId || report.profileId)} · ${dateText(job.startedAt)} · ${JOB_LABELS[job.state] || job.state || ''} · ${String(job.id || '').slice(0, 8)}`;
  $('#resultMeta').textContent += ` · A: ${environmentName('a', report, job)}${reportType(report, job) === 'comparison' ? ` / B: ${environmentName('b', report, job)}` : ''}`;
  visible($('#discoveryNotice'), reportMode(report, job) === 'discovery');
  $('#loadRunSettings').disabled = !job.options || Boolean(state.activeId);
  $('#configureVisualMode').disabled = !job.options || Boolean(state.activeId);
  const coverage = $('#coverageSummary'); coverage.replaceChildren();
  const coverageItems = [['A 방문', totals.baselineVisited], ['실행 검증식', totals.assertions], ['발견 동작', totals.discoveredActions]];
  if (['comparison', 'UNSPECIFIED'].includes(reportType(report, job))) coverageItems.splice(1, 0, ['B 방문', totals.candidateVisited]);
  if (totals.attemptedActions != null) coverageItems.push(['시도 동작', totals.attemptedActions]);
  coverageItems.push(['실행 완료 동작', totals.executedActions], ['차단·제외 동작', totals.blockedActions]);
  coverageItems.push(['원시 관찰', totals.rawObservations], ['고유 발견 사항', totals.uniqueFindings ?? (Array.isArray(report.findings) ? report.findings.length : null)], ['연결된 이슈', totals.linkedIssues]);
  for (const [status, count] of Object.entries(totals.checkStatuses || totals.checkStatusCounts || {})) coverageItems.push([`검증식 ${status}`, count]);
  for (const [label, value] of coverageItems) coverage.append(el('span', {}, [el('span', { text: label }), el('strong', { text: metric(value) })]));
  const legacy = !Array.isArray(report.findings);
  visible($('#legacyNotice'), legacy);
  $('#legacyNotice').textContent = '이전 형식의 보고서입니다. 당시 PASS/FAIL/REVIEW/SKIP/ERROR를 그대로 표시하며 DIFF/BLOCKED로 재분류하지 않습니다. 추가 분류·심각도·고유 발견 집계가 없으면 미등록/미평가로 표시합니다.';
  renderRegression(report, job);
  renderInventory(report, job);
  $('#csvLink').href = `/api/scans/${encodeURIComponent(job.id)}.csv`; $('#jsonLink').href = `/api/scans/${encodeURIComponent(job.id)}.json`;
  const metadata = results.map(rowMeta);
  selectOptions('regionFilter', results.map(item => item.region_id || '__PAGE__'), { __PAGE__: '페이지 전체' }, '모든 영역');
  selectOptions('environmentFilter', metadata.flatMap(meta => meta.environments.length ? meta.environments : ['unknown']), ENV_LABELS, '모든 환경');
  selectOptions('categoryFilter', metadata.flatMap(meta => meta.categories.length ? meta.categories : ['UNREGISTERED']), CATEGORY_LABELS, '모든 분류');
  selectOptions('subtypeFilter', metadata.flatMap(meta => meta.subtypes.length ? meta.subtypes : ['UNREGISTERED']), { UNREGISTERED: '유형 미등록' }, '모든 유형');
  selectOptions('severityFilter', metadata.map(meta => meta.severity), { UNEVALUATED: '심각도 미평가' }, '모든 심각도');
  selectOptions('reviewStatusFilter', Object.keys(REVIEW_LABELS), REVIEW_LABELS, '모든 검수 상태');
  selectOptions('regressionFilter', metadata.flatMap(meta => meta.regressions), REGRESSION_LABELS, '모든 회귀 구분');
  const attention = results.map((item, index) => ({ item, index })).filter(({ item }) => ['FAIL', 'ERROR'].includes(item.status));
  visible($('#attentionPanel'), attention.length > 0);
  $('#attentionSummary').textContent = `실패 · 실행 오류 ${attention.length}개 — 차이율 필터와 관계없이 확인하세요`;
  $('#attentionList').replaceChildren();
  for (const { item, index } of attention) { const button = el('button', { type: 'button', class: 'secondary', text: '근거 확인' }); button.addEventListener('click', () => openAttention(index)); $('#attentionList').append(el('div', { class: 'attention-row' }, [el('span', { text: `${item.status} · ${item.key} ${item.region_id ? `· ${item.region_id}` : ''}` }), button])); }
  renderRows(); visible($('#resultSection'), true);
}

$('#scanForm').addEventListener('submit', async event => {
  event.preventDefault(); clearError(); visible($('#successSection'), false);
  if (state.activeId || state.submitting) return;
  state.submitting = true; updateStartButton();
  try {
    const payload = buildPayload(); saveRememberedIds();
    const data = await api('/api/scans', { method: 'POST', body: payload });
    const id = data.id || data.job?.id;
    if (!id) throw new Error('서버가 실행 식별자를 반환하지 않았습니다. 실행 이력을 확인해 주세요.');
    state.activeId = id; state.selectedId = id; state.report = null; visible($('#resultSection'), false); setFilter('ALL');
    startPolling(id);
    await loadJob(id, { scroll: false }); await refreshHistory();
    $('#progressSection').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (error) { showError(error.message); if (error.status === 409) refreshHistory().catch(() => {}); }
  finally { state.submitting = false; updateStartButton(); }
});
$('#cancelBtn').addEventListener('click', async () => {
  if (!state.activeId) return;
  $('#cancelBtn').disabled = true;
  try { await api(`/api/scans/${encodeURIComponent(state.activeId)}/cancel`, { method: 'POST', body: {} }); $('#progressText').textContent = '중단을 요청했습니다. 진행 중인 작업을 정리하고 있습니다.'; } catch (error) { showError(error.message); $('#cancelBtn').disabled = false; }
});
$('#continueBtn').addEventListener('click', async () => {
  if (!state.activeId) return;
  $('#continueBtn').disabled = true;
  try { await api(`/api/scans/${encodeURIComponent(state.activeId)}/continue`, { method: 'POST', body: {} }); $('#authText').textContent = '검사 계속을 요청했습니다. 사용자가 확인한 로그인 상태로 검사를 진행합니다.'; } catch (error) { showError(error.message); $('#continueBtn').disabled = false; }
});
$('#refreshHistory').addEventListener('click', async () => { try { await refreshHistory(); const active = state.jobs.find(job => ['running', 'awaiting_auth'].includes(job.state)); if (active) { state.activeId = active.id; updateProgress(active); startPolling(active.id); updateStartButton(); } } catch (error) { showError(error.message); } });
$('#profileId').addEventListener('change', () => { $('#projectId').value = ''; applyProfile(); });
$('#projectId').addEventListener('change', chooseProject);
window.addEventListener('pageshow', () => { const previous = $('#projectId').value; populateProjects(previous); if (previous && !$('#projectId').value) applyProfile(); });
$('#testType').addEventListener('change', updateTestType);
$('#crawlScope').addEventListener('change', updateCrawlScopeHint);
for (const side of ['baseline', 'candidate']) {
  $(`#${side}EnvironmentId`).addEventListener('change', () => chooseEnvironment(side));
  $(`#${side}Url`).addEventListener('input', () => { syncEnvironmentSelection(side); updateCrawlScopeHint(); });
}
$('#useConditionExample').addEventListener('click', () => { $('#conditions').value = JSON.stringify(CONDITION_EXAMPLE, null, 2); });
$('#loadRunSettings').addEventListener('click', () => loadRunSettings());
$('#configureVisualMode').addEventListener('click', () => loadRunSettings({ visual: true }));
$('#operatorId').addEventListener('change', loadRememberedIds);
$('#rememberIds').addEventListener('change', () => { updateRememberedInputs(); saveRememberedIds(); if (!$('#rememberIds').checked) { $('#rememberedIdA').value = ''; $('#rememberedIdB').value = ''; } });
for (const id of ['rememberedIdA', 'rememberedIdB']) $(`#${id}`).addEventListener('change', saveRememberedIds);
for (const button of document.querySelectorAll('[data-filter]')) button.addEventListener('click', () => { setFilter(button.dataset.filter); renderRows(); });
for (const id of ['searchFilter', 'diffMin', 'diffMax']) $(`#${id}`).addEventListener('input', renderRows);
for (const id of [...SELECT_FILTERS, 'includeNull']) $(`#${id}`).addEventListener('change', renderRows);

async function init() {
  $('#conditionExample').textContent = JSON.stringify(CONDITION_EXAMPLE, null, 2);
  try {
    const bootstrap = await api('/api/bootstrap');
    state.token = bootstrap.sessionToken || '';
    state.profiles = Array.isArray(bootstrap.profiles) ? bootstrap.profiles : [];
    populateProjects();
    const select = $('#profileId'); select.replaceChildren();
    for (const profile of state.profiles) select.append(el('option', { value: profile.id, text: profile.label || profile.id, disabled: Boolean(profile.disabled) }));
    const first = state.profiles.find(profile => !profile.disabled && /demo/i.test(profile.id)) || state.profiles.find(profile => !profile.disabled);
    if (first) { select.value = first.id; applyProfile(); }
    try {
      const draft = JSON.parse(sessionStorage.getItem('m_pending_project') || 'null');
      sessionStorage.removeItem('m_pending_project');
      if (draft && typeof draft.baselineUrl === 'string' && state.profiles.some(profile => profile.id === 'custom' && !profile.disabled)) {
        if (draft.projectId && [...$('#projectId').options].some(option => option.value === draft.projectId)) $('#projectId').value = draft.projectId;
        $('#profileId').value = 'custom';
        applyProfile();
        for (const id of ['baselineUrl', 'candidateUrl', 'baselineName', 'candidateName', 'testType']) {
          if (typeof draft[id] === 'string' && $(`#${id}`)) $(`#${id}`).value = draft[id];
        }
        syncEnvironmentSelection('baseline'); syncEnvironmentSelection('candidate'); updateTestType();
        showSuccess('프로젝트의 첫 번째 환경을 A, 두 번째 환경을 B로 불러왔습니다. 담당자 ID와 검사 조건을 입력한 뒤 시작하세요.');
      }
    } catch { /* Invalid browser draft is ignored. */ }
    $('#connectionStatus').textContent = '로컬 서버 연결됨 · 실행 기록 저장';
    updateStartButton();
    await refreshHistory();
    const requestedRun = new URLSearchParams(location.search).get('run');
    if (requestedRun && state.jobs.some(job => job.id === requestedRun)) await loadJob(requestedRun, { scroll: false });
    const active = state.jobs.find(job => ['running', 'awaiting_auth'].includes(job.state));
    if (active) await loadJob(active.id, { scroll: false });
  } catch (error) { $('#connectionStatus').textContent = '서버 연결을 확인해 주세요'; showError(error.message); }
}
init();
