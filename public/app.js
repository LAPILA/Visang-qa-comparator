const $ = selector => document.querySelector(selector);
const STATUS = ['PASS', 'FAIL', 'REVIEW', 'SKIP', 'ERROR'];
const REVIEW_LABELS = { UNREVIEWED: '미검수', BUG_CONFIRMED: '버그 확정', EXPECTED_DIFFERENCE: '정상 차이', FALSE_POSITIVE: '오탐', RETEST_REQUIRED: '재검 필요' };
const JOB_LABELS = { running: '실행 중', awaiting_auth: '로그인 대기', done: '완료', cancelled: '중단', error: '실행 오류' };
const state = { token: '', profiles: [], jobs: [], selectedId: null, activeId: null, report: null, job: null, filter: 'ALL', polling: null, pollErrors: 0, submitting: false };

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
function badge(status) { const value = STATUS.includes(status) ? status : 'REVIEW'; return el('span', { class: `status ${value}`, text: value }); }
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
function updateStartButton() { $('#startBtn').disabled = !state.token || Boolean(state.activeId) || state.submitting || Boolean(profileById($('#profileId').value)?.disabled); $('#startText').textContent = state.submitting ? '검사 시작 중…' : state.activeId ? '검사 진행 중' : '검사 시작'; }

function applyProfile() {
  const profile = profileById($('#profileId').value);
  if (!profile) return;
  const defaults = profile.defaults || {};
  $('#maxActions').max = profile.id === 'synthetic-demo' ? '200' : '50';
  $('#baselineUrl').value = profile.baselineUrl || defaults.baselineUrl || '';
  $('#candidateUrl').value = profile.candidateUrl || defaults.candidateUrl || '';
  $('#profileHint').textContent = profile.description || '등록한 시작 URL과 승인된 동작만 검사합니다.';
  const fallback = { mode: 'combined', maxPages: 10, maxDepth: 2, maxActions: 20, timeoutSeconds: 300, visualThreshold: 2 };
  for (const [name, value] of Object.entries(fallback)) $(`#${name}`).value = defaults[name] ?? value;
  for (const name of ['aliases', 'regions', 'safeActions', 'scenarioIds']) $(`#${name}`).value = JSON.stringify(defaults[name] || profile[name] || [], null, 2);
  for (const name of ['allowedPaths', 'allowedHosts']) $(`#${name}`).value = (defaults[name] || profile[name] || []).join('\n');
  if (typeof defaults.manualLogin === 'boolean') $('#manualLogin').checked = defaults.manualLogin;
  loadRememberedIds();
  updateStartButton();
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
  $('#rememberedIdB').disabled = !enabled;
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
  const payload = { profileId: $('#profileId').value, operatorId: $('#operatorId').value.trim(), baselineUrl: $('#baselineUrl').value.trim(), candidateUrl: $('#candidateUrl').value.trim(), mode: $('#mode').value, manualLogin: $('#manualLogin').checked };
  if (!payload.operatorId) throw new Error('실행 담당자를 입력해 주세요.');
  if (!safeUrl(payload.baselineUrl) || !safeUrl(payload.candidateUrl)) throw new Error('아이디·비밀번호를 포함하지 않은 http 또는 https URL을 입력해 주세요.');
  for (const name of ['maxPages', 'maxDepth', 'maxActions', 'timeoutSeconds', 'visualThreshold']) payload[name] = Number($(`#${name}`).value);
  for (const name of ['aliases', 'regions', 'safeActions', 'scenarioIds']) payload[name] = readArray(name);
  for (const name of ['allowedPaths', 'allowedHosts']) payload[name] = $(`#${name}`).value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
  if (payload.allowedPaths.some(value => ['*', '/*', '**', '/**'].includes(value)) || payload.allowedHosts.some(value => value.includes('*'))) throw new Error('전체 허용(*) 대신 검토한 경로와 정확한 호스트를 입력해 주세요.');
  if (payload.scenarioIds.some(id => typeof id !== 'string')) throw new Error('scenarioIds는 문자열 ID 배열이어야 합니다.');
  return payload;
}

