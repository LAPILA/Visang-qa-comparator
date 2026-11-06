"""Validated run configuration. No passwords or browser sessions are serialized."""
from __future__ import annotations

import json
import math
import re
import uuid
from copy import deepcopy
from urllib.parse import urlsplit

from .environments import PRODUCT_ENVIRONMENTS

TEST_TYPES = ('comparison', 'single', 'regression', 'conditional')
CRAWL_SCOPES = ('approved_paths', 'same_origin_readonly')
# Only static dependencies observed in the supplied templates/run are preapproved.
# These hosts never become navigation, API, or manual-auth host permissions.
# Static asset / SDK hosts observed in real runs (2026-11-04). Passive GET resources only:
# this list never approves navigation, XHR or login hosts. Trackers are deliberately absent.
_SHARED_ASSET_HOSTS = ['www.vivasam.com', 'stg.vivasam.com', 'dn.vivasam.com', 'dn22.vivasam.com',
                       'fonts.googleapis.com', 'fonts.gstatic.com', 'code.jquery.com',
                       'developers.kakao.com', 'dapi.kakao.com', 't1.kakaocdn.net', 'accounts.google.com']
PROFILE_RESOURCE_HOSTS = {
    'elementary-pc': list(_SHARED_ASSET_HOSTS),
    'secondary-pc': list(_SHARED_ASSET_HOSTS),
    'elementary-mobile': list(_SHARED_ASSET_HOSTS),
    'secondary-mobile': list(_SHARED_ASSET_HOSTS),
}
XHR_POLICIES = ('allow_allowed_hosts', 'block_writes')
AUTH_MODES = ('anonymous', 'login', 'manual')
OBSERVATION_MODES = ('strict', 'lenient')
SAFETY_LEVELS = ('strict', 'test_account')


def validate_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError('URL을 입력하세요. (최대 2,000자)')
    value = value.strip()
    if any(ord(char) < 32 for char in value):
        raise ValueError('URL에는 제어 문자를 사용할 수 없습니다.')
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise ValueError('http:// 또는 https:// URL만 지원합니다.')
    if parts.username or parts.password:
        raise ValueError('URL에 아이디 또는 비밀번호를 넣을 수 없습니다.')
    try:
        parts.port
    except ValueError as exc:
        raise ValueError('URL 포트가 올바르지 않습니다.') from exc
    return value


def _array(value, label, limit=100):
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else []
        except json.JSONDecodeError as exc:
            raise ValueError(f'{label}: 올바른 JSON 배열을 입력하세요.') from exc
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f'{label}: 최대 {limit}개의 배열이어야 합니다.')
    return value


def _lines(value, label):
    if isinstance(value, str):
        value = [line.strip() for line in value.splitlines() if line.strip()]
    return _array(value, label)


def _number(data, name, default, low, high, integer=False):
    raw = data.get(name, default)
    if isinstance(raw, bool):
        raise ValueError(f'{name}: 숫자를 입력하세요.')
    try:
        number = float(raw)
        if not math.isfinite(number) or not low <= number <= high:
            raise ValueError()
        if integer and not number.is_integer():
            raise ValueError()
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{name}: {low}~{high} 범위의 {"정수" if integer else "숫자"}를 입력하세요.') from exc
    return int(number) if integer else number


def _boolean(value):
    if value in (True, 'true', 'on', '1', 1):
        return True
    if value in (False, None, '', 'false', 'off', '0', 0):
        return False
    raise ValueError('로그인 옵션이 올바르지 않습니다.')


