"""Bounded two-environment runner, evolved from the original Playwright crawler.

Discovery and approval are separate. No browser/network work happens at import time.
"""
from __future__ import annotations

import fnmatch
import platform
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from .comparison import image_diff, visual_check
from .matching import match_pages, normalize_url, page_key
from .policy import (aggregate_status, check, classify_candidate, dangerous_action,
                     host_allowed, http_observation, route_allowed, sanitize_message, sanitize_url)

DISCOVER_JS = r'''(rules) => {
  const selector = el => {
    if (el.id) return '#' + CSS.escape(el.id);
    const path = [];
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const siblings = n.parentElement ? [...n.parentElement.children].filter(x => x.tagName === n.tagName) : [n];
      path.unshift(n.tagName.toLowerCase() + (siblings.length > 1 ? ':nth-of-type('+(siblings.indexOf(n)+1)+')' : ''));
      if (path.length >= 7) break;
    }
    return path.join(' > ');
  };
  const candidates = [...document.querySelectorAll('a[href],button,input[type=submit],input[type=image],[role=button],[role=link],[role=tab],[onclick],[tabindex]')].map(el => {
    const r = el.getBoundingClientRect();
    let selected = selector(el);
    for (const rule of rules) { try { if (el.matches(rule.selector)) { selected = rule.selector; break; } } catch (_) {} }
    return {selector:selected,tag:el.tagName.toLowerCase(),type:el.getAttribute('type')||'',
      role:el.getAttribute('role')||'',label:(el.getAttribute('aria-label')||el.innerText||el.getAttribute('value')||'').slice(0,120),
      href:el.href||'',formAction:el.formAction||'',download:el.hasAttribute('download'),
      visible:r.width>0&&r.height>0&&getComputedStyle(el).visibility!=='hidden',disabled:!!el.disabled,
      pageUrl:location.href};
  });
  const broken = [...document.images].filter(i => {
    const r=i.getBoundingClientRect();return r.width>0&&r.height>0&&r.top<innerHeight&&r.bottom>0&&i.complete&&i.naturalWidth===0&&!!(i.currentSrc||i.src);
  }).map(i=>i.currentSrc||i.src);
  return {title:document.title,heading:document.querySelector('h1')?.innerText?.trim().slice(0,160)||'',
    structure:[...document.querySelectorAll('main,nav,form,[role=main],h1,h2')].map(el=>el.tagName.toLowerCase()).join('|'),
    candidates,broken,iframes:document.querySelectorAll('iframe').length,
    demo:document.querySelector('[data-qa-demo="web-qa-comparator-v1"]')!==null};
}'''


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id(value):
    return sha256(str(value).encode('utf-8')).hexdigest()[:20]


def _origin(url):
    p = urlsplit(url)
    return p.scheme, p.netloc.lower()


def _public(page):
    if page is None:
        return None
    return {key: value for key, value in page.items()
            if key in ('url', 'finalUrl', 'title', 'heading', 'statusCode', 'issues', 'screenshot', 'depth',
                       'actions', 'checks', 'observedAt', 'regions', 'coverage')}


def _safe_record(page):
    result = _public(page)
    if result:
        result = dict(result)
        result['url'] = sanitize_url(result['url'])
        result['finalUrl'] = sanitize_url(result['finalUrl'])
        result['regions'] = [{k: v for k, v in region.items() if k != 'screenshotFile'} for region in page.get('regions', [])]
    return result


class Budget:
    def __init__(self, options, cancelled):
        self.started = time.monotonic()
        self.deadline = self.started + max(1, float(options.get('timeout_seconds', 180)))
        self.maximum = max(0, int(options.get('max_actions', 10)))
        self.interval = max(0, float(options.get('action_interval', 1)))
        self.cancelled = cancelled
        self.actions = 0
        self.completed = 0
        self.last_action = 0.0

    def reason(self):
        if self.cancelled():
            return 'CANCELLED'
        if time.monotonic() >= self.deadline:
            return 'TIME_LIMIT_REACHED'
        return None

    def timeout(self, cap=15000):
        return max(1, min(cap, int((self.deadline - time.monotonic()) * 1000)))

    def action(self, page):
        if self.reason() or self.actions >= self.maximum:
            return False
        while time.monotonic() - self.last_action < self.interval:
            if self.reason():
                return False
            page.wait_for_timeout(min(100, self.timeout(100)))
        self.actions += 1
        self.last_action = time.monotonic()
        return True