async function refreshHistory() {
  const data = await api('/api/scans');
  state.jobs = Array.isArray(data.scans) ? data.scans : [];
  renderHistory();
  return state.jobs;
}
function renderHistory() {
  const list = $('#historyList'); list.replaceChildren();
  if (!state.jobs.length) { list.append(el('p', { class: 'empty compact', text: '아직 실행 기록이 없습니다. 합성 데모로 첫 검사를 시작해 보세요.' })); return; }
  for (const job of state.jobs) {
    const button = el('button', { type: 'button', class: `history-item${state.selectedId === job.id ? ' selected' : ''}`, 'aria-label': `${profileLabel(job.profileId)} ${dateText(job.startedAt)} 실행 열기` });
    button.append(el('div', { class: 'history-top' }, [el('span', { class: 'history-title', text: profileLabel(job.profileId || job.report?.profileId) }), el('span', { class: `job-state ${job.state || ''}`, text: JOB_LABELS[job.state] || job.state || '기록' })]));
    button.append(el('div', { class: 'history-meta', text: `${job.operatorId || job.report?.operatorId || '담당자 정보 없음'} · ${dateText(job.startedAt)}\n${String(job.id || '').slice(0, 8)}` }));
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
    row.append(el('span', { class: 'error-type', text: `[${item.category || 'OBSERVATION'}]` }), el('span', { text: item.message || item.reason || '' }));
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
function imageCard(value, title) {
  const url = safeUrl(value, true);
  if (!url) return el('figure', { class: 'screenshot' }, [el('div', { class: 'screenshot-placeholder', text: '이미지 없음 / 비교 불가' }), el('figcaption', { text: title })]);
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
  const select = el('select', { 'aria-label': '최종 검수 상태' });
  for (const [value, label] of Object.entries(REVIEW_LABELS)) select.append(el('option', { value, text: label }));
  select.value = review.status || 'UNREVIEWED';
  const reason = el('textarea', { rows: '1', required: true, maxlength: '2000', placeholder: '판정 근거 또는 재검 사유', 'aria-label': '검수 사유' });
  const button = el('button', { type: 'submit', class: 'secondary', text: '검수 저장' });
  form.append(el('label', { class: 'field' }, [el('span', { text: '검수 담당자' }), reviewer]), el('label', { class: 'field' }, [el('span', { text: '최종 검수' }), select]), el('label', { class: 'field reason-field' }, [el('span', { text: '사유' }), reason]), button);
  const feedback = el('p', { class: 'review-feedback hidden', role: 'status' });
  form.addEventListener('submit', async event => {
    event.preventDefault(); button.disabled = true;
    const resultId = item.id || item.result_id;
    try {
      if (!resultId) throw new Error('결과 식별자가 없어 검수를 저장할 수 없습니다.');
      if (!reviewer.value.trim() || !reason.value.trim()) throw new Error('검수 담당자와 사유를 입력해 주세요.');
      await api(`/api/scans/${encodeURIComponent(runId)}/reviews`, { method: 'POST', body: { resultId, reviewer: reviewer.value.trim(), status: select.value, reason: reason.value.trim(), expectedRevision: review.revision ?? 0 } });
      const job = await api(`/api/scans/${encodeURIComponent(runId)}`);
      const updated = job.report?.results?.find(result => (result.id || result.result_id) === resultId);
      if (updated && state.selectedId === runId) { Object.assign(item, updated); const summary = box.closest('.result-row')?.querySelector('.review-tag span'); if (summary) summary.textContent = REVIEW_LABELS[updated.review?.status] || '미검수'; box.replaceWith(renderReview(item)); }
      showSuccess('검수 이력을 저장했습니다. 자동 검사 판정은 유지됩니다.');
    } catch (error) {
      feedback.textContent = error.status === 409 ? '다른 담당자가 먼저 검수했습니다. 현재 결과를 다시 열어 최신 검수 이력을 확인한 뒤 저장해 주세요. 입력한 사유는 유지됩니다.' : error.message;
      feedback.classList.add('error'); visible(feedback, true);
    } finally { button.disabled = false; }
  });
  box.append(form, feedback);
  const events = Array.isArray(review.events) ? review.events : [];
  if (events.length) {
    const history = el('details', { class: 'sub-details review-history' }, [el('summary', { text: `검수 이력 ${events.length}건` })]);
    for (const event of [...events].reverse()) history.append(el('div', { class: 'review-event', text: `${event.reviewer || event.actor || '담당자'} · ${REVIEW_LABELS[event.status || event.new_status] || event.status || event.new_status || ''} · ${dateText(event.timestamp || event.createdAt)}\n${event.reason || ''}` }));
    box.append(history);
  }
  return box;
}
function rowFor(item, index) {
  const row = el('details', { class: 'result-row', id: `result-row-${index}` });
  const main = el('summary', { class: 'row-main' });
  const primary = el('div', {}, [el('div', { class: 'pathname', text: item.key === '__ROOT__' ? '홈 페이지' : item.key || item.page_class || '페이지' }), el('div', { class: 'desc', text: item.baseline?.title || item.candidate?.title || '제목 정보 없음' })]);
  if (item.region_id) primary.append(el('div', { class: 'region-label', text: item.region_id }));
  const flags = Array.isArray(item.flags) ? item.flags : [];
  const tags = el('div', { class: 'tags' });
  for (const flag of flags.slice(0, 3)) tags.append(el('span', { class: 'tag', text: flag }));
  if (flags.length > 3) tags.append(el('span', { class: 'tag', text: `+${flags.length - 3}` }));
  if (!flags.length) tags.append(el('span', { class: 'tag', text: '관찰 유형 없음' }));
  const difference = numeric(item.visual?.differencePercent);
  main.append(primary, badge(item.status), tags, el('span', { class: 'diff-value', text: difference == null ? '비교 불가' : `${difference.toFixed(2)}%` }), el('span', { class: 'review-tag' }, [el('span', { text: REVIEW_LABELS[item.review?.status] || '미검수' }), el('span', { class: 'expand-mark', text: '⌄', 'aria-hidden': 'true' })]));
  const details = el('div', { class: 'details' });
  if (item.match) details.append(el('p', { class: 'mini-meta', text: `매칭: ${item.match.method || '미확정'} · 확신도 ${item.match.confidence || '정보 없음'}` }));
  details.append(el('div', { class: 'detail-grid' }, [renderSite(item.baseline, '기준 A'), renderSite(item.candidate, '비교 B')]));
  details.append(el('h4', { class: 'evidence-title', text: `화면 증거 · ${difference == null ? '비교 불가' : `차이율 ${difference.toFixed(2)}%`}` }), el('div', { class: 'screenshot-grid' }, [imageCard(item.baseline?.screenshot, '기준 화면'), imageCard(item.candidate?.screenshot, '비교 화면'), imageCard(item.visual?.url, '차이 영역')]));
  if (item.visual?.note) details.append(el('p', { class: 'mini-meta', text: item.visual.note }));
  details.append(el('h4', { class: 'evidence-title', text: '실행한 검증식과 기대 결과' }), renderChecks(item.checks), renderActions(item), renderReview(item));
  row.append(main, details); return row;
}
function searchText(item) {
  return [item.key, item.region_id, item.baseline?.title, item.candidate?.title, item.baseline?.url, item.candidate?.url, ...(item.flags || []), ...(item.baseline?.issues || []).flatMap(issue => [issue.category, issue.message]), ...(item.candidate?.issues || []).flatMap(issue => [issue.category, issue.message]), ...(item.checks || []).flatMap(check => [check.check_id, check.scenario_id, check.reason_code])].filter(Boolean).join(' ').toLowerCase();
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
    const difference = numeric(item.visual?.differencePercent);
    if (difference == null) { if (!$('#includeNull').checked) return; }
    else if ((min != null && difference < min) || (max != null && difference > max)) return;
    rows.append(rowFor(item, index)); shown += 1;
  });
  $('#resultCount').textContent = `${shown} / ${results.length}개 표시`;
  visible($('#emptyMessage'), shown === 0);
}
function setFilter(value) {
  state.filter = value;
  for (const button of document.querySelectorAll('[data-filter]')) { const active = button.dataset.filter === value; button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active)); }
}
function openAttention(index) {
  setFilter('ALL'); $('#searchFilter').value = ''; $('#regionFilter').value = 'ALL'; $('#diffMin').value = ''; $('#diffMax').value = ''; $('#includeNull').checked = true; renderRows();
  const row = $(`#result-row-${index}`); if (row) { row.open = true; row.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
}
function renderReport(report, job) {
  state.report = report;
  const results = Array.isArray(report.results) ? report.results : [];
  const totals = report.totals || {};
  const stats = $('#stats'); stats.replaceChildren();
  const counts = [['ALL', '비교 결과', totals.pages ?? results.length], ...STATUS.map(status => [status, status, totals[status.toLowerCase()] ?? results.filter(item => item.status === status).length])];
  for (const [status, title, count] of counts) stats.append(el('div', { class: `stat ${status}` }, [el('span', { text: title }), el('strong', { text: metric(count) })]));
  $('#resultMeta').textContent = `${job.operatorId || report.operatorId || '담당자 정보 없음'} · ${profileLabel(job.profileId || report.profileId)} · ${dateText(job.startedAt)} · ${JOB_LABELS[job.state] || job.state || ''} · ${String(job.id || '').slice(0, 8)}`;
  const coverage = $('#coverageSummary'); coverage.replaceChildren();
  const coverageItems = [['A 방문', totals.baselineVisited], ['B 방문', totals.candidateVisited], ['실행 검증식', totals.assertions], ['발견 동작', totals.discoveredActions]];
  if (totals.attemptedActions != null) coverageItems.push(['시도 동작', totals.attemptedActions]);
  coverageItems.push(['실행 완료 동작', totals.executedActions], ['차단·제외 동작', totals.blockedActions]);
  for (const [label, value] of coverageItems) coverage.append(el('span', {}, [el('span', { text: label }), el('strong', { text: metric(value) })]));
  $('#csvLink').href = `/api/scans/${encodeURIComponent(job.id)}.csv`; $('#jsonLink').href = `/api/scans/${encodeURIComponent(job.id)}.json`;
  const currentRegion = $('#regionFilter').value;
  $('#regionFilter').replaceChildren(el('option', { value: 'ALL', text: '모든 영역' }));
  for (const region of new Set(results.map(item => item.region_id || '__PAGE__'))) $('#regionFilter').append(el('option', { value: region, text: region === '__PAGE__' ? '페이지 전체' : region }));
  $('#regionFilter').value = [...$('#regionFilter').options].some(option => option.value === currentRegion) ? currentRegion : 'ALL';
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
$('#profileId').addEventListener('change', applyProfile);
$('#operatorId').addEventListener('change', loadRememberedIds);
$('#rememberIds').addEventListener('change', () => { updateRememberedInputs(); saveRememberedIds(); if (!$('#rememberIds').checked) { $('#rememberedIdA').value = ''; $('#rememberedIdB').value = ''; } });
for (const id of ['rememberedIdA', 'rememberedIdB']) $(`#${id}`).addEventListener('change', saveRememberedIds);
for (const button of document.querySelectorAll('[data-filter]')) button.addEventListener('click', () => { setFilter(button.dataset.filter); renderRows(); });
for (const id of ['searchFilter', 'diffMin', 'diffMax']) $(`#${id}`).addEventListener('input', renderRows);
for (const id of ['regionFilter', 'includeNull']) $(`#${id}`).addEventListener('change', renderRows);

async function init() {
  try {
    const bootstrap = await api('/api/bootstrap');
    state.token = bootstrap.sessionToken || '';
    state.profiles = Array.isArray(bootstrap.profiles) ? bootstrap.profiles : [];
    const select = $('#profileId'); select.replaceChildren();
    for (const profile of state.profiles) select.append(el('option', { value: profile.id, text: `${profile.label || profile.id}${profile.disabled ? ' · 주소 확인 필요' : ''}`, disabled: Boolean(profile.disabled) }));
    const first = state.profiles.find(profile => !profile.disabled && /demo/i.test(profile.id)) || state.profiles.find(profile => !profile.disabled);
    if (first) { select.value = first.id; applyProfile(); }
    $('#connectionStatus').textContent = '로컬 서버 연결됨 · 실행 기록 저장';
    updateStartButton();
    await refreshHistory();
    const active = state.jobs.find(job => ['running', 'awaiting_auth'].includes(job.state));
    if (active) await loadJob(active.id, { scroll: false });
  } catch (error) { $('#connectionStatus').textContent = '서버 연결을 확인해 주세요'; showError(error.message); }
}
init();
