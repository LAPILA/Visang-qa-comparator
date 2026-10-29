"""Validated run configuration. No passwords or browser sessions are serialized."""
from __future__ import annotations

import json
import math
import re
from urllib.parse import urlsplit


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
    demo.pop('options', None)
    common = {'maxPages': 5, 'maxDepth': 2, 'maxActions': 5, 'timeoutSeconds': 180,
              'visualThreshold': 2, 'mode': 'combined', 'aliases': [], 'regions': [],
              'safeActions': [], 'scenarioIds': [], 'allowedPaths': [], 'allowedHosts': []}
    demo['defaults'] = {**common, **demo['defaults']}
    definitions = [
        ('elementary-pc', '초등 PC', 'https://e.vivasam.com/main', 'https://stg-e.vivasam.com/main', False),
        ('secondary-pc', '중고등 PC', 'https://v.vivasam.com/', 'https://stg-v.vivasam.com/main', False),
        ('elementary-mobile', '초등 모바일', 'https://me.vivasam.com/#/', 'https://stg-me.vivasam.com/', False),
        ('secondary-mobile', '중고등 모바일 · STG 주소 확인 필요', 'https://mv.vivasam.com/#/', '', True),
    ]
    result = [demo]
    for key, label, baseline, candidate, disabled in definitions:
        result.append({'id': key, 'label': label, 'baselineUrl': baseline, 'candidateUrl': candidate,
                       'disabled': disabled, 'description': '실사이트 미검증 · 시작 페이지 외 이동은 경로 승인이 필요합니다.',
                       'defaults': dict(common)})
    result.append({'id': 'custom', 'label': '직접 입력', 'baselineUrl': '', 'candidateUrl': '',
                   'description': '허용한 경로·버튼만 실행합니다. 기능 시나리오는 현재 합성 데모에서 지원합니다.',
                   'defaults': dict(common)})
    return result


def public_options(options):
    names = {'route_aliases': 'aliases', 'safe_actions': 'safeActions', 'scenario_ids': 'scenarioIds',
             'allowed_paths': 'allowedPaths', 'allowed_hosts': 'allowedHosts', 'max_pages': 'maxPages',
             'max_depth': 'maxDepth', 'max_actions': 'maxActions', 'timeout_seconds': 'timeoutSeconds',
             'visual_threshold': 'visualThreshold', 'manual_login': 'manualLogin'}
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
    merged = {**profile['defaults'], **data}
    baseline = validate_url(merged.get('baselineUrl') or profile['baselineUrl'])
    candidate = validate_url(merged.get('candidateUrl') or profile['candidateUrl'])
    if profile_id == 'synthetic-demo' and (baseline != profile['baselineUrl'] or candidate != profile['candidateUrl']):
        raise ValueError('합성 데모 URL은 변경할 수 없습니다. 다른 URL은 직접 입력 프로필을 사용하세요.')
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
    allowed_hosts.update(urlsplit(url).netloc.lower() for url in (baseline, candidate))
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
        'profile_id': profile_id, 'operator_id': _text(merged.get('operatorId', 'QA-A'), '담당자', 50),
        'mode': mode, 'max_pages': _number(merged, 'maxPages', 5, 1, 30, True),
        'max_depth': _number(merged, 'maxDepth', 2, 0, 4, True),
        'max_actions': _number(merged, 'maxActions', 5, 0, 200 if profile_id == 'synthetic-demo' else 50, True),
        'timeout_seconds': _number(merged, 'timeoutSeconds', 180, 15, 600, True),
        'action_interval': _number(merged, 'actionInterval', 0.25 if profile_id == 'synthetic-demo' else 1, 0.1, 10),
        'visual_threshold': _number(merged, 'visualThreshold', 2, 0.1, 100),
        'manual_login': _boolean(merged.get('manualLogin', False)), 'viewport': viewport,
        'route_aliases': aliases, 'regions': regions, 'safe_actions': actions,
        'allowed_hosts': sorted(allowed_hosts), 'allowed_paths': paths, 'scenario_ids': scenarios,
        'data_policy': 'LIVE_INDEPENDENT',
    }