def _append_issue(record, category, level, message, url='', **details):
    issue = dict(category=category, level=level, message=sanitize_message(message), url=sanitize_url(url), **details)
    if issue not in record['issues']:
        record['issues'].append(issue)


def _attach_observers(page, record, context_state):
    def response_observed(response):
        try:
            observation = http_observation(response.status, response.request.resource_type,
                                           _origin(response.url) == _origin(record['url']))
            if observation:
                _append_issue(record, observation['category'], observation['level'],
                              f'{response.status} {response.request.resource_type}', response.url,
                              statusCode=response.status, resourceType=response.request.resource_type,
                              method=response.request.method)
        except Exception as exc:
            _append_issue(record, 'OBSERVATION_ERROR', 'ERROR', type(exc).__name__)

    def request_failed(request):
        try:
            if request.url in context_state['blocked_urls']:
                return
            _append_issue(record, 'NETWORK_ERROR', 'REVIEW', request.failure or 'Network failure',
                          request.url, resourceType=request.resource_type, method=request.method)
        except Exception as exc:
            _append_issue(record, 'OBSERVATION_ERROR', 'ERROR', type(exc).__name__)

    page.on('response', response_observed)
    page.on('requestfailed', request_failed)
    def page_error(exc):
        policy_interference = any(item['category'] == 'POLICY_BLOCKED' for item in record['issues'])
        _append_issue(record, 'JS_ERROR_AFTER_POLICY_BLOCK' if policy_interference else 'JS_ERROR',
                      'REVIEW' if policy_interference else 'FAIL', str(exc), page.url)

    page.on('pageerror', page_error)
    page.on('console', lambda message: _append_issue(record, 'CONSOLE_ERROR', 'REVIEW', message.text, page.url)
            if message.type == 'error' else None)
    page.on('dialog', lambda dialog: dialog.dismiss())
    page.on('download', lambda download: _append_issue(record, 'DOWNLOAD_BLOCKED', 'SKIP',
                                                       'Download was not approved.', page.url))


def _network_guard(context, options, seeds, side, state, budget):
    seed = seeds[0 if side == 'a' else 1]
    demo_prefix = '/demo/' + side + '/' if urlsplit(seed).path.startswith('/demo/' + side + '/') else None

    def guard(route):
        request = route.request
        reason = budget.reason()
        if not reason and not host_allowed(request.url, options['allowed_hosts']):
            reason = 'HOST_NOT_APPROVED'
        if not reason and not state['manual_auth']:
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                reason = 'WRITE_REQUEST_NOT_APPROVED'
            elif dangerous_action({'url': request.url}):
                reason = dangerous_action({'url': request.url})
            elif request.is_navigation_request() and not route_allowed(request.url, options, seeds):
                reason = 'ROUTE_NOT_APPROVED'
            elif request.is_navigation_request() and demo_prefix and not urlsplit(request.url).path.startswith(demo_prefix):
                reason = 'ENVIRONMENT_BOUNDARY'
        if reason:
            state['blocked_urls'].add(request.url)
            item = dict(url=sanitize_url(request.url), method=request.method, reason=reason,
                        resourceType=request.resource_type)
            state['blocked'].append(item)
            if state.get('record') is not None:
                _append_issue(state['record'], 'POLICY_BLOCKED', 'SKIP', reason, request.url,
                              resourceType=request.resource_type)
            route.abort('blockedbyclient')
        else:
            route.continue_()

    context.route('**/*', guard)


