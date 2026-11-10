// 대시보드: 실행 목록 + 최근 완료 실행의 검수 분류·7상태 요약. (원안: origin/1105_mia, 테마·검수 분류 반영)
const $ = selector => document.querySelector(selector);
const TYPES = { comparison: '환경 비교', single: '단일 환경', regression: '회귀', conditional: '조건 기반 UI' };
const STATES = { running: '실행 중', awaiting_auth: '로그인 대기', done: '완료', cancelled: '중단', error: '오류' };
const STATUSES = ['PASS', 'FAIL', 'DIFF', 'REVIEW', 'SKIP', 'BLOCKED', 'ERROR'];
const TRIAGE = [['ISSUE', '이슈 등록 후보', '기능 미작동·필수 요소 누락·페이지 오류'], ['HUMAN_CHECK', '대인체크', 'DB·이미지 차이, 매핑, 오류 관찰'],
  ['RETEST', '재검 필요', '로그인·데이터·한도 문제로 미검사'], ['OK', '정상', '실행한 검증식 통과'], ['NOT_RUN', '미실행', '정책·범위상 제외']];

function notice(message, error = false) { const node = $('#notice'); node.textContent = message; node.className = `notice ${error ? 'error-notice' : 'success-notice'}`; }
function date(value) { if (!value) return '시각 없음'; const d = new Date(value); return Number.isNaN(d.getTime()) ? '시각 없음' : new Intl.DateTimeFormat('ko-KR', { dateStyle: 'short', timeStyle: 'short' }).format(d); }
function node(tag, text, className) { const element = document.createElement(tag); element.textContent = String(text); if (className) element.className = className; return element; }
async function get(path) { const response = await fetch(path, { cache: 'no-store' }); if (!response.ok) throw new Error(`서버 응답 오류 (HTTP ${response.status})`); return response.json(); }

function triageTiles(triage) {
  const root = $('#triageStats'); root.replaceChildren();
  for (const [key, label, hint] of TRIAGE) {
    const tile = node('a', '', `triage-tile ${key}`); tile.href = '/';
    tile.append(node('span', label, 'triage-tile-label'), node('strong', triage ? Number(triage[key] || 0) : '—'), node('small', hint));
    root.append(tile);
  }
}

async function dashboard() {
  try {
    const [list, boot] = await Promise.all([get('/api/scans'), get('/api/bootstrap')]);
    if (boot.version) $('#versionPill').textContent = `v${boot.version} · LOCAL`;
    const jobs = Array.isArray(list.scans) ? list.scans : [];
    const names = new Map((boot.profiles || []).map(p => [p.id, p.label || p.id]));
    const latest = jobs.find(j => j.state === 'done' && j.totals);
    const totals = latest?.totals || {};
    const triage = totals.triage || null;
    $('#totalRuns').textContent = jobs.length;
    $('#activeRuns').textContent = jobs.filter(j => ['running', 'awaiting_auth'].includes(j.state)).length;
    $('#reviewCount').textContent = latest ? Number(triage?.HUMAN_CHECK ?? totals.review ?? 0) : '—';
    $('#failureCount').textContent = latest ? Number(triage?.ISSUE ?? (Number(totals.fail || 0) + Number(totals.error || 0))) : '—';
    $('#latestLabel').textContent = latest ? `${date(latest.startedAt)} · ${names.get(latest.profileId) || latest.profileId || '프로필 미기록'} · ${TYPES[latest.testType] || ''}` : '완료된 실행이 없습니다.';
    triageTiles(triage);
    const rows = $('#statusRows'); rows.replaceChildren();
    for (const status of STATUSES) { const row = node('div', '', 'status-row'); const badge = node('span', status, `status ${status}`); row.append(badge, node('strong', latest ? Number(totals[status.toLowerCase()] || 0) : '—')); rows.append(row); }
    const body = $('#runsBody'); body.replaceChildren();
    for (const job of jobs.slice(0, 15)) {
      const tr = document.createElement('tr');
      const link = node('a', date(job.startedAt)); link.href = '/m_results.html?run=' + encodeURIComponent(job.id);
      const first = document.createElement('td'); first.append(link);
      const state = document.createElement('td'); state.append(node('span', STATES[job.state] || job.state || '미기록', `job-state ${job.state || ''}`));
      const t = job.totals?.triage;
      tr.append(first, node('td', names.get(job.profileId) || job.profileId || '미기록'), node('td', TYPES[job.testType] || job.testType || '미기록'), state,
        node('td', t ? `${t.ISSUE || 0} / ${t.HUMAN_CHECK || 0} / ${t.OK || 0}` : '—'), node('td', job.operatorId || '미기록'));
      body.append(tr);
    }
    if (!jobs.length) { const tr = document.createElement('tr'); const td = node('td', '아직 실행 이력이 없습니다. 검사 실행 화면에서 첫 검사를 준비하세요.'); td.colSpan = 6; tr.append(td); body.append(tr); }
    notice(`${jobs.length}개 실행 이력을 불러왔습니다.`);
  } catch (error) { notice(error.message, true); }
}
$('#refresh').addEventListener('click', dashboard);
dashboard();