def _text(value, label, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{label}: 1~{maximum}자로 입력하세요.')
    if any(ord(char) < 32 for char in value):
        raise ValueError(f'{label}: 제어 문자는 사용할 수 없습니다.')
    return value.strip()


def profiles(base_origin):
    from qa.demo import demo_profile
    demo = demo_profile(base_origin)
    demo_options = demo.get('options', {})
    demo['defaults'] = public_options(demo_options)
    demo.setdefault('label', '합성 데모 · 정상 차이와 결함')
    demo.setdefault('description', '외부 접속 없이 매칭·영역 비교·기능 시나리오를 확인합니다.')
    demo.setdefault('environments', [])
    demo.setdefault('baselineEnvironmentId', 'custom')
    demo.setdefault('candidateEnvironmentId', 'custom')
    demo.pop('options', None)
    common = {'maxPages': 5, 'maxDepth': 2, 'maxActions': 5, 'timeoutSeconds': 180,
              'visualThreshold': 2, 'mode': 'combined', 'aliases': [], 'regions': [],
              'safeActions': [], 'scenarioIds': [], 'allowedPaths': [], 'allowedHosts': [],
              'testType': 'comparison', 'conditions': [], 'privateMaskSelectors': [],
              'pairStartPages': True, 'resourceHosts': [], 'crawlScope': 'approved_paths',
              'baselineName': 'A', 'candidateName': 'B'}
    demo['defaults'] = {**common, **demo['defaults']}
    definitions = [('elementary-pc', '초등 PC'), ('secondary-pc', '중고등 PC'),
                   ('elementary-mobile', '초등 모바일'), ('secondary-mobile', '중고등 모바일')]
    result = [demo]
    for key, label in definitions:
        environments = deepcopy(PRODUCT_ENVIRONMENTS[key])
        by_id = {item['id']: item for item in environments}
        result.append({'id': key, 'label': label,
                       'baselineUrl': by_id['production']['url'], 'candidateUrl': by_id['staging']['url'],
                       'baselineEnvironmentId': 'production', 'candidateEnvironmentId': 'staging',
                       'environments': environments, 'disabled': False,
                       'description': '사용자 등록 주소 · 제품과 A/B 환경을 선택하세요. 실제 접속·로그인 여부는 검사에서 확인합니다.',
                       'defaults': {**deepcopy(common), 'resourceHosts': list(PROFILE_RESOURCE_HOSTS.get(key, [])),
                                    'observationMode': 'lenient', 'visualThreshold': 8, 'autoDismiss': True,
                                    # vivasam mobile/PC gate: every route lands on /coverPage (or /#/coverPage) until dismissed.
                                    'entry': {'selector': 'button, a, [role=button]',
                                              'text': '모바일웹으로 계속하기|모바일 웹으로 이동하기' if 'mobile' in key else 'PC버전으로 계속하기|PC 버전으로 계속하기',
                                              'urlPattern': '*coverPage*', 'sides': 'both'},
                                    'baselineName': by_id['production']['label'], 'candidateName': by_id['staging']['label']}})
    result.append({'id': 'custom', 'label': '직접 입력', 'baselineUrl': '', 'candidateUrl': '',
                   'environments': [], 'baselineEnvironmentId': 'custom', 'candidateEnvironmentId': 'custom',
                   'description': '허용한 경로·버튼만 실행합니다. 기능 시나리오는 현재 합성 데모에서 지원합니다.',
                   'defaults': dict(common)})
    return result


def _resolve_environment(data, profile, side):
    entries = {item['id']: item for item in profile.get('environments', [])}
    field = side + 'EnvironmentId'
    requested = data.get(field)
    if requested is not None and (not isinstance(requested, str) or (requested != 'custom' and requested not in entries)):
        raise ValueError(f'{field}: 현재 제품에 등록된 환경 또는 custom을 선택하세요.')
    raw_url = data.get(side + 'Url')
    if requested in entries:
        entry = entries[requested]
        url = validate_url(raw_url or entry['url'])
        if url != entry['url']:
            raise ValueError(f'{field}: 등록 URL과 다릅니다. URL을 직접 바꾸려면 custom을 선택하세요.')
        return url, requested, entry['label']
    if requested == 'custom' and not raw_url:
        raise ValueError(f'{side}Url: 직접 입력 URL이 필요합니다.')
    url = validate_url(raw_url or profile[side + 'Url'])
    match = next((item for item in entries.values() if item['url'] == url), None)
    identifier = 'custom' if requested == 'custom' or not match else match['id']
    label = match['label'] if match and identifier != 'custom' else ('A' if side == 'baseline' else 'B')
    return url, identifier, label


_LOGIN_SELECTOR_KEYS = ('usernameSelector', 'passwordSelector', 'submitSelector', 'successSelector', 'failureSelector')


def _login_config(value):
    """Validate the login *form description* only. Credentials never pass through here."""
    if value in (None, '', False, {}):
        return None
    if not isinstance(value, dict):
        raise ValueError('login 설정은 객체여야 합니다.')
    forbidden = {key for key in value if key.lower() in {'password', 'pw', 'passwd', 'id', 'username', 'user', 'account', 'token', 'cookie'}}
    if forbidden:
        raise ValueError('login 설정에는 선택자와 URL만 넣습니다. 계정·비밀번호는 환경변수나 secrets 파일로만 제공하세요.')
    result = {'url': validate_url(value.get('url')) if value.get('url') else None}
    for key in _LOGIN_SELECTOR_KEYS:
        raw = value.get(key)
        result[key] = _text(raw, 'login.' + key, 300) if raw not in (None, '') else None
    explicit = [result[key] for key in ('usernameSelector', 'passwordSelector', 'submitSelector')]
    if any(explicit) and not all(explicit):
        raise ValueError('login 선택자는 아이디·비밀번호·버튼 셋을 모두 적거나, 모두 비워 자동 탐지를 사용하세요.')
    result['auto'] = not all(explicit)
    result['accountKey'] = _text(value.get('accountKey', 'default'), 'login.accountKey', 50)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', result['accountKey']):
        raise ValueError('login.accountKey는 영문·숫자·._-만 사용합니다.')
    return result


def _credential_refs(value):
    """Which 프로젝트 설정 environment supplies each side's login ID/PW. IDs only, never secrets."""
    if value in (None, '', {}):
        return {}
    if not isinstance(value, dict) or set(value) - {'a', 'b'}:
        raise ValueError("credentialRefs는 {'a': {...}, 'b': {...}} 형식이어야 합니다.")
    refs = {}
    for side, ref in value.items():
        if ref in (None, '', {}):
            continue
        if not isinstance(ref, dict) or set(ref) - {'projectId', 'environmentId'}:
            raise ValueError('credentialRefs 항목에는 projectId·environmentId만 넣습니다.')
        try:
            refs[side] = {key: str(uuid.UUID(str(ref.get(key, '')))) for key in ('projectId', 'environmentId')}
        except ValueError as exc:
            raise ValueError('credentialRefs의 프로젝트·환경 ID 형식이 올바르지 않습니다.') from exc
    return refs


def _auth_mode(merged, login, manual_login):
    """One authoritative 인증 상태: 비로그인 / 로그인(테스트 계정) / 수동 로그인 — never two at once."""
    mode = merged.get('authMode')
    if mode in (None, ''):
        mode = 'manual' if manual_login else 'login' if login else 'anonymous'
    if mode not in AUTH_MODES:
        raise ValueError('authMode는 anonymous(비로그인), login(로그인), manual(수동 로그인) 중 하나여야 합니다.')
    if mode == 'login':
        return mode, login or _login_config({'accountKey': 'default'}), False
    if mode == 'manual':
        return mode, None, True
    return mode, None, False


def _entry_config(value):
    """A single approved click that dismisses a cover/landing gate on the start page."""
    if value in (None, '', False, {}):
        return None
    if not isinstance(value, dict):
        raise ValueError('entry 설정은 객체여야 합니다.')
    selector = value.get('selector')
    if not selector:
        raise ValueError('entry.selector(통과 버튼 선택자)는 필수입니다.')
    result = {'selector': _text(selector, 'entry.selector', 300)}
    for key in ('text', 'urlPattern'):
        raw = value.get(key)
        result[key] = _text(raw, 'entry.' + key, 300) if raw not in (None, '') else None
    sides = value.get('sides', 'both')
    if sides not in ('a', 'b', 'both'):
        raise ValueError("entry.sides는 'a', 'b', 'both' 중 하나여야 합니다.")
    result['sides'] = sides
    return result


def public_options(options):
    names = {'route_aliases': 'aliases', 'safe_actions': 'safeActions', 'scenario_ids': 'scenarioIds',
             'allowed_paths': 'allowedPaths', 'allowed_hosts': 'allowedHosts', 'max_pages': 'maxPages',
             'max_depth': 'maxDepth', 'max_actions': 'maxActions', 'timeout_seconds': 'timeoutSeconds',
             'visual_threshold': 'visualThreshold', 'manual_login': 'manualLogin',
             'test_type': 'testType', 'previous_run_id': 'previousRunId',
             'private_mask_selectors': 'privateMaskSelectors',
             'pair_start_pages': 'pairStartPages', 'resource_hosts': 'resourceHosts',
             'route_equivalence': 'routeEquivalence', 'login': 'login', 'entry': 'entry',
             'xhr_policy': 'xhrPolicy', 'dismiss_selectors': 'dismissSelectors',
             'observation_mode': 'observationMode', 'smoke_actions': 'smokeActions', 'smoke_action_limit': 'smokeActionLimit',
             'safety_level': 'safetyLevel', 'smoke_fill_text': 'smokeFillText', 'capture_settle_ms': 'captureSettleMs',
             'auto_dismiss': 'autoDismiss', 'instance_sample_limit': 'instanceSampleLimit',
             'auth_mode': 'authMode', 'credential_refs': 'credentialRefs',
             'crawl_scope': 'crawlScope', 'baseline_name': 'baselineName', 'candidate_name': 'candidateName',
             'baseline_environment_id': 'baselineEnvironmentId', 'candidate_environment_id': 'candidateEnvironmentId'}
    return {names.get(key, key): value for key, value in options.items()
            if key not in ('profile_id', 'operator_id', 'baseline_url', 'candidate_url')}


def parse_options(data, base_origin):
    if not isinstance(data, dict):
        raise ValueError('JSON 객체가 필요합니다.')
    # Deliberately refuse credential-bearing requests, even if a modified UI sends them.
    if any(key.lower() in {'password', 'pw', 'passwd', 'cookie', 'token', 'storage_state'} for key in data):
        raise ValueError('비밀번호·인증 상태는 API에 전달하지 마세요. 브라우저에서 직접 로그인하세요.')
    profile_id = data.get('profileId', 'custom')
    available = {item['id']: item for item in profiles(base_origin)}
    if profile_id not in available or available[profile_id].get('disabled'):
        raise ValueError('사용 가능한 환경 프로필을 선택하세요.')
    profile = available[profile_id]
    merged = deepcopy({**profile['defaults'], **data})
    test_type = merged.get('testType', 'comparison')
    if test_type not in TEST_TYPES:
        raise ValueError('테스트 목적은 comparison/single/regression/conditional 중 하나여야 합니다.')
    crawl_scope = merged.get('crawlScope', 'approved_paths')
    if crawl_scope not in CRAWL_SCOPES:
        raise ValueError('탐색 범위는 approved_paths 또는 same_origin_readonly여야 합니다.')
    try:
        pair_start_pages = _boolean(merged.get('pairStartPages', test_type == 'comparison'))
    except ValueError as exc:
        raise ValueError('시작 페이지 비교 옵션은 true 또는 false여야 합니다.') from exc
    pair_start_pages = pair_start_pages if test_type == 'comparison' else False
    try:
        route_equivalence = _boolean(merged.get('routeEquivalence', True))
    except ValueError as exc:
        raise ValueError('동등 라우트 매칭 옵션은 true 또는 false여야 합니다.') from exc
    auth_mode, login, manual_login = _auth_mode(merged, _login_config(merged.get('login')),
                                                _boolean(merged.get('manualLogin', False)))
    credential_refs = _credential_refs(merged.get('credentialRefs')) if auth_mode == 'login' else {}
    entry = _entry_config(merged.get('entry'))
    xhr_policy = merged.get('xhrPolicy', 'allow_allowed_hosts')
    if xhr_policy not in XHR_POLICIES:
        raise ValueError('xhrPolicy는 allow_allowed_hosts 또는 block_writes여야 합니다.')
    dismiss_selectors = _array(merged.get('dismissSelectors', []), '팝업 닫기 선택자', 10)
    observation_mode = merged.get('observationMode', 'strict')
    if observation_mode not in OBSERVATION_MODES:
        raise ValueError('observationMode는 strict 또는 lenient여야 합니다.')
    safety_level = merged.get('safetyLevel', 'strict')
    if safety_level not in SAFETY_LEVELS:
        raise ValueError('safetyLevel은 strict 또는 test_account여야 합니다.')
    try:
        smoke_actions = _boolean(merged.get('smokeActions', False))
    except ValueError as exc:
        raise ValueError('smokeActions는 true 또는 false여야 합니다.') from exc
    for selector in dismiss_selectors:
        _text(selector, '팝업 닫기 선택자', 300)
    baseline, baseline_environment_id, baseline_label = _resolve_environment(data, profile, 'baseline')
    if test_type == 'comparison':
        candidate, candidate_environment_id, candidate_label = _resolve_environment(data, profile, 'candidate')
    else:
        candidate, candidate_environment_id, candidate_label = None, None, None
    baseline_name = _text(data.get('baselineName', baseline_label), '환경 A 이름', 50)
    candidate_name = _text(data.get('candidateName', candidate_label), '환경 B 이름', 50) if test_type == 'comparison' else None
    if profile_id == 'synthetic-demo' and (baseline != profile['baselineUrl'] or
            (test_type == 'comparison' and candidate != profile['candidateUrl'])):
        raise ValueError('합성 데모 URL은 변경할 수 없습니다. 다른 URL은 직접 입력 프로필을 사용하세요.')
    previous_run_id = merged.get('previousRunId') or None
    if test_type == 'regression':
        try:
            if str(uuid.UUID(previous_run_id)) != previous_run_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError('회귀 비교할 과거 실행을 선택하세요.') from exc
    else:
        previous_run_id = None
    from qa.conditions import validate_conditions
    conditions = validate_conditions(merged.get('conditions', []))
    if test_type == 'conditional' and not conditions:
        raise ValueError('조건 기반 검사에는 최소 1개의 조건 계약이 필요합니다.')
    private_masks = _array(merged.get('privateMaskSelectors', []), '민감 영역 마스크', 30)
    private_masks = [_text(selector, '민감 영역 선택자', 500) for selector in private_masks]
    mode = merged.get('mode', 'combined')
    if mode not in ('combined', 'visual', 'discovery'):
        raise ValueError('검사 유형이 올바르지 않습니다.')
    aliases = _array(merged.get('aliases', []), '경로 매핑')
    classes = set()
    for alias in aliases:
        if not isinstance(alias, dict):
            raise ValueError('경로 매핑 항목은 객체여야 합니다.')
        for side in ('baseline', 'candidate'):
            path = _text(alias.get(side), '매핑 경로', 500)
            if not path.startswith('/') or path.startswith('//'):
                raise ValueError('매핑은 /로 시작하는 상대 경로만 허용합니다.')
        name = _text(alias.get('page_class'), '페이지 분류', 100)
        if name in classes:
            raise ValueError('페이지 분류가 중복된 매핑은 사용할 수 없습니다.')
        classes.add(name)
    regions = _array(merged.get('regions', []), '비교 영역', 30)
    region_ids = set()
    for region in regions:
        if not isinstance(region, dict):
            raise ValueError('영역은 객체여야 합니다.')
        name = _text(region.get('id'), '영역 ID', 100)
        if name in region_ids:
            raise ValueError('영역 ID가 중복됩니다.')
        region_ids.add(name)
        _text(region.get('selector'), '영역 선택자', 500)
        region['required'] = _boolean(region.get('required', False))
        for selector in _array(region.get('mask_selectors', []), '마스크', 30):
            _text(selector, '마스크 선택자', 500)
    actions = _array(merged.get('safeActions', []), '허용 동작', 30)
    for action in actions:
        if not isinstance(action, dict) or action.get('kind', 'click') != 'click':
            raise ValueError('허용 동작은 click 객체만 지원합니다.')
        _text(action.get('id'), '동작 ID', 100)
        _text(action.get('selector'), '동작 선택자', 500)
        if action.get('url_pattern') is not None:
            _text(action['url_pattern'], '동작 URL 범위', 500)
    allowed_hosts = set()
    for host in _lines(merged.get('allowedHosts', []), '허용 호스트'):
        host = _text(host, '호스트', 255).lower()
        parsed = urlsplit('https://' + host)
        if (parsed.netloc != host or parsed.path or parsed.query or parsed.fragment or
                not parsed.hostname or parsed.username or parsed.password or '*' in host):
            raise ValueError('허용 호스트는 정확한 host[:port]만 입력하세요.')
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError('허용 호스트의 포트가 올바르지 않습니다.') from exc
        allowed_hosts.add(host)
    allowed_hosts.update(urlsplit(url).netloc.lower() for url in (baseline, candidate) if url)
    resource_hosts = set()
    for host in _lines(merged.get('resourceHosts', []), '정적 리소스 호스트'):
        host = _text(host, '정적 리소스 호스트', 255).lower()
        parsed = urlsplit('https://' + host)
        if (parsed.netloc != host or parsed.path or parsed.query or parsed.fragment or
                not parsed.hostname or parsed.username or parsed.password or '*' in host or
                any(char.isspace() for char in host)):
            raise ValueError('정적 리소스 호스트는 정확한 host[:port]만 입력하세요.')
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError('정적 리소스 호스트의 포트가 올바르지 않습니다.') from exc
        resource_hosts.add(host)
    paths = _lines(merged.get('allowedPaths', []), '허용 경로')
    for path in paths:
        _text(path, '허용 경로', 500)
        if not path.startswith('/') or path.startswith('//') or path in ('/*', '/**'):
            raise ValueError('허용 경로는 /로 시작하는 제한된 경로여야 합니다. 전체 /*는 허용하지 않습니다.')
    scenarios = _array(merged.get('scenarioIds', []), '시나리오', 10)
    for scenario in scenarios:
        _text(scenario, '시나리오 ID', 100)
    viewport = {'width': 390, 'height': 844} if 'mobile' in profile_id else {'width': 1365, 'height': 768}
    return {
        'baseline_url': baseline, 'candidate_url': candidate,
        'baseline_environment_id': baseline_environment_id, 'candidate_environment_id': candidate_environment_id,
        'baseline_name': baseline_name, 'candidate_name': candidate_name, 'crawl_scope': crawl_scope,
        'test_type': test_type, 'previous_run_id': previous_run_id, 'conditions': conditions,
        'pair_start_pages': pair_start_pages, 'route_equivalence': route_equivalence, 'login': login, 'entry': entry,
        'xhr_policy': xhr_policy, 'dismiss_selectors': dismiss_selectors, 'observation_mode': observation_mode,
        'smoke_actions': smoke_actions, 'smoke_action_limit': _number(merged, 'smokeActionLimit', 20, 0, 100, True),
        'safety_level': safety_level, 'smoke_fill_text': _text(merged.get('smokeFillText', 'QA자동테스트'), '스모크 입력값', 100),
        'capture_settle_ms': _number(merged, 'captureSettleMs', 4000, 0, 15000, True),
        'auto_dismiss': _boolean(merged.get('autoDismiss', False)),
        'instance_sample_limit': _number(merged, 'instanceSampleLimit', 3, 0, 50, True),
        'resource_hosts': sorted(resource_hosts),
        'private_mask_selectors': private_masks,
        'profile_id': profile_id, 'operator_id': _text(merged.get('operatorId', 'QA-A'), '담당자', 50),
        'mode': mode, 'max_pages': _number(merged, 'maxPages', 5, 1, 200, True),
        'max_depth': _number(merged, 'maxDepth', 2, 0, 8, True),
        'max_actions': _number(merged, 'maxActions', 5, 0, 1000, True),
        'timeout_seconds': _number(merged, 'timeoutSeconds', 180, 15, 3600, True),
        'action_interval': _number(merged, 'actionInterval', 0.25 if profile_id == 'synthetic-demo' else 1, 0.1, 10),
        'visual_threshold': _number(merged, 'visualThreshold', 2, 0.1, 100),
        'manual_login': manual_login, 'auth_mode': auth_mode, 'credential_refs': credential_refs, 'viewport': viewport,
        'route_aliases': aliases, 'regions': regions, 'safe_actions': actions,
        'allowed_hosts': sorted(allowed_hosts), 'allowed_paths': paths, 'scenario_ids': scenarios,
        'data_policy': 'LIVE_INDEPENDENT',
    }