def _capture(page, record, options, artifact_root, run_id, side, budget):
    folder = Path(artifact_root) / run_id / side
    folder.mkdir(parents=True, exist_ok=True)
    name = _id(record['url'])
    private_selectors = ['input[type=password]', '[data-qa-private]', *options.get('private_mask_selectors', [])]
    private_masks = [page.locator(selector) for selector in private_selectors]
    try:
        record['maskBoxes'] = []
        for locator in private_masks:
            for index in range(locator.count()):
                box = locator.nth(index).bounding_box()
                if box:
                    record['maskBoxes'].append([box['x'], box['y'], box['width'], box['height']])
        page.screenshot(path=str(folder / (name + '.png')), full_page=False,
                        animations='disabled', caret='hide', mask=private_masks, timeout=budget.timeout(12000))
        record['screenshot'] = f'/artifacts/{run_id}/{side}/{name}.png'
        record['screenshotFile'] = str(folder / (name + '.png'))
    except Exception as exc:
        record['checks'].append(check(side + '.capture', 'ERROR', 'SCREENSHOT_ERROR',
                                      expected='Viewport evidence', actual=type(exc).__name__))
    for region in options.get('regions', []):
        region_id = region.get('id', 'region')
        required = bool(region.get('required', True))
        item = {'id': region_id, 'selector': region.get('selector'), 'required': required,
                'screenshot': None, 'screenshotFile': None}
        record['regions'].append(item)
        try:
            locator = page.locator(region['selector'])
            count = locator.count()
            if count == 0:
                item['state'] = 'MISSING'
                record['checks'].append(check(f'{side}.region.{region_id}', 'FAIL' if required else 'SKIP',
                                              'REQUIRED_REGION_MISSING' if required else 'OPTIONAL_REGION_ABSENT',
                                              expected='One visible region', actual=0, required=required))
                continue
            if count != 1:
                item['state'] = 'ERROR'
                record['checks'].append(check(f'{side}.region.{region_id}', 'ERROR', 'AMBIGUOUS_SELECTOR',
                                              expected=1, actual=count, required=required))
                continue
            if not locator.is_visible():
                item['state'] = 'HIDDEN'
                record['checks'].append(check(f'{side}.region.{region_id}', 'FAIL' if required else 'SKIP',
                                              'REGION_NOT_VISIBLE', expected='visible', actual='hidden', required=required))
                continue
            item['state'] = 'PRESENT'
            item['geometry'] = locator.bounding_box()
            item['style'] = locator.evaluate("el => { const s=getComputedStyle(el); return {display:s.display,position:s.position,fontSize:s.fontSize,color:s.color,overflow:s.overflow}; }")
            record['checks'].append(check(f'{side}.region.{region_id}', 'PASS', 'REGION_VISIBLE',
                                          expected='One visible region', actual=1, required=required))
            masks = [locator.locator(selector) for selector in region.get('mask_selectors', [])] + private_masks
            item['maskSelectors'] = list(region.get('mask_selectors', [])) + private_selectors
            item['maskedElements'] = sum(mask.count() for mask in masks)
            item['maskBoxes'] = []
            box = item['geometry']
            if box:
                for mask in masks:
                    for index in range(mask.count()):
                        masked_box = mask.nth(index).bounding_box()
                        if not masked_box:
                            continue
                        x1, y1 = max(box['x'], masked_box['x']), max(box['y'], masked_box['y'])
                        x2 = min(box['x'] + box['width'], masked_box['x'] + masked_box['width'])
                        y2 = min(box['y'] + box['height'], masked_box['y'] + masked_box['height'])
                        if x2 > x1 and y2 > y1:
                            item['maskBoxes'].append([x1 - box['x'], y1 - box['y'], x2 - x1, y2 - y1])
            filename = name + '-' + _id(region_id) + '.png'
            locator.screenshot(path=str(folder / filename), animations='disabled', caret='hide',
                               mask=masks, timeout=budget.timeout(12000))
            item['screenshotFile'] = str(folder / filename)
            item['screenshot'] = f'/artifacts/{run_id}/{side}/{filename}'
        except Exception as exc:
            item['state'] = 'ERROR'
            record['checks'].append(check(f'{side}.region.{region_id}.capture', 'ERROR', 'REGION_CAPTURE_ERROR',
                                          expected='Valid selector and captured evidence', actual=type(exc).__name__, required=required))


