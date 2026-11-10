// 실행 결과: 실행 목록(경량 요약 version 비교로 갱신) + 선택 실행의 진행 단계·검증식·증거. 원안: 1105_mia
const $ = selector => document.querySelector(selector);
const stateNames = { running: '검사 중', awaiting_auth: '로그인 대기', done: '검사 완료', cancelled: '중단됨', error: '실행 오류' };
const typeNames = { comparison: '환경 비교', single: '단일 환경', regression: '회귀 테스트', conditional: '조건 기반 UI' };
const statuses = ['PASS', 'FAIL', 'DIFF', 'REVIEW', 'SKIP', 'BLOCKED', 'ERROR'];
let runs = [], selectedId = new URLSearchParams(location.search).get('run'), filter = 'all', profiles = new Map(), busy = false;
let renderedId = null;
let loadedId = null, loadedVersion = null;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}
function notice(message, error = false) { $('#notice').textContent = message; $('#notice').className = `notice ${error ? 'error-notice' : 'success-notice'}`; }
function date(value) {
  if (!value) return '시각 미기록';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '시각 미기록' : new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed);
}
function count(value) { return Number.isFinite(Number(value)) ? Number(value).toLocaleString('ko-KR') : '—'; }
async function get(path) {
  const response = await fetch(path, { cache: 'no-store' });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `서버 응답 오류 (${response.status})`);
  return data;
}
function badge(state) { return element('span', stateNames[state] || state || '상태 미기록', `state-badge ${state || ''}`); }
function matchesFilter(run) { return filter === 'all' || (filter === 'active' ? ['running', 'awaiting_auth'].includes(run.state) : !['running', 'awaiting_auth'].includes(run.state)); }
function renderList() {
  const list = $('#runList'); list.replaceChildren();
  const visible = runs.filter(matchesFilter);
  $('#runCount').textContent = `${runs.length}개 실행 · 현재 ${visible.length}개 표시`;
  if (!visible.length) { list.append(element('p', runs.length ? '선택한 상태의 검사가 없습니다.' : '검사 이력이 없습니다. 검사 실행 화면에서 시작하세요.', 'empty-detail')); return; }
  for (const run of visible) {
    const button = element('button', null, `run-item${run.id === selectedId ? ' selected' : ''}`);
    button.type = 'button'; button.dataset.runId = run.id;
    const top = element('div', null, 'run-item-top');
    top.append(element('strong', profiles.get(run.profileId) || run.profileId || '검사 프로필 미기록'), badge(run.state));
    button.append(top, element('small', `${typeNames[run.testType] || run.testType || '목적 미기록'} · ${run.operatorId || '담당자 미기록'} · ${date(run.startedAt)}`));
    if (run.progress) button.append(element('small', run.progress));
    button.addEventListener('click', () => selectRun(run.id));
    list.append(button);
  }
}
function safeLink(value) {
  if (typeof value !== 'string') return null;
  try { const url = new URL(value, location.origin); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; }
  catch { return null; }
}
function safeArtifact(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value, location.origin);
    return url.origin === location.origin && /^\/artifacts\/[a-z0-9-]+\/(a|b|diff)\/[a-zA-Z0-9_.-]+\.png$/.test(url.pathname) ? url.href : null;
  } catch { return null; }
}
function link(value, label) {
  const href = safeLink(value);
  if (!href) return element('span', value || '주소 미기록');
  const anchor = element('a', label || value); anchor.href = href; anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'; return anchor;
}
function detailSection(title) { const section = element('section', null, 'detail-section'); section.append(element('h3', title)); return section; }
function renderProgress(job, root) {
  const section = detailSection('진행 단계');
  const history = Array.isArray(job.progressHistory) ? job.progressHistory : [];
  const events = history.length ? history : [{ at: job.startedAt, state: job.state, message: job.progress || '진행 기록이 없습니다.' }];
  const timeline = element('ol', null, 'timeline');
  for (const event of [...events].reverse()) {
    const item = element('li'); item.append(element('time', date(event.at)), element('span', event.message || '단계 기록 없음')); timeline.append(item);
  }
  section.append(timeline); root.append(section);
}
function siteBox(site, label) {
  const box = element('div'); box.append(element('strong', label));
  if (!site) { box.append(element('span', '대응 페이지 미확인')); return box; }
  box.append(link(site.url || site.finalUrl), element('p', `HTTP ${site.statusCode ?? '—'} · ${site.title || '제목 미기록'}`));
  if (site.finalUrl && site.finalUrl !== site.url) box.append(element('p', '최종 주소: '), link(site.finalUrl));
  if (Array.isArray(site.issues)) for (const issue of site.issues.slice(0, 10)) box.append(element('p', `${issue.category || '관찰'} · ${issue.message || issue.reason || '내용 미기록'}`));
  const screenshot = safeArtifact(site.screenshot);
  if (screenshot) { const anchor = link(screenshot, '화면 증거 열기'); const image = element('img'); image.src = screenshot; image.alt = `${label} 화면 증거`; image.loading = 'lazy'; anchor.replaceChildren(image); box.append(anchor); }
  return box;
}
function asText(value) { return typeof value === 'string' ? value : JSON.stringify(value); }
function renderResult(row, findings) {
  const item = element('details', null, 'result-item');
  item.dataset.rowId = String(row.id ?? row.key ?? '');
  const summary = element('summary');
  summary.append(element('span', `${row.key === '__ROOT__' ? '홈 페이지' : row.key || row.page_class || '페이지'}${row.region_id ? ` · ${row.region_id}` : ''}`), element('span', row.status || '미판정', `state-badge ${row.status === 'PASS' ? 'done' : row.status === 'ERROR' || row.status === 'FAIL' ? 'error' : ''}`));
  item.append(summary);
  const body = element('div', null, 'result-body');
  const sites = element('div', null, 'detail-grid'); sites.append(siteBox(row.baseline, '기준 A'));
  if (row.candidate) sites.append(siteBox(row.candidate, '비교 B'));
  body.append(sites);
  if (row.visual?.differencePercent != null) body.append(element('p', `화면 차이율: ${Number(row.visual.differencePercent).toFixed(2)}%`));
  if (row.visual?.note) body.append(element('p', row.visual.note));
  const diffImage = safeArtifact(row.visual?.url);
  if (diffImage) body.append(link(diffImage, '차이 이미지 열기'));
  const related = (Array.isArray(findings) ? findings : []).filter(finding =>
    (row.findingIds || []).includes(finding.id) || (finding.rowIds || []).includes(String(row.id)));
  if (related.length) {
    body.append(element('h4', `발견 사항 ${related.length}개`));
    const list = element('ul');
    for (const finding of related) list.append(element('li', `${finding.category || '분류 미기록'} · ${finding.summary || finding.subtype || '내용 미기록'}`));
    body.append(list);
  }
  const checks = Array.isArray(row.checks) ? row.checks : [];
  body.append(element('h4', `검증식 ${checks.length}개`));
  if (checks.length) {
    const list = element('ul');
    for (const check of checks) {
      const line = element('li');
      line.append(element('strong', `${check.status || '미판정'} · ${check.check_id || check.scenario_id || '검증식'}`));
      if (check.reason_code || check.message) line.append(element('span', ` — ${check.reason_code || check.message}`));
      if (check.expected != null || check.actual != null) line.append(element('code', `\n기대: ${asText(check.expected)}\n실제: ${asText(check.actual)}`));
      list.append(line);
    }
    body.append(list);
  } else body.append(element('p', '이 행에는 실행된 검증식이 기록되지 않았습니다.'));
  body.append(element('p', `QA 검수: ${row.review?.status || '미검수'}${row.review?.issueRef ? ' · 이슈 연결됨' : ''}`));
  item.append(body); return item;
}
function renderReport(job, root) {
  const report = job.report;
  if (!report) {
    const section = detailSection('검사항목');
    section.append(element('p', ['running', 'awaiting_auth'].includes(job.state) ? '검사가 진행 중입니다. 검사항목은 결과가 저장되면 표시됩니다.' : '저장된 검사항목이 없습니다.', 'empty-detail'));
    root.append(section); return;
  }
  const rows = Array.isArray(report.results) ? report.results : [];
  const totals = report.totals || {};
  const summary = detailSection('결과 요약');
  const grid = element('div', null, 'summary-stats');
  for (const [label, value] of [['결과 행', totals.resultRows ?? rows.length], ...statuses.map(status => [status, totals[status.toLowerCase()] ?? rows.filter(row => row.status === status).length])]) {
    const card = element('div', null, 'summary-stat'); card.append(element('span', label), element('strong', count(value))); grid.append(card);
  }
  summary.append(grid);
  if (report.manifest?.status === 'PARTIAL') summary.append(element('p', '일부 범위만 완료되었습니다. BLOCKED·SKIP 항목과 미실행 범위를 확인하세요.', 'empty-detail'));
  root.append(summary);
  const section = detailSection(`검사항목 ${rows.length}개`);
  const list = element('div', null, 'result-list');
  if (rows.length) for (const row of rows) list.append(renderResult(row, report.findings || []));
  else list.append(element('p', '결과 행이 없습니다. 탐색 범위와 실행 오류를 확인하세요.', 'empty-detail'));
  section.append(list); root.append(section);
}
function renderDetail(job) {
  const root = $('#runDetail');
  const expanded = renderedId === job.id ? new Set([...root.querySelectorAll('.result-item[open]')].map(item => item.dataset.rowId)) : new Set();
  root.replaceChildren(); renderedId = job.id;
  $('#detailTitle').textContent = profiles.get(job.profileId) || job.profileId || '검사 상세';
  $('#detailSubtitle').textContent = `${typeNames[job.report?.testType || job.options?.test_type] || '검사 목적 미기록'} · ${job.id}`;
  $('#fullReportLink').href = `/?run=${encodeURIComponent(job.id)}`;
  $('#fullReportLink').classList.toggle('hidden', !job.report);
  const meta = element('div', null, 'run-meta');
  for (const [name, value] of [['담당자', job.operatorId || '미기록'], ['시작', date(job.startedAt)], ['종료', job.finishedAt ? date(job.finishedAt) : '진행 중']]) {
    const span = element('span'); span.append(element('strong', `${name}: `), document.createTextNode(value)); meta.append(span);
  }
  root.append(meta);
  const current = element('div', null, 'current-status'); current.append(badge(job.state), element('strong', job.progress || stateNames[job.state] || '상태 미기록'));
  if (job.state === 'awaiting_auth') current.append(element('p', '로그인 대기 중입니다. 검사 실행 화면에서 로그인 완료 후 계속을 눌러 주세요.'));
  if (job.error) current.append(element('p', job.error));
  root.append(current);
  renderProgress(job, root); renderReport(job, root);
  for (const item of root.querySelectorAll('.result-item')) if (expanded.has(item.dataset.rowId)) item.open = true;
}
async function selectRun(id) {
  selectedId = id; history.replaceState(null, '', `?run=${encodeURIComponent(id)}`); renderList();
  try {
    const job = await get(`/api/scans/${encodeURIComponent(id)}`);
    if (selectedId !== id) return;
    renderDetail(job); loadedId = id;
    const summary = runs.find(run => run.id === id);
    loadedVersion = summary && (summary.version || summary.updatedAt || `${summary.state}:${summary.progress}:${summary.finishedAt}`);
    notice('검사 상세를 불러왔습니다.');
  }
  catch (error) { notice(error.message, true); }
}
async function refresh(force = false) {
  if (busy) return;
  busy = true;
  try {
    const response = await get('/api/scans'); runs = Array.isArray(response.scans) ? response.scans : [];
    if (selectedId && !runs.some(run => run.id === selectedId)) selectedId = null;
    if (!selectedId && runs.length) selectedId = runs[0].id;
    renderList();
    if (selectedId) {
      const summary = runs.find(run => run.id === selectedId);
      const version = summary && (summary.version || summary.updatedAt || `${summary.state}:${summary.progress}:${summary.finishedAt}`);
      if (force || loadedId !== selectedId || loadedVersion !== version) {
        const id = selectedId;
        const job = await get(`/api/scans/${encodeURIComponent(id)}`);
        if (selectedId === id) { renderDetail(job); loadedId = id; loadedVersion = version; }
      }
    }
    else {
      loadedId = null; loadedVersion = null;
      $('#detailTitle').textContent = '검사 상세'; $('#detailSubtitle').textContent = '왼쪽 목록에서 검사를 선택하세요.';
      $('#fullReportLink').classList.add('hidden');
      $('#runDetail').replaceChildren(element('p', '검사를 선택하면 진행 단계와 검사항목이 여기에 표시됩니다.', 'empty-detail'));
    }
    notice(`${runs.length}개 검사 이력을 불러왔습니다.`);
  } catch (error) { notice(error.message, true); }
  finally { busy = false; }
}
for (const button of document.querySelectorAll('.run-filter')) button.addEventListener('click', () => {
  filter = button.dataset.filter;
  for (const entry of document.querySelectorAll('.run-filter')) { const active = entry === button; entry.classList.toggle('active', active); entry.setAttribute('aria-pressed', String(active)); }
  renderList();
});
$('#refreshRuns').addEventListener('click', () => refresh(true));
async function init() {
  try { const boot = await get('/api/bootstrap'); profiles = new Map((boot.profiles || []).map(profile => [profile.id, profile.label || profile.id])); if (boot.version) $('#versionPill').textContent = `v${boot.version} · LOCAL`; }
  catch { /* Run IDs and state still render without profile labels. */ }
  await refresh();
  const poll = async () => { if (!document.hidden) await refresh(); setTimeout(poll, document.hidden ? 12000 : 4000); };
  setTimeout(poll, 4000);
}
init();