def _action_guard(page, record, options, budget, action):
    reason = budget.reason()
    if not reason:
        reason = dangerous_action(action)
    if not reason and action.get('url'):
        if not host_allowed(action['url'], options['allowed_hosts']):
            reason = 'HOST_NOT_APPROVED'
        elif not route_allowed(action['url'], options, (options['baseline_url'], options['candidate_url'])):
            reason = 'ROUTE_NOT_APPROVED'
    if not reason and budget.actions >= budget.maximum:
        reason = 'ACTION_LIMIT_REACHED'
    if not reason and budget.actions - options.get('_side_action_start', 0) >= options.get('_side_action_limit', budget.maximum):
        reason = 'ENVIRONMENT_ACTION_LIMIT_REACHED'
    if reason:
        record['checks'].append(check('action.guard.' + str(len(record['checks'])), 'SKIP', reason,
                                      expected='Approved action within budget', actual=action.get('kind'), required=False))
        return False
    if not budget.action(page):
        return False
    return True


def _visit(context, url, side, depth, options, artifact_root, run_id, budget, state):
    record = dict(url=url, finalUrl=url, title='', heading='', structure='', statusCode=None,
                  issues=[], checks=[], screenshot=None, screenshotFile=None, regions=[], actions=[],
                  depth=depth, observedAt=_now(), navigated=False, coverage={})
    state['record'] = record
    page = context.new_page()
    _attach_observers(page, record, state)
    try:
        response = page.goto(url, wait_until='domcontentloaded', timeout=budget.timeout())
        record['statusCode'] = response.status if response else None
        record['finalUrl'] = page.url
        if response and response.status >= 400:
            record['checks'].append(check(side + '.document', 'FAIL', 'DOCUMENT_HTTP_ERROR',
                                          expected='HTTP < 400', actual=response.status))
        elif response:
            record['checks'].append(check(side + '.document', 'PASS', 'DOCUMENT_REACHABLE',
                                          expected='HTTP < 400', actual=response.status))
        else:
            # Hash-only navigation does not necessarily have a document response.
            record['checks'].append(check(side + '.document', 'REVIEW', 'DOCUMENT_STATUS_UNAVAILABLE',
                                          expected='Document response or approved SPA contract', actual=None))
        record['navigated'] = True
        try:
            page.wait_for_load_state('load', timeout=budget.timeout(3000))
        except Exception:
            record['checks'].append(check(side + '.ready', 'REVIEW', 'LOAD_NOT_CONFIRMED',
                                          expected='Load event within capture budget', actual='timeout'))
        page.evaluate('() => Promise.race([document.fonts?.ready || Promise.resolve(), new Promise(resolve => setTimeout(resolve, 1500))])')
        page.wait_for_timeout(min(150, budget.timeout(150)))
        info = page.evaluate(DISCOVER_JS, options.get('safe_actions', []))
        record.update(title=sanitize_message(info['title'], 160), heading=sanitize_message(info['heading'], 160),
                      structure=info['structure'])
        record['coverage']['iframesUninspected'] = info['iframes']
        if info['iframes']:
            record['checks'].append(check(side + '.iframes', 'SKIP', 'IFRAME_INSPECTION_UNSUPPORTED',
                                          actual=info['iframes'], required=False))
        for broken in info['broken']:
            _append_issue(record, 'BROKEN_IMAGE', 'FAIL', 'Visible image failed to load', broken)
        seen_selectors = set()

        def register(candidates):
            for action in candidates:
                if action['selector'] in seen_selectors:
                    continue
                seen_selectors.add(action['selector'])
                allowed, reason = classify_candidate(action, options, (options['baseline_url'], options['candidate_url']))
                action.update(id=_id(url + action['selector']), allowed=allowed, reason=reason,
                              state='DISCOVERED' if allowed else 'BLOCKED')
                action['label'] = sanitize_message(action['label'], 120)
                record['actions'].append(action)

        register(info['candidates'])
        if options.get('mode') != 'discovery':
            for rule in options.get('safe_actions', []):
                if budget.reason():
                    break
                action = next((a for a in record['actions'] if a['selector'] == rule.get('selector')), None)
                if not action or not action['allowed'] or action.get('href'):
                    continue
                if not _action_guard(page, record, options, budget, action):
                    action.update(state='SKIP', reason=budget.reason() or 'ACTION_LIMIT_REACHED')
                    continue
                before = page.url
                try:
                    page.locator(rule['selector']).click(timeout=budget.timeout(5000))
                    budget.completed += 1
                    action['state'] = 'EXECUTED'
                    # Successful click dispatch is not evidence of expected application behavior.
                    record['checks'].append(check(side + '.click.' + action['id'], 'REVIEW', 'ACTION_EXPECTATION_MISSING',
                                                  expected='A configured behavior assertion', actual='Click dispatched', required=False))
                    register(page.evaluate(DISCOVER_JS, options.get('safe_actions', []))['candidates'])
                    if page.url != before:
                        page.goto(before, wait_until='domcontentloaded', timeout=budget.timeout())
                except Exception as exc:
                    action['state'] = 'ERROR'
                    record['checks'].append(check(side + '.click.' + action['id'], 'ERROR', 'ACTION_OR_RESET_ERROR',
                                                  actual=type(exc).__name__))
                    break
        # Capture the settled baseline state before scenario actions mutate local UI.
        if budget.reason():
            record['checks'].append(check(side + '.capture', 'SKIP', budget.reason(), expected='Capture within budget'))
        else:
            _capture(page, record, options, artifact_root, run_id, side, budget)
        scenario_ids = (options.get('scenario_ids', []) if options.get('mode', 'combined') == 'combined'
                        and depth == 0 and not state.get('scenario_done') else [])
        if scenario_ids and not budget.reason():
            state['scenario_done'] = True
            from .scenarios import run_scenarios
            scenario_options = dict(options)
            scenario_options['_action_guard'] = lambda action: _action_guard(page, record, options, budget, action)
            def action_completed(_action):
                budget.completed += 1
            scenario_options['_action_completed'] = action_completed
            try:
                scenario_checks = run_scenarios(page, scenario_ids, side, scenario_options,
                                               lambda: bool(budget.reason()))
                for item in scenario_checks:
                    item = dict(item)
                    item['environment'] = side
                    item['check_id'] = side + '.' + item['check_id']
                    record['checks'].append(item)
            except Exception as exc:
                record['checks'].append(check(side + '.scenario', 'ERROR', 'SCENARIO_ENGINE_ERROR',
                                              expected='Structured scenario results', actual=type(exc).__name__))
        elif scenario_ids:
            for scenario in scenario_ids:
                record['checks'].append(check(side + '.' + scenario, 'SKIP', budget.reason() or 'SCENARIO_NOT_RUN',
                                              scenario_id=scenario, expected='Scenario execution'))
    except Exception as exc:
        reason = budget.reason()
        policy_blocked = url in state['blocked_urls'] or any(i['category'] == 'POLICY_BLOCKED' for i in record['issues'])
        record['checks'].append(check(side + '.navigation', 'SKIP' if reason or policy_blocked else 'ERROR',
                                      reason or ('POLICY_BLOCKED' if policy_blocked else 'NAVIGATION_ERROR'),
                                      expected='Approved, reachable page', actual=type(exc).__name__))
    finally:
        if depth == 0 and options.get('mode', 'combined') == 'combined' and not state.get('scenario_done'):
            for scenario in options.get('scenario_ids', []):
                record['checks'].append(check(side + '.' + scenario, 'SKIP', 'PAGE_PREREQUISITE_UNAVAILABLE',
                                              scenario_id=scenario, expected='Seed page ready for scenarios'))
        # Do not export raw candidate URLs containing authentication query values.
        for action in record['actions']:
            action['_navigation_url'] = action.get('href')
            for key in ('href', 'pageUrl', 'formAction'):
                if action.get(key):
                    action[key] = sanitize_url(action[key])
        for issue in record['issues']:
            record['checks'].append(check(side + '.observation.' + str(len(record['checks'])), issue['level'],
                                          issue['category'], expected='Healthy required resources / review optional observations',
                                          actual=issue['message'], evidence=[issue['url']] if issue['url'] else [],
                                          required=issue['level'] != 'SKIP'))
        try:
            page.close()
        finally:
            state['record'] = None
    return record


def _skipped_page(url, side, reason, depth=0):
    return dict(url=url, finalUrl=url, title='', heading='', structure='', statusCode=None,
                screenshot=None, screenshotFile=None, issues=[], regions=[], actions=[], navigated=False,
                depth=depth, checks=[check(side + '.visit', 'SKIP', reason, expected='Planned page visit')], coverage={})


def _crawl(browser, side, options, artifact_root, run_id, progress, budget, auth_gate):
    options = dict(options)
    options['_side_action_start'] = budget.actions
    # Reserve at least half the action allowance for B before A starts.
    options['_side_action_limit'] = budget.maximum // 2 if side == 'a' else budget.maximum - budget.actions
    seed = options['baseline_url' if side == 'a' else 'candidate_url']
    context = browser.new_context(viewport=options.get('viewport', {'width': 1365, 'height': 768}),
                                  device_scale_factor=1, locale='ko-KR', timezone_id='Asia/Seoul',
                                  color_scheme='light', reduced_motion='reduce',
                                  service_workers='block', accept_downloads=False)
    state = dict(record=None, blocked=[], blocked_urls=set(), manual_auth=False, scenario_done=False)
    _network_guard(context, options, (options['baseline_url'], options['candidate_url']), side, state, budget)
    pages, deferred = OrderedDict(), []
    queue, seen = deque([(seed, 0)]), {normalize_url(seed)}
    try:
        if options.get('manual_login'):
            if auth_gate is None:
                return OrderedDict([(seed, _skipped_page(seed, side, 'MANUAL_AUTH_REQUIRED'))]), [], state
            state['manual_auth'] = True
            try:
                auth_gate(side, context, seed)
            finally:
                state['manual_auth'] = False
            if budget.reason():
                return OrderedDict([(seed, _skipped_page(seed, side, budget.reason()))]), [], state
        while queue and len(pages) < int(options.get('max_pages', 5)):
            url, depth = queue.popleft()
            if budget.reason():
                deferred.append(_skipped_page(url, side, budget.reason(), depth))
                break
            progress(f'{side.upper()}: {len(pages) + 1}/{options.get("max_pages", 5)} {sanitize_url(url)}')
            record = _visit(context, url, side, depth, options, artifact_root, run_id, budget, state)
            pages[normalize_url(url)] = record
            for action in record['actions']:
                href = action.pop('_navigation_url', None)
                if not href or not action['allowed']:
                    continue
                normalized = normalize_url(href)
                action['_target_identity'] = normalized
                if normalized in seen:
                    action.update(state='SKIP', reason='ALREADY_DISCOVERED')
                    continue
                seen.add(normalized)
                if depth >= int(options.get('max_depth', 1)):
                    action.update(state='SKIP', reason='DEPTH_LIMIT_REACHED')
                    deferred.append(_skipped_page(normalized, side, 'DEPTH_LIMIT_REACHED', depth + 1))
                else:
                    action['state'] = 'QUEUED'
                    queue.append((normalized, depth + 1))
        reason = budget.reason() or 'PAGE_LIMIT_REACHED'
        deferred.extend(_skipped_page(url, side, reason, depth) for url, depth in queue)
        for record in pages.values():
            for action in record['actions']:
                target = action.pop('_target_identity', None)
                if target in pages and pages[target].get('navigated'):
                    action.update(state='URL_VISITED', reason='NAVIGATION_VISITED_NOT_CLICK_ASSERTED')
                elif action['state'] == 'QUEUED':
                    action.update(state='SKIP', reason=reason)
    finally:
        context.close()
    return pages, deferred, state


def _result_rows(pairs, options, artifact_root, run_id):
    rows = []
    for pair in pairs:
        a, b, match = pair['baseline'], pair['candidate'], pair['match']
        checks = [*a.get('checks', [])] if a else []
        if b:
            checks.extend(b.get('checks', []))
        if not a or not b:
            checks.append(check('match', 'REVIEW', 'NOT_DISCOVERED',
                                expected='Both environments discovered; absence is not 404',
                                actual='ONLY_CANDIDATE' if not a else 'ONLY_BASELINE'))
        elif not match.get('approved'):
            checks.append(check('match', 'REVIEW', 'REVIEW_MATCH', expected='Approved functional mapping', actual=match['method']))
        else:
            checks.append(check('match', 'PASS', 'MATCH_CONFIRMED', expected='Approved mapping or route plus heading', actual=match['method']))
        base = dict(id=_id(pair['key'] + (a or b)['url']), key=pair['key'], region_id='page',
                    baseline=_safe_record(a), candidate=_safe_record(b), match=match,
                    review=dict(status='UNREVIEWED', revision=0, events=[]))
        if options.get('mode') == 'discovery':
            base.update(visual=None, checks=checks, status=aggregate_status(checks),
                        flags=sorted({c['reason_code'] for c in checks if c['status'] != 'PASS'}))
            rows.append(base)
            continue
        regions = options.get('regions', [])
        # With configured regions the viewport stays contextual evidence, not a DB-sensitive verdict.
        if regions:
            base.update(visual=None, checks=checks, status=aggregate_status(checks),
                        flags=sorted({c['reason_code'] for c in checks if c['status'] != 'PASS'}))
            rows.append(base)
            for region in regions:
                rid = region['id']
                left = next((r for r in (a or {}).get('regions', []) if r['id'] == rid), None)
                right = next((r for r in (b or {}).get('regions', []) if r['id'] == rid), None)
                region_check_ids = {f'{side}.region.{rid}{suffix}' for side in ('a', 'b') for suffix in ('', '.capture')}
                region_checks = [c for c in checks if c.get('check_id') in region_check_ids]
                if not a or not b:
                    region_checks.append(check(f'region.{rid}.match', 'SKIP', 'MATCH_SIDE_UNAVAILABLE', required=region.get('required', True)))
                    visual = None
                elif any(r and r.get('state') in ('MISSING', 'HIDDEN') for r in (left, right)):
                    region_checks.append(check(f'region.{rid}.visual', 'SKIP', 'REGION_PREREQUISITE_FAILED', required=region.get('required', True)))
                    visual = None
                else:
                    visual = image_diff(left, right, artifact_root, run_id, pair['key'] + '#' + rid)
                    region_checks.append(visual_check(visual, options.get('visual_threshold', 2), f'region.{rid}.visual'))
                if a and b and not match.get('approved'):
                    region_checks.append(check(f'region.{rid}.match', 'REVIEW', 'REVIEW_MATCH'))
                row = dict(base, id=_id(base['id'] + rid), region_id=rid, checks=region_checks,
                           visual=visual, status=aggregate_status(region_checks),
                           flags=sorted({c['reason_code'] for c in region_checks if c['status'] != 'PASS'}))
                # Present region-specific captures rather than labelling whole-page images as a region.
                for field, item in (('baseline', left), ('candidate', right)):
                    if row[field] is not None:
                        row[field] = dict(row[field], screenshot=(item or {}).get('screenshot'))
                rows.append(row)
        else:
            if a and b:
                visual = image_diff(a, b, artifact_root, run_id, pair['key'])
                checks.append(visual_check(visual, options.get('visual_threshold', 2)))
            else:
                visual = None
                checks.append(check('visual', 'SKIP', 'MATCH_SIDE_UNAVAILABLE'))
            base.update(visual=visual, checks=checks, status=aggregate_status(checks),
                        flags=sorted({c['reason_code'] for c in checks if c['status'] != 'PASS'}))
            rows.append(base)
    return rows


def run_scan(options, run_id, artifact_root, progress, cancelled, auth_gate=None):
    """Run one bounded scan; contexts and credentials never enter report/store state."""
    options = dict(options)
    options['baseline_url'] = normalize_url(options['baseline_url'])
    options['candidate_url'] = normalize_url(options['candidate_url'])
    if not options.get('allowed_hosts'):
        options['allowed_hosts'] = list({urlsplit(options[k]).hostname for k in ('baseline_url', 'candidate_url')})
    for key in ('baseline_url', 'candidate_url'):
        if not host_allowed(options[key], options['allowed_hosts']):
            raise ValueError('Start URL host is not approved.')
    # Prevent a caller from escaping the artifact root through the public runner API.
    if not run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in run_id):
        raise ValueError('Invalid run ID.')
    budget = Budget(options, cancelled)
    started = _now()
    progress('Preparing isolated Chromium contexts')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not bool(options.get('manual_login')), timeout=budget.timeout(15000))
        browser_version = browser.version
        try:
            a, a_skip, a_state = _crawl(browser, 'a', options, artifact_root, run_id, progress, budget, auth_gate)
            if budget.reason():
                b = OrderedDict([(options['candidate_url'], _skipped_page(options['candidate_url'], 'b', budget.reason()))])
                b_skip, b_state = [], {'blocked': []}
            else:
                b, b_skip, b_state = _crawl(browser, 'b', options, artifact_root, run_id, progress, budget, auth_gate)
        finally:
            browser.close()
    progress('Comparing route mappings and region evidence')
    rows = _result_rows(match_pages(a, b, options.get('route_aliases', [])), options, artifact_root, run_id)
    for side, deferred in (('a', a_skip), ('b', b_skip)):
        for page in deferred:
            rows.append(dict(id=_id(side + page['url'] + '.skip'), key=page_key(page['url']), region_id='page',
                             status='SKIP', flags=[page['checks'][0]['reason_code']], checks=page['checks'],
                             baseline=_safe_record(page) if side == 'a' else None,
                             candidate=_safe_record(page) if side == 'b' else None, visual=None,
                             match={'method': 'NOT_EXECUTED', 'confidence': 'LOW', 'approved': False},
                             review={'status': 'UNREVIEWED', 'revision': 0, 'events': []}))
    observed = list(a.values()) + list(b.values())
    actions = [action for page in observed for action in page.get('actions', [])]
    for action in actions:
        action.pop('_navigation_url', None)
    # A check shown in both page and region views is counted once in totals.
    unique_checks = {}
    for row in rows:
        for item in row['checks']:
            unique_checks[(row['key'], item.get('environment'), item.get('check_id'), item.get('scenario_id'), item.get('step_id'))] = item
    totals = dict(pages=len(rows), baselineVisited=sum(p.get('navigated', False) for p in a.values()),
                  candidateVisited=sum(p.get('navigated', False) for p in b.values()),
                  assertions=sum(c['status'] in ('PASS', 'FAIL') for c in unique_checks.values()),
                  discoveredActions=len(actions), executedActions=budget.completed, attemptedActions=budget.actions,
                  blockedActions=sum(not action['allowed'] for action in actions))
    totals.update({status.lower(): sum(row['status'] == status for row in rows)
                   for status in ('PASS', 'FAIL', 'REVIEW', 'SKIP', 'ERROR')})
    blocked_requests = a_state['blocked'] + b_state['blocked']
    return dict(baselineUrl=sanitize_url(options['baseline_url']), candidateUrl=sanitize_url(options['candidate_url']),
                maxPages=options.get('max_pages', 5), maxDepth=options.get('max_depth', 1),
                visualThreshold=options.get('visual_threshold', 2), totals=totals, results=rows,
                manifest=dict(schemaVersion='1.0', runId=run_id, profileId=options.get('profile_id', 'custom'),
                              operatorId=options.get('operator_id', ''), startedAt=started, finishedAt=_now(),
                              python=platform.python_version(), playwright=version('playwright'), pillow=version('Pillow'),
                              browser=browser_version, viewport=options.get('viewport', {'width': 1365, 'height': 768}),
                              mode=options.get('mode', 'combined'), status='CANCELLED' if cancelled() else 'PARTIAL' if budget.reason() else 'COMPLETED',
                              ruleVersion='mvp-1', dataPolicy='INDEPENDENT_LIVE_WITH_CONFIGURED_MASKS'),
                coverage=dict(discoveredPages=len(a) + len(b) + len(a_skip) + len(b_skip),
                              deferredPages=len(a_skip) + len(b_skip), discoveredActions=len(actions),
                              executedActions=budget.completed, attemptedActions=budget.actions,
                              navigationTargetsVisited=sum(a.get('state') == 'URL_VISITED' for a in actions),
                              blockedActions=totals['blockedActions'],
                              blockedRequests=blocked_requests, incomplete=bool(blocked_requests or a_skip or b_skip or budget.reason()),
                              limitations=['No shadow DOM/canvas coverage', 'Iframes are inventory only',
                                           'Click dispatch without an assertion is REVIEW', 'Viewport capture only',
                                           'No direct database equality comparison']))
