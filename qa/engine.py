"""Bounded two-environment runner, evolved from the original Playwright crawler.

Discovery and approval are separate. No browser/network work happens at import time.
"""
from __future__ import annotations

import fnmatch
import json
import platform
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import sync_playwright

from .comparison import image_diff, visual_check
from .matching import instance_template, match_pages, normalize_url, page_key
from .policy import (readonly_navigation_reason, aggregate_status, check, classify_candidate, dangerous_action,
                     host_allowed, http_observation, route_allowed, sanitize_message, sanitize_url,
                     STATUSES, unexecuted_status, resource_allowed)

DISCOVER_JS = r'''(argument) => {
  const rules = Array.isArray(argument) ? argument : (argument?.rules || []);
  const configured = Array.isArray(argument) ? [] : (argument?.privateSelectors || []);
  const selectors = ['[data-qa-private]', 'input[type=password]', ...configured];
  const privateRoots = new Set();
  for (let index=0; index<selectors.length; index++) {
    try {
      for (const el of document.querySelectorAll(selectors[index])) privateRoots.add(el);
    } catch (_) {
      // Invalid privacy configuration cannot silently enable unmasked collection.
      return {title:'',heading:'',structure:'',candidates:[],broken:[],signature:{},iframes:0,demo:false,
        privacy:{error:'INVALID_PRIVATE_SELECTOR',selectorIndex:index,excludedCandidates:0,excludedElements:0}};
    }
  }
  const privateElements = new Set();
  const privateTerms = new Set();
  for (const root of privateRoots) {
    for (const el of [root,...root.querySelectorAll('*')]) {
      privateElements.add(el);
      for (const value of [el.getAttribute('aria-label'),el.getAttribute('title'),el.getAttribute('placeholder')]) {
        if (typeof value === 'string' && value.trim()) privateTerms.add(value.trim());
      }
    }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      if (walker.currentNode.parentElement.closest('input,textarea,select,option')) continue;
      const value = walker.currentNode.textContent.trim();
      if (value) privateTerms.add(value);
    }
  }
  // Terms remain inside this evaluation and protect duplicated title/aria text.
  const terms = [...privateTerms].sort((a,b)=>b.length-a.length);
  const scrub = value => {
    let text = String(value || '');
    for (const term of terms) text = text.split(term).join('[PRIVATE]');
    return text;
  };
  const privateElement = el => privateElements.has(el);
  const publicText = el => {
    if (!el || privateElement(el)) return '';
    const values = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const parent = walker.currentNode.parentElement;
      if (privateElement(parent) || parent.closest('script,style,template,noscript,input,textarea,select,option')) continue;
      let hidden = false;
      if (el.tagName !== 'TITLE') {
        for (let node=parent; node; node=node.parentElement) {
          const style = getComputedStyle(node);
          if (node.hidden || node.getAttribute('aria-hidden') === 'true' || style.display === 'none'
              || style.visibility === 'hidden' || style.visibility === 'collapse') {hidden=true;break;}
        }
      }
      if (!hidden) values.push(walker.currentNode.textContent);
    }
    return scrub(values.join(' '));
  };
  const label = (el,limit=100) => {
    if (privateElement(el)) return '';
    return scrub(el.getAttribute('aria-label') || publicText(el) || el.getAttribute('title') || '')
      .replace(/\s+/g,' ').trim().slice(0,limit);
  };
  const publicElements = query => [...document.querySelectorAll(query)].filter(el=>!privateElement(el));
  const selector = el => {
    if (el.id && scrub(el.id) === el.id) return '#' + CSS.escape(el.id);
    const path = [];
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const siblings = n.parentElement ? [...n.parentElement.children].filter(x => x.tagName === n.tagName) : [n];
      path.unshift(n.tagName.toLowerCase() + (siblings.length > 1 ? ':nth-of-type('+(siblings.indexOf(n)+1)+')' : ''));
      if (path.length >= 7) break;
    }
    return path.join(' > ');
  };
  const allCandidates = [...document.querySelectorAll('a[href],button,input[type=submit],input[type=image],[role=button],[role=link],[role=tab],[onclick],[tabindex]')];
  let excludedCandidates = 0;
  const candidates = allCandidates.filter(el => {
    if (privateElement(el) || [el.href,el.formAction].some(value => value && scrub(value) !== value)) {
      excludedCandidates++;
      return false;
    }
    return true;
  }).map(el => {
    const r = el.getBoundingClientRect();
    let selected = selector(el);
    for (const rule of rules) { try { if (el.matches(rule.selector)) { selected = rule.selector; break; } } catch (_) {} }
    return {selector:selected,tag:el.tagName.toLowerCase(),type:el.getAttribute('type')||'',
      role:el.getAttribute('role')||'',label:label(el,120),
      href:el.href||'',formAction:el.formAction||'',download:el.hasAttribute('download'),
      visible:r.width>0&&r.height>0&&getComputedStyle(el).visibility!=='hidden',disabled:!!el.disabled,
      pageUrl:location.href};
  });
  const broken = [...document.images].filter(i => {
    if (privateElement(i) || scrub(i.currentSrc||i.src) !== (i.currentSrc||i.src)) return false;
    const r=i.getBoundingClientRect();return r.width>0&&r.height>0&&r.top<innerHeight&&r.bottom>0&&i.complete&&i.naturalWidth===0&&!!(i.currentSrc||i.src);
  }).map(i=>i.currentSrc||i.src);
  const dynamic = el => privateElement(el) || !!el.closest('[data-qa-dynamic],tr') || (!!el.closest('li') && !el.closest('nav,header,[role=navigation]'));
  const unique = values => [...new Set(values.filter(Boolean))].slice(0,40);
  const signature = {
    landmarks:Object.fromEntries(['main','nav','form','header','footer','h1','h2'].map(tag => [tag,publicElements(tag).length])),
    headings:[...document.querySelectorAll('h1,h2')].filter(el=>!dynamic(el)).slice(0,12).map(el=>({tag:el.tagName.toLowerCase(),text:label(el)})),
    formFields:[...document.querySelectorAll('form input,form select,form textarea,[role=search] input')]
      .filter(el=>!['password','hidden'].includes((el.type||'').toLowerCase())&&!privateElement(el))
      .slice(0,30).map(el=>({type:el.type||el.tagName.toLowerCase(),name:scrub(el.getAttribute('name')||''),label:scrub(el.getAttribute('aria-label')||el.getAttribute('placeholder')||'')})),
    actionLabels:unique([...document.querySelectorAll('button,[role=button],[role=tab],form a')].filter(el=>!dynamic(el)).map(el=>label(el))),
    navLabels:unique(publicElements('nav a,header a,[role=navigation] a').map(el=>label(el)))
  };
  return {title:label(document.querySelector('title')||document.createElement('title'),160),
    heading:publicText(publicElements('h1')[0]).replace(/\s+/g,' ').trim().slice(0,160),
    structure:publicElements('main,nav,form,[role=main],h1,h2').map(el=>el.tagName.toLowerCase()).join('|'),
    candidates,broken,signature,iframes:publicElements('iframe').length,
    privacy:{error:null,excludedCandidates,excludedElements:privateElements.size},
    demo:document.querySelector('[data-qa-demo="web-qa-comparator-v1"]')!==null};
}'''


def _discover(page, options, record, side):
    info = page.evaluate(DISCOVER_JS, {'rules': options.get('safe_actions', []),
                                     'privateSelectors': options.get('private_mask_selectors', [])})
    privacy = info.get('privacy') or {}
    record['coverage']['privateExcludedCandidates'] = max(record['coverage'].get('privateExcludedCandidates', 0),
                                                         privacy.get('excludedCandidates', 0))
    record['coverage']['privateExcludedElements'] = max(record['coverage'].get('privateExcludedElements', 0),
                                                       privacy.get('excludedElements', 0))
    if privacy.get('error'):
        record['captureReady'] = False
        record['readiness']['privacy'] = False
        record['checks'].append(check(side + '.privacy', 'ERROR', 'INVALID_PRIVATE_SELECTOR',
                                      expected='Valid private selectors before any DOM evidence collection',
                                      actual={'selectorIndex': privacy.get('selectorIndex')}))
        return None
    return info


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id(value):
    return sha256(str(value).encode('utf-8')).hexdigest()[:20]


def _origin(url):
    p = urlsplit(url)
    return p.scheme, p.netloc.lower()


def _seed_urls(options):
    return tuple(options[key] for key in ('baseline_url', 'candidate_url') if options.get(key))


def _public(page):
    if page is None:
        return None
    return {key: value for key, value in page.items()
            if key in ('url', 'finalUrl', 'title', 'heading', 'statusCode', 'issues', 'screenshot', 'depth',
                       'actions', 'checks', 'observedAt', 'regions', 'coverage', 'captureReady', 'readiness',
                       'navigationTrail', 'pageSignature', 'entryAction', 'dismissed', 'mirroredFromBaseline')}


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


_INFORMATIONAL_CATEGORIES = frozenset({
    'JS_ERROR', 'JS_ERROR_AFTER_POLICY_BLOCK', 'CONSOLE_ERROR', 'CONSOLE_ERROR_AFTER_POLICY_BLOCK',
    'BROKEN_IMAGE', 'HTTP_4XX', 'HTTP_5XX', 'NETWORK_ERROR', 'REQUEST_ABORTED', 'OBSERVATION_ERROR'})


def _append_issue(record, category, level, message, url='', **details):
    timestamp = _now()
    issue = dict(category=category, level=level, message=sanitize_message(message), url=sanitize_url(url),
                 timestamp=timestamp, lastSeenAt=timestamp, count=1, requestId=None,
                 source='BROWSER', method=None, resourceType=None, statusCode=None,
                 runId=record.get('runId'), environment=record.get('environment'), pageId=record.get('pageId'),
                 scenarioId=record.get('_active_scenario', 'engine'), stepId=record.get('_active_step', 'observe'))
    issue.update(details)
    identity = tuple(issue.get(key) for key in ('category', 'level', 'message', 'url', 'requestId', 'scenarioId', 'stepId'))
    for existing in record['issues']:
        if tuple(existing.get(key) for key in ('category', 'level', 'message', 'url', 'requestId', 'scenarioId', 'stepId')) == identity:
            existing['count'] += 1
            existing['lastSeenAt'] = timestamp
            return existing
    issue['observationId'] = _id(str(identity) + str(record.get('pageId')))
    record['issues'].append(issue)
    return issue


def _request_metadata(request, state, record):
    identities = state.setdefault('request_ids', {})
    if request not in identities:
        identities[request] = _id(str(record.get('runId', '')) + str(record.get('environment', '')) + str(len(identities)))
    return dict(requestId=identities[request], method=request.method, resourceType=request.resource_type,
                source='FIRST_PARTY' if _origin(request.url) == _origin(record['url']) else 'THIRD_PARTY')


def _attach_observers(page, context_state):
    """Attach once per tab; every handler resolves the *current* page record from state.

    One Chromium tab per environment stays open for the whole crawl, so login
    cookies, sessionStorage and a dismissed cover gate survive between pages.
    """
    def current():
        return context_state.get('record')

    def policy_context(record):
        related = [dict(url=item.get('url'), reason=item.get('message'),
                        resourceType=item.get('resourceType'), method=item.get('method'))
                   for item in record['issues'] if item['category'] == 'POLICY_BLOCKED']
        return {'policyInterference': bool(related), 'causeConfirmed': False,
                'relatedBlockedRequests': related[-10:]}

    def response_observed(response):
        record = current()
        if record is None:
            return
        try:
            observation = http_observation(response.status, response.request.resource_type,
                                           _origin(response.url) == _origin(record['url']))
            if observation:
                _append_issue(record, observation['category'], observation['level'],
                              f'{response.status} {response.request.resource_type}', response.url,
                              statusCode=response.status, **_request_metadata(response.request, context_state, record))
        except Exception as exc:
            _append_issue(record, 'OBSERVATION_ERROR', 'ERROR', type(exc).__name__)

    def request_failed(request):
        record = current()
        if record is None:
            return
        try:
            if request.url in context_state['blocked_urls']:
                return
            failure = request.failure or 'Network failure'
            aborted = 'ERR_ABORTED' in failure.upper()
            owner = context_state.get('request_owner', {}).pop(request, None)
            if aborted and owner is not None and owner != record['pageId']:
                # In-flight request of the previous page cancelled by this navigation: not this page's issue.
                return
            runner_cancelled = aborted and record.get('_closing', False)
            metadata = _request_metadata(request, context_state, record)
            if runner_cancelled:
                metadata['source'] = 'RUNNER'
            _append_issue(record, 'REQUEST_CANCELLED_BY_RUNNER' if runner_cancelled else 'REQUEST_ABORTED' if aborted else 'NETWORK_ERROR',
                          'SKIP' if runner_cancelled else 'REVIEW', failure,
                          request.url, **metadata)
        except Exception as exc:
            _append_issue(record, 'OBSERVATION_ERROR', 'ERROR', type(exc).__name__)

    owners = context_state.setdefault('request_owner', {})

    def request_started(request):
        record = current()
        if record is not None:
            owners[request] = record['pageId']
            if len(owners) > 2000:
                for key in list(owners)[:1000]:
                    owners.pop(key, None)

    page.on('request', request_started)
    page.on('response', response_observed)
    page.on('requestfailed', request_failed)

    def page_error(exc):
        record = current()
        if record is None:
            return
        context = policy_context(record)
        _append_issue(record, 'JS_ERROR_AFTER_POLICY_BLOCK' if context['policyInterference'] else 'JS_ERROR',
                      'REVIEW' if context['policyInterference'] else 'FAIL', str(exc), page.url, **context)

    def console_error(message):
        record = current()
        if record is None or message.type != 'error':
            return
        context = policy_context(record)
        after_block = context['policyInterference'] and ('ERR_BLOCKED_BY_CLIENT' in message.text or 'ERR_BLOCKED_BY_RESPONSE' in message.text)
        _append_issue(record, 'CONSOLE_ERROR_AFTER_POLICY_BLOCK' if after_block else 'CONSOLE_ERROR',
                      'REVIEW', message.text, page.url, **context)

    page.on('pageerror', page_error)
    page.on('console', console_error)
    page.on('dialog', lambda dialog: dialog.dismiss())
    page.on('download', lambda download: (current() is not None) and _append_issue(
        current(), 'DOWNLOAD_BLOCKED', 'SKIP', 'Download was not approved.', page.url))


def _network_guard(context, options, seeds, side, state, budget):
    seed = seeds[0 if side == 'a' else 1]
    demo_prefix = '/demo/' + side + '/' if urlsplit(seed).path.startswith('/demo/' + side + '/') else None
    # Fragments never travel in HTTP requests. Approve the seed's bootstrap
    # document separately while candidate/action policy still checks hash routes.
    seed_documents = {normalize_url(urlunsplit(urlsplit(seed)._replace(fragment='')))}

    def guard(route):
        request = route.request
        reason = budget.reason()
        approved_resource = resource_allowed(request.url, request.resource_type, request.method,
                                             request.is_navigation_request(), options.get('resource_hosts', []))
        if not reason and not (host_allowed(request.url, options['allowed_hosts']) or approved_resource):
            reason = 'HOST_NOT_APPROVED'
        passive = request.resource_type in ('image', 'font', 'stylesheet', 'script', 'media') and request.method in ('GET', 'HEAD')
        data_call = request.resource_type in ('xhr', 'fetch') and host_allowed(request.url, options['allowed_hosts'])
        level = options.get('safety_level', 'strict')
        if not reason and not state['manual_auth'] and level == 'test_account':
            # Test-account level: writes on approved hosts are allowed; only account-breaking /
            # paid URLs and unapproved routes are refused. Policy is logged, not silent.
            if not passive and dangerous_action({'url': request.url}, level):
                reason = dangerous_action({'url': request.url}, level)
            elif request.is_navigation_request() and not (
                    normalize_url(request.url) in seed_documents or route_allowed(request.url, options, seeds, origin_url=seed)):
                reason = 'ROUTE_NOT_APPROVED'
            elif request.is_navigation_request() and demo_prefix and not urlsplit(request.url).path.startswith(demo_prefix):
                reason = 'ENVIRONMENT_BOUNDARY'
        elif not reason and not state['manual_auth']:
            if passive:
                # A GET for ico_save.svg cannot mutate anything: resource URLs skip the action-word policy.
                pass
            elif data_call and options.get('xhr_policy', 'allow_allowed_hosts') == 'allow_allowed_hosts':
                # Page-load data calls (often POST for read APIs) are the page's own behaviour on approved hosts.
                # Action words in the URL (delete/save/submit...) are still refused.
                if dangerous_action({'url': request.url}):
                    reason = dangerous_action({'url': request.url})
            elif request.method not in ('GET', 'HEAD', 'OPTIONS'):
                reason = 'WRITE_REQUEST_NOT_APPROVED'
            elif dangerous_action({'url': request.url}):
                reason = dangerous_action({'url': request.url})
            elif request.is_navigation_request() and not (
                    normalize_url(request.url) in seed_documents or route_allowed(request.url, options, seeds, origin_url=seed)):
                reason = 'ROUTE_NOT_APPROVED'
            elif request.is_navigation_request() and demo_prefix and not urlsplit(request.url).path.startswith(demo_prefix):
                reason = 'ENVIRONMENT_BOUNDARY'
        if reason:
            state['blocked_urls'].add(request.url)
            record = state.get('record')
            item = dict(url=sanitize_url(request.url), method=request.method, reason=reason,
                        resourceType=request.resource_type, timestamp=_now(), source='POLICY', environment=side)
            if record is not None:
                item['requestId'] = _request_metadata(request, state, record)['requestId']
            state['blocked'].append(item)
            if record is not None:
                # A blocked tracker on a foreign host does not change what the page looks like; a blocked
                # first-party or approved-host resource might. Only the latter makes a capture non-comparable.
                first_party = _origin(request.url) == _origin(record['url'])
                approved_host = host_allowed(request.url, options['allowed_hosts']) or host_allowed(request.url, options.get('resource_hosts', []))
                rendering_relevant = (first_party or approved_host) and request.resource_type in (
                    'document', 'stylesheet', 'script', 'image', 'font', 'media', 'xhr', 'fetch')
                _append_issue(record, 'EXECUTION_BLOCKED' if unexecuted_status(reason) == 'BLOCKED' else 'POLICY_BLOCKED',
                              unexecuted_status(reason), reason, request.url,
                              resourceType=request.resource_type, method=request.method,
                              requestId=item.get('requestId'), source='POLICY', renderingRelevant=rendering_relevant)
            route.abort('blockedbyclient')
        else:
            route.continue_()

    context.route('**/*', guard)


_SETTLE_JS = '''() => {
  const spinner = [...document.querySelectorAll('[class*="loading" i],[class*="spinner" i],[class*="skeleton" i],[id*="loading" i],[aria-busy="true"]')]
    .some(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none'; });
  const pendingImages = [...document.images].filter(img => { const r = img.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.top < innerHeight && r.bottom > 0 && !img.complete; }).length;
  return { ready: document.readyState, height: document.documentElement.scrollHeight, nodes: document.getElementsByTagName('*').length,
           scrollY: window.scrollY, spinner, pendingImages };
}'''


def _settle_before_capture(page, record, budget, options):
    """Normalize the viewport and wait for the page to stop changing before the screenshot.

    - Scroll to the top with smooth scrolling disabled, so A and B are captured at the same offset.
    - Wait until no visible loading/spinner/skeleton element, no pending in-viewport image, and
      document height / node count stay identical across two consecutive samples.
    Bounded by ``capture_settle_ms`` (default 4000 ms) and the run budget; the outcome is recorded.
    """
    limit = min(int(options.get('capture_settle_ms', 4000)), budget.timeout(4000))
    deadline = time.monotonic() + limit / 1000
    try:
        page.evaluate('() => { document.documentElement.style.scrollBehavior = "auto"; window.scrollTo(0, 0); }')
    except Exception:
        pass
    previous, stable, last = None, 0, {}
    while time.monotonic() < deadline:
        try:
            last = page.evaluate(_SETTLE_JS)
        except Exception:
            break
        current = (last.get('height'), last.get('nodes'))
        quiet = last.get('ready') == 'complete' and not last.get('spinner') and not last.get('pendingImages')
        stable = stable + 1 if quiet and current == previous else 0
        if stable >= 2:
            break
        previous = current
        page.wait_for_timeout(min(150, budget.timeout(150)))
    try:
        if last.get('scrollY'):
            page.evaluate('() => window.scrollTo(0, 0)')
            page.wait_for_timeout(min(100, budget.timeout(100)))
    except Exception:
        pass
    settled = stable >= 2
    record.setdefault('readiness', {})['settled'] = settled
    record['readiness']['settleState'] = {k: last.get(k) for k in ('ready', 'spinner', 'pendingImages', 'scrollY')}
    if not settled:
        record['checks'].append(check(side_of(record) + '.settle', 'REVIEW', 'CAPTURE_NOT_SETTLED',
                                      expected='No spinner, images loaded, stable layout within the settle budget',
                                      actual=record['readiness']['settleState'], required=False))
        record['checks'][-1]['informational'] = True


def side_of(record):
    return record.get('environment') or 'a'


def _capture(page, record, options, artifact_root, run_id, side, budget):
    folder = Path(artifact_root) / run_id / side
    folder.mkdir(parents=True, exist_ok=True)
    name = _id(record['url'])
    _settle_before_capture(page, record, budget, options)
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
        reason = dangerous_action(action, options.get('safety_level', 'strict'))
    if not reason and action.get('url'):
        if not host_allowed(action['url'], options['allowed_hosts']):
            reason = 'HOST_NOT_APPROVED'
        elif not route_allowed(action['url'], options, _seed_urls(options),
                               origin_url=options.get('_environment_seed') or record.get('url')):
            reason = 'ROUTE_NOT_APPROVED'
    if not reason and budget.actions >= budget.maximum:
        reason = 'ACTION_LIMIT_REACHED'
    if not reason and budget.actions - options.get('_side_action_start', 0) >= options.get('_side_action_limit', budget.maximum):
        reason = 'ENVIRONMENT_ACTION_LIMIT_REACHED'
    if reason:
        status = unexecuted_status(reason)
        record['checks'].append(check('action.guard.' + str(len(record['checks'])), status, reason,
                                      expected='Approved action within budget', actual=action.get('kind'), required=status == 'BLOCKED'))
        return False
    record['_active_scenario'] = action.get('scenario_id', 'engine')
    record['_active_step'] = action.get('step_id', action.get('kind', 'action'))
    if not budget.action(page):
        return False
    return True


_SMOKE_FILL_JS = '''([selector, marker]) => {
  const control = document.querySelector(selector);
  const form = control && control.closest('form');
  if (!form) return 0;
  let filled = 0;
  for (const el of form.querySelectorAll('input, textarea, select')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0 || el.disabled || el.readOnly) continue;
    const type = (el.type || '').toLowerCase();
    if (el.tagName === 'SELECT') { if (el.selectedIndex <= 0 && el.options.length > 1) { el.selectedIndex = 1; filled++; } continue; }
    if (['hidden', 'submit', 'button', 'image', 'file', 'password', 'checkbox', 'radio'].includes(type)) continue;
    if (el.value) continue;
    el.value = type === 'email' ? 'qa-auto@test.local' : type === 'number' ? '1' : type === 'tel' ? '01000000000' : marker;
    el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true }));
    filled++;
  }
  return filled;
}'''


def _fill_form_for_smoke(page, selector, options):
    """Fill empty visible fields of the control's form with a QA marker (test-account level only)."""
    try:
        return int(page.evaluate(_SMOKE_FILL_JS, [selector, options.get('smoke_fill_text', 'QA자동테스트')]) or 0)
    except Exception:
        return 0


def _smoke_actions(page, record, options, budget, side, register):
    """Click discovered in-page controls (no href, not dangerous) with one generic expectation.

    Expectation: the page stays on the approved origin, no new JavaScript error is
    raised and the document still responds. That is a smoke contract, not a
    functional PASS; it finds controls that throw or navigate away.
    """
    limit = int(options.get('smoke_action_limit', 20))
    seed_origin = _origin(record['url'])
    done = 0
    for action in list(record['actions']):
        if done >= limit or budget.reason():
            break
        if budget.actions >= budget.maximum or budget.actions - options.get('_side_action_start', 0) >= options.get('_side_action_limit', budget.maximum):
            # Smoke clicks are opportunistic: an exhausted action budget ends them silently.
            record['coverage']['smokeBudgetExhausted'] = True
            break
        if action.get('href') or action['reason'] not in ('UNKNOWN_ACTION',):
            continue
        level = options.get('safety_level', 'strict')
        if not action.get('visible', True) or action.get('disabled') or dangerous_action(action, level):
            continue
        if not str(action.get('label') or '').strip():
            # Icon-only / overlay controls with no accessible name are not worth a blind click.
            continue
        tag, kind = action.get('tag', ''), action.get('type', '').lower()
        submits = tag == 'input' or kind in ('submit', 'image') or (tag == 'button' and kind != 'button')
        # Strict: a <button> without an explicit type submits its form, so only explicit type=button
        # or non-form controls are smoke-clicked. Test-account level also submits forms, after
        # filling empty visible text fields with a QA marker so validation does not stop the submit.
        if submits and level != 'test_account':
            continue
        if not _action_guard(page, record, options, budget, action):
            action.update(state='BLOCKED', reason=budget.reason() or 'ACTION_LIMIT_REACHED')
            continue
        before_url, before_errors = page.url, sum(1 for i in record['issues'] if i['category'] in ('JS_ERROR', 'JS_ERROR_AFTER_POLICY_BLOCK'))
        check_id = side + '.smoke.' + action['id']
        try:
            filled = 0
            if submits:
                filled = _fill_form_for_smoke(page, action['selector'], options)
                if filled:
                    action['smokeFilledFields'] = filled
            target = page.locator(action['selector']).first
            try:
                target.click(timeout=budget.timeout(1500))
            except Exception as click_error:
                if 'Timeout' in type(click_error).__name__:
                    # Covered by another element or not actionable right now: evidence, not a verdict.
                    action.update(state='SKIP', reason='SMOKE_NOT_CLICKABLE')
                    record['checks'].append(check(check_id, 'SKIP', 'ACTION_SMOKE_NOT_CLICKABLE',
                                                  expected='Control actionable within 1.5s', actual={'label': action.get('label')}, required=False))
                    continue
                raise
            page.wait_for_timeout(min(400, budget.timeout(400)))
            budget.completed += 1
            done += 1
            after_errors = sum(1 for i in record['issues'] if i['category'] in ('JS_ERROR', 'JS_ERROR_AFTER_POLICY_BLOCK'))
            left_origin = _origin(page.url) != seed_origin
            responsive = page.evaluate('() => document.readyState !== "loading"')
            if left_origin or not responsive:
                action.update(state='EXECUTED', allowed=True, reason='SMOKE_ACTION')
                record['checks'].append(check(check_id, 'FAIL', 'ACTION_SMOKE_LEFT_SCOPE' if left_origin else 'ACTION_SMOKE_UNRESPONSIVE',
                                              expected='Control keeps the page on the approved origin and responsive',
                                              actual={'label': action.get('label'), 'url': sanitize_url(page.url)}))
            elif after_errors > before_errors:
                action.update(state='EXECUTED', allowed=True, reason='SMOKE_ACTION')
                record['checks'].append(check(check_id, 'FAIL', 'ACTION_SMOKE_JS_ERROR',
                                              expected='No new JavaScript error after click',
                                              actual={'label': action.get('label'), 'newErrors': after_errors - before_errors}))
            else:
                action.update(state='EXECUTED', allowed=True, reason='SMOKE_ACTION')
                record['checks'].append(check(check_id, 'PASS', 'ACTION_SMOKE_OK',
                                              expected='Click keeps origin, no JS error, document responsive',
                                              actual={'label': action.get('label'), 'navigated': page.url != before_url,
                                                      'submitted': bool(submits), 'filledFields': filled}))
            discovered = _discover(page, options, record, side)
            if discovered is not None:
                register(discovered['candidates'])
            if page.url != before_url:
                page.goto(before_url, wait_until='domcontentloaded', timeout=budget.timeout())
        except Exception as exc:
            action['state'] = 'ERROR'
            # A smoke click that could not be dispatched/reset is evidence for a person, not a row verdict.
            record['checks'].append(check(check_id, 'REVIEW', 'ACTION_SMOKE_ERROR', expected='Click dispatch and reset',
                                          actual={'label': action.get('label'), 'error': type(exc).__name__}, required=False))
            try:
                if page.url != before_url:
                    page.goto(before_url, wait_until='domcontentloaded', timeout=budget.timeout())
            except Exception:
                break


_AUTO_DISMISS_JS = r'''() => {
  const vw = innerWidth, vh = innerHeight;
  const visible = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && r.bottom > 0 && r.top < vh; };
  const closeText = /^(닫기|close|×|x|✕|확인|오늘\s*하루\s*(보지\s*않기|닫기)|(오늘|7일간?|일주일|다시)\s*(보지\s*않기|열지\s*않기)|do not show|don't show|dismiss)$/i;
  const layers = [...document.querySelectorAll('[role=dialog],[aria-modal="true"],[class*="popup" i],[class*="modal" i],[class*="layer" i],[id*="popup" i],[id*="modal" i],[class*="notice-pop" i]')]
    .filter(el => visible(el) && (['fixed','absolute'].includes(getComputedStyle(el).position) || el.getAttribute('role') === 'dialog'))
    .filter(el => { const r = el.getBoundingClientRect(); return r.width * r.height > vw * vh * 0.04; });
  const out = [];
  for (const layer of layers.slice(0, 5)) {
    const controls = [...layer.querySelectorAll('button, a, [role=button], input[type=button], label, span, i, em')].filter(visible);
    let control = controls.find(el => closeText.test((el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || el.value || '').replace(/\s+/g, ' ').trim()))
      || controls.find(el => /close|btn-x|ico-x|dismiss/i.test(el.className + ' ' + (el.id || '') + ' ' + (el.getAttribute('aria-label') || '')));
    if (!control) continue;
    const path = []; let node = control;
    while (node && node !== document.body && path.length < 6) { const parent = node.parentElement; if (!parent) break; const idx = [...parent.children].indexOf(node) + 1; path.unshift(node.tagName.toLowerCase() + ':nth-child(' + idx + ')'); node = parent; }
    out.push({ selector: path.join(' > '), text: (control.textContent || control.getAttribute('aria-label') || '').trim().slice(0, 40), layer: (layer.id ? '#' + layer.id : '.' + String(layer.className).split(' ')[0]) });
  }
  return out;
}'''


def _dismiss_overlays(page, record, options, side, budget):
    """Close marketing popups/layers before capture; each close is recorded, never assumed.

    Configured selectors run first; then, with ``auto_dismiss`` (profile default), any
    visible fixed/dialog layer covering >4% of the viewport is closed through its own
    닫기/close/오늘 하루 보지 않기 control. Nothing outside such a layer is clicked.
    """
    closed = []
    if options.get('auto_dismiss', False):
        for _round in range(3):
            try:
                found = page.evaluate(_AUTO_DISMISS_JS) or []
            except Exception:
                found = []
            if not found:
                break
            progressed = False
            for item in found:
                try:
                    locator = page.locator('body > ' + item['selector']) if not item['selector'].startswith('html') else page.locator(item['selector'])
                    locator = page.locator(item['selector']) if locator.count() == 0 else locator
                    if locator.count() and locator.first.is_visible():
                        locator.first.click(timeout=budget.timeout(1500))
                        page.wait_for_timeout(min(250, budget.timeout(250)))
                        closed.append(f"auto:{item['layer']} → {item['text'] or 'close'}")
                        progressed = True
                except Exception:
                    continue
            if not progressed:
                break
    for selector in list(options.get('dismiss_selectors', []))[:10]:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible():
                locator.click(timeout=budget.timeout(3000))
                page.wait_for_timeout(min(250, budget.timeout(250)))
                closed.append(selector)
        except Exception:
            record['checks'].append(check(side + '.dismiss', 'REVIEW', 'DISMISS_SELECTOR_FAILED',
                                          expected='Overlay close control clickable', actual=selector))
    if closed:
        record['dismissed'] = closed
        record['checks'].append(check(side + '.dismiss', 'PASS', 'OVERLAYS_DISMISSED',
                                      expected='Overlays closed before capture', actual=closed, required=False))


def _flexible_text(text):
    """'모바일웹으로 계속하기|모바일 웹으로 이동하기' → regex ignoring whitespace, alternatives with |."""
    import re as _re
    parts = [p.strip() for p in str(text).split('|') if p.strip()]
    pattern = '|'.join(r'\s*'.join(_re.escape(ch) for ch in part.replace(' ', '')) for part in parts)
    return _re.compile(pattern, _re.I)


def _apply_entry_action(page, record, options, side, budget):
    """Dismiss a cover/landing gate on the start page with one approved click.

    Example: a legacy mobile SPA opens ``/#/`` as ``/#/coverPage`` and only shows
    the real home after "모바일 웹으로 이동하기". The click is recorded as evidence
    and the resulting URL becomes the start page for discovery. Route policy is
    unchanged: a full navigation to an unapproved path is still blocked.
    """
    entry = options.get('entry') or {}
    if not entry or entry.get('sides', 'both') not in ('both', side):
        return
    pattern = entry.get('urlPattern')
    if pattern and not (fnmatch.fnmatchcase(page.url, pattern) or fnmatch.fnmatchcase(page_key(page.url), pattern)):
        if record.get('depth', 0) == 0:
            record['checks'].append(check(side + '.entry', 'SKIP', 'ENTRY_ACTION_NOT_APPLICABLE',
                                          expected='urlPattern ' + pattern, actual=sanitize_url(page.url), required=False))
        return
    try:
        locator = page.locator(entry['selector'])
        if entry.get('text'):
            locator = locator.filter(has_text=_flexible_text(entry['text']))
        locator = locator.first
        if locator.count() == 0 or not locator.is_visible():
            record['checks'].append(check(side + '.entry', 'SKIP', 'ENTRY_ACTION_NOT_PRESENT',
                                          expected='Cover/landing gate element visible', actual='not visible', required=False))
            return
        before = page.url
        locator.click(timeout=budget.timeout(5000))
        try:
            page.wait_for_load_state('load', timeout=budget.timeout(8000))
        except Exception:
            pass
        page.wait_for_timeout(min(500, budget.timeout(500)))
        after = page.url
        if after == before:
            record['checks'].append(check(side + '.entry', 'REVIEW', 'ENTRY_ACTION_NO_NAVIGATION',
                                          expected='URL changes after the gate is dismissed', actual=sanitize_url(after)))
            return
        record['entryAction'] = {'selector': entry['selector'], 'before': sanitize_url(before), 'after': sanitize_url(after)}
        record['checks'].append(check(side + '.entry', 'PASS', 'ENTRY_ACTION_APPLIED',
                                      expected='Cover/landing gate dismissed once', actual=f'{sanitize_url(before)} → {sanitize_url(after)}'))
    except Exception as exc:
        record['checks'].append(check(side + '.entry', 'REVIEW', 'ENTRY_ACTION_FAILED',
                                      expected='One approved click on the start page', actual=type(exc).__name__))


def _visit(context, url, side, depth, options, artifact_root, run_id, budget, state):
    record = dict(url=url, finalUrl=url, title='', heading='', structure='', statusCode=None,
                  issues=[], checks=[], screenshot=None, screenshotFile=None, regions=[], actions=[],
                  depth=depth, observedAt=_now(), navigated=False, coverage={}, runId=run_id,
                  environment=side, pageId=_id(side + url), captureReady=False, readiness={})
    state['record'] = record
    page = _environment_page(context, state)
    try:
        response = page.goto(url, wait_until='domcontentloaded', timeout=budget.timeout())
        spa_route = False
        if response is None and state.get('document_status') and _origin(page.url) == state.get('document_origin'):
            # Same-document (hash) navigation in the persistent tab: the loaded document already
            # answered; the route itself has no HTTP response to observe.
            spa_route = True
        elif response is not None:
            state['document_status'], state['document_origin'] = response.status, _origin(page.url)
        record['statusCode'] = response.status if response else (state.get('document_status') if spa_route else None)
        record['finalUrl'] = page.url
        if response and response.status in (401, 403):
            record['checks'].append(check(side + '.document', 'BLOCKED',
                                          'LOGIN_REQUIRED' if response.status == 401 else 'ACCESS_DENIED',
                                          expected='Required authentication / access available', actual=response.status))
        elif response and response.status == 400:
            record['checks'].append(check(side + '.document', 'REVIEW', 'HTTP_STATUS_CONTRACT_UNSPECIFIED',
                                          expected='A specified response contract for this request', actual=response.status))
        elif response and response.status >= 400:
            record['checks'].append(check(side + '.document', 'FAIL', 'DOCUMENT_HTTP_ERROR',
                                          expected='HTTP < 400', actual=response.status))
        elif response:
            record['checks'].append(check(side + '.document', 'PASS', 'DOCUMENT_REACHABLE',
                                          expected='HTTP < 400', actual=response.status))
        elif spa_route:
            record['checks'].append(check(side + '.document', 'PASS', 'DOCUMENT_REACHABLE',
                                          expected='HTTP < 400 (loaded document)', actual=f"{state['document_status']} · SPA same-document route"))
        else:
            # Hash-only navigation does not necessarily have a document response.
            record['checks'].append(check(side + '.document', 'REVIEW', 'DOCUMENT_STATUS_UNAVAILABLE',
                                          expected='Document response or approved SPA contract', actual=None))
        record['navigated'] = True
        if response and response.status >= 400:
            # Error/auth documents do not satisfy the protected page's region/scenario prerequisites.
            record['checks'].append(check(side + '.page-ready', 'BLOCKED', 'PAGE_PREREQUISITE_UNAVAILABLE',
                                          expected='Intended page available for UI assertions', actual=response.status))
            return record
        load_ready = False
        try:
            page.wait_for_load_state('load', timeout=budget.timeout(3000))
            load_ready = True
        except Exception:
            record['checks'].append(check(side + '.ready', 'REVIEW', 'LOAD_NOT_CONFIRMED',
                                          expected='Load event within capture budget', actual='timeout'))
        fonts_ready = page.evaluate('() => Promise.race([(document.fonts?.ready || Promise.resolve()).then(() => true), new Promise(resolve => setTimeout(() => resolve(false), 1500))])')
        network_idle = False
        try:
            page.wait_for_load_state('networkidle', timeout=budget.timeout(min(4000, int(options.get('network_idle_ms', 4000)))))
            network_idle = True
        except Exception:
            pass
        record['readiness'] = {'load': load_ready, 'fonts': bool(fonts_ready), 'networkIdle': network_idle}
        record['captureReady'] = bool(load_ready and fonts_ready and (spa_route or (response and response.status < 400)))
        if not fonts_ready:
            record['checks'].append(check(side + '.fonts', 'REVIEW', 'FONTS_NOT_CONFIRMED',
                                          expected='Fonts ready before capture', actual='timeout'))
        page.wait_for_timeout(min(150, budget.timeout(150)))
        if options.get('entry') and (depth == 0 or options['entry'].get('urlPattern')):
            # A cover gate can swallow any route until it is dismissed, so with a urlPattern
            # the entry action may apply on deeper pages too (it skips when the pattern misses).
            _apply_entry_action(page, record, options, side, budget)
        if options.get('dismiss_selectors') or options.get('auto_dismiss'):
            _dismiss_overlays(page, record, options, side, budget)
        info = _discover(page, options, record, side)
        if info is None:
            return record
        # SPA redirects can settle after the document response or font readiness.
        record['finalUrl'] = page.url
        record.update(title=sanitize_message(info['title'], 160), heading=sanitize_message(info['heading'], 160),
                      structure=info['structure'])
        signature = info.get('signature') or {}
        record['pageSignature'] = {
            'landmarks': signature.get('landmarks', {}),
            'headings': [{key: sanitize_message(str(value), 100) for key, value in item.items()}
                         for item in signature.get('headings', [])],
            'formFields': [{key: sanitize_message(str(value), 100) for key, value in item.items()}
                           for item in signature.get('formFields', [])],
            'actionLabels': [sanitize_message(value, 100) for value in signature.get('actionLabels', [])],
            'navLabels': [sanitize_message(value, 100) for value in signature.get('navLabels', [])],
        }
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
                allowed, reason = classify_candidate(action, options, _seed_urls(options),
                                                     origin_url=options.get('_environment_seed') or url)
                action.update(id=_id(url + action['selector']), allowed=allowed, reason=reason,
                              state='DISCOVERED' if allowed else 'SKIP')
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
                    action.update(state='BLOCKED', reason=budget.reason() or 'ACTION_LIMIT_REACHED')
                    continue
                before = page.url
                errors_before = sum(1 for i in record['issues'] if i['category'] in ('JS_ERROR', 'JS_ERROR_AFTER_POLICY_BLOCK'))
                try:
                    page.locator(rule['selector']).click(timeout=budget.timeout(5000))
                    budget.completed += 1
                    action['state'] = 'EXECUTED'
                    if options.get('smoke_actions'):
                        # Smoke contract: same origin, no new JS error, document responsive.
                        new_errors = sum(1 for i in record['issues'] if i['category'] in ('JS_ERROR', 'JS_ERROR_AFTER_POLICY_BLOCK')) - errors_before
                        left_origin = _origin(page.url) != _origin(record['url'])
                        if left_origin or new_errors > 0:
                            record['checks'].append(check(side + '.click.' + action['id'], 'FAIL', 'ACTION_SMOKE_LEFT_SCOPE' if left_origin else 'ACTION_SMOKE_JS_ERROR',
                                                          expected='Approved click keeps origin and raises no JS error', actual={'url': sanitize_url(page.url), 'newErrors': new_errors}))
                        else:
                            record['checks'].append(check(side + '.click.' + action['id'], 'PASS', 'ACTION_SMOKE_OK',
                                                          expected='Approved click keeps origin, no JS error, document responsive', actual='Click dispatched'))
                    else:
                        # Successful click dispatch is not evidence of expected application behavior.
                        record['checks'].append(check(side + '.click.' + action['id'], 'REVIEW', 'ACTION_EXPECTATION_MISSING',
                                                      expected='A configured behavior assertion', actual='Click dispatched', required=False))
                    discovered = _discover(page, options, record, side)
                    if discovered is None:
                        return record
                    register(discovered['candidates'])
                    if page.url != before:
                        page.goto(before, wait_until='domcontentloaded', timeout=budget.timeout())
                except Exception as exc:
                    action['state'] = 'ERROR'
                    record['checks'].append(check(side + '.click.' + action['id'], 'ERROR', 'ACTION_OR_RESET_ERROR',
                                                  actual=type(exc).__name__))
                    break
        if options.get('smoke_actions') and options.get('mode') != 'discovery':
            _smoke_actions(page, record, options, budget, side, register)
        # Capture the settled baseline state before scenario actions mutate local UI.
        record['_active_scenario'], record['_active_step'] = 'engine', 'capture'
        blocked = [item for item in record['issues'] if item['category'] in ('POLICY_BLOCKED', 'EXECUTION_BLOCKED')]
        if blocked:
            record['readiness']['policyInterference'] = True
            record['readiness']['blockedThirdParty'] = sum(not item.get('renderingRelevant') for item in blocked)
        if any(item.get('renderingRelevant') for item in blocked):
            # Something the page itself needs was refused: the screenshot may not represent the product.
            record['captureReady'] = False
            record['readiness']['renderingBlocked'] = [sanitize_url(item['url']) for item in blocked if item.get('renderingRelevant')][:10]
        if options.get('conditions'):
            record['_conditions_started'] = True
            from .conditions import run_condition_checks
            if budget.reason():
                for condition in options['conditions']:
                    record['checks'].append(check(side + '.condition.' + condition['id'], 'BLOCKED', budget.reason(),
                                                  scenario_id='conditions', expected='Condition evaluated within budget'))
            else:
                try:
                    for item in run_condition_checks(page, options['conditions'], side, options,
                                                     lambda: bool(budget.reason())):
                        item = dict(item)
                        item['environment'] = side
                        item['check_id'] = side + '.' + item['check_id']
                        record['checks'].append(item)
                except Exception as exc:
                    record['checks'].append(check(side + '.conditions', 'ERROR', 'CONDITION_ENGINE_ERROR',
                                                  expected='Structured condition results', actual=type(exc).__name__))
        if budget.reason():
            record['checks'].append(check(side + '.capture', 'BLOCKED', budget.reason(), expected='Capture within budget'))
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
                    # Only classify newly emitted checks; historical reports remain unchanged.
                    if item.get('status') == 'SKIP' and unexecuted_status(item.get('reason_code')) == 'BLOCKED':
                        item['status'] = 'BLOCKED'
                    if item.get('reason_code') == 'POLICY_OR_BUDGET_BLOCKED' and any(
                            c['status'] == 'BLOCKED' and c.get('check_id', '').startswith('action.guard.') for c in record['checks']):
                        item['status'] = 'BLOCKED'
                    record['checks'].append(item)
            except Exception as exc:
                record['checks'].append(check(side + '.scenario', 'ERROR', 'SCENARIO_ENGINE_ERROR',
                                              expected='Structured scenario results', actual=type(exc).__name__))
        elif scenario_ids:
            for scenario in scenario_ids:
                record['checks'].append(check(side + '.' + scenario, 'BLOCKED', budget.reason() or 'SCENARIO_NOT_RUN',
                                              scenario_id=scenario, expected='Scenario execution'))
    except Exception as exc:
        reason = budget.reason()
        policy_blocked = url in state['blocked_urls'] or any(i['category'] == 'POLICY_BLOCKED' for i in record['issues'])
        record['checks'].append(check(side + '.navigation', 'BLOCKED' if reason else 'SKIP' if policy_blocked else 'ERROR',
                                      reason or ('POLICY_BLOCKED' if policy_blocked else 'NAVIGATION_ERROR'),
                                      expected='Approved, reachable page', actual=type(exc).__name__))
    finally:
        if options.get('conditions') and not record.get('_conditions_started'):
            for condition in options['conditions']:
                record['checks'].append(check(side + '.condition.' + condition['id'], 'BLOCKED',
                                              'PAGE_PREREQUISITE_UNAVAILABLE', scenario_id='conditions',
                                              expected='Page ready for condition assertion'))
        if depth == 0 and options.get('mode', 'combined') == 'combined' and not state.get('scenario_done'):
            for scenario in options.get('scenario_ids', []):
                record['checks'].append(check(side + '.' + scenario, 'BLOCKED', 'PAGE_PREREQUISITE_UNAVAILABLE',
                                              scenario_id=scenario, expected='Seed page ready for scenarios'))
        # Do not export raw candidate URLs containing authentication query values.
        for action in record['actions']:
            action['_navigation_url'] = action.get('href')
            for key in ('href', 'pageUrl', 'formAction'):
                if action.get(key):
                    action[key] = sanitize_url(action[key])
        lenient = options.get('observation_mode', 'strict') == 'lenient'
        for issue in record['issues']:
            level = issue['level']
            informational = False
            if lenient and level in ('FAIL', 'REVIEW') and issue['category'] in _INFORMATIONAL_CATEGORIES:
                # Real sites emit console noise and third-party 404s constantly; in lenient
                # mode they are kept as evidence under "기타" and do not decide the row status.
                informational = True
            item = check(side + '.observation.' + issue['observationId'], level,
                         issue['category'], expected='Healthy required resources / review optional observations',
                         actual=issue['message'], evidence=[issue['url']] if issue['url'] else [],
                         scenario_id=issue.get('scenarioId') or 'engine', step_id=issue.get('stepId') or 'observe',
                         required=level != 'SKIP' and not informational)
            item['observation'] = dict(issue)
            if informational:
                item['informational'] = True
            record['checks'].append(item)
        for item in record['checks']:
            item.setdefault('environment', side)
            item.setdefault('pageId', record['pageId'])
            item.setdefault('timestamp', _now())
        # The tab stays open: in-flight requests aborted by the next navigation are
        # attributed to no record (the previous page is already finalized).
        record['_closing'] = True
        state['record'] = None
    return record


def _route_style(seed):
    parts = urlsplit(seed)
    return 'hash' if parts.fragment.startswith('/') else 'path'


def _translate_route(url, from_seed, to_seed):
    """Move a route between a path-routed app and a hash-routed SPA of the same product.

    dev2 ``/educourse/middle`` ↔ legacy ``/#/educourse/middle``; the start page shell
    (``/`` vs ``/#/``) is taken from the target seed. Query strings follow the route.
    """
    parts, target = urlsplit(url), urlsplit(to_seed)
    source_style, target_style = _route_style(from_seed), _route_style(to_seed)
    if source_style == 'hash':
        route, _, query = parts.fragment.partition('?')
        route = route or '/'
        query = query or parts.query
    else:
        route, query = parts.path or '/', parts.query
    if target_style == 'hash':
        shell = target.path or '/'
        fragment = route + ('?' + query if query else '')
        return urlunsplit((target.scheme, target.netloc, shell, '', fragment))
    return urlunsplit((target.scheme, target.netloc, route, query, ''))


def _environment_page(context, state):
    """One tab per environment context, created lazily and reused for login, gate and every visit."""
    page = state.get('page')
    if page is None or page.is_closed():
        page = context.new_page()
        _attach_observers(page, state)
        state['page'] = page
    return page


def _skipped_page(url, side, reason, depth=0, *, status=None, actual=None):
    return dict(url=url, finalUrl=url, title='', heading='', structure='', statusCode=None,
                screenshot=None, screenshotFile=None, issues=[], regions=[], actions=[], navigated=False,
                depth=depth, checks=[check(side + '.visit', status or unexecuted_status(reason), reason,
                                          expected='Planned page visit', actual=actual)], coverage={})


_LOGIN_LINK = 'a:has-text("로그인"), button:has-text("로그인"), [role=button]:has-text("로그인"), a:has-text("Login"), a:has-text("login"), a:has-text("Sign in"), a[href*="login" i], a[href*="signin" i]'


_LOGIN_ROUTES = ('/login', '/#/login', '/member/login', '/members/login', '/user/login', '/users/login',
                 '/signin', '/sign-in', '/auth/login', '/login.do', '/member/login.do', '/#/member/login')


def _find_login_form(page, budget, options=None, side='a'):
    """Locate (username, password, submit) without configuration.

    1. A visible password field on the current page wins.
    2. Else follow a visible 로그인/login link or button once.
    3. Else use a hidden login link's href (mobile menus hide it in a drawer).
    4. Else try well-known login routes on the start origin.
    After each navigation a configured cover gate is dismissed again if it reappears.
    The password field anchors the form; the username is the nearest visible
    text/email/tel input before it; submit is the form's submit control or a
    로그인-labelled button, else None (Enter is pressed on the password field).
    """
    options = options or {}

    def settle():
        try:
            page.wait_for_load_state('load', timeout=budget.timeout(8000))
        except Exception:
            pass
        page.wait_for_timeout(min(400, budget.timeout(400)))
        if options.get('entry'):
            _apply_entry_action(page, {'checks': [], 'depth': 0, 'url': page.url}, options, side, budget)

    def password_field():
        candidates = page.locator('input[type=password]')
        for index in range(min(candidates.count(), 5)):
            item = candidates.nth(index)
            if item.is_visible():
                return item
        return None

    password = password_field()
    if password is None:
        link = page.locator(_LOGIN_LINK).first
        if link.count() and link.is_visible():
            link.click(timeout=budget.timeout(5000))
            settle()
            password = password_field()
    if password is None:
        href = page.evaluate('''() => {
            const el = [...document.querySelectorAll('a[href]')].find(a => /로그인|login|signin|sign-in/i.test((a.textContent || '') + ' ' + a.getAttribute('href')));
            return el ? el.href : null; }''')
        if href and host_allowed(href, options.get('allowed_hosts', [urlsplit(page.url).hostname])):
            page.goto(href, wait_until='domcontentloaded', timeout=budget.timeout(15000))
            settle()
            password = password_field()
    if password is None:
        origin = urlsplit(page.url)
        for route in _LOGIN_ROUTES:
            if budget.reason():
                break
            candidate = urlunsplit((origin.scheme, origin.netloc, route.split('#')[0] or '/', '', route.partition('#')[2]))
            try:
                response = page.goto(candidate, wait_until='domcontentloaded', timeout=budget.timeout(10000))
            except Exception:
                continue
            if response is not None and response.status >= 400:
                continue
            settle()
            password = password_field()
            if password is not None:
                break
    if password is None:
        return None
    username = page.evaluate_handle('''pw => {
        const inputs = [...document.querySelectorAll('input')];
        const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
        const before = inputs.slice(0, inputs.indexOf(pw)).reverse();
        return before.find(el => ['text', 'email', 'tel', 'number', ''].includes((el.type || '').toLowerCase()) && visible(el)) || null;
    }''', password.element_handle())
    if username.as_element() is None:
        return None
    submit = None
    form_submit = password.locator('xpath=ancestor::form[1]//button[not(@type="button")] | ancestor::form[1]//input[@type="submit"]').first
    labelled = page.locator('button:has-text("로그인"), input[type=submit][value*="로그인"], [role=button]:has-text("로그인"), a:has-text("로그인"), button:has-text("Login"), button:has-text("Sign in")').first
    for candidate in (form_submit, labelled):
        try:
            if candidate.count() and candidate.is_visible():
                submit = candidate
                break
        except Exception:
            continue
    return _handle_locator(page, username), password, submit


def _handle_locator(page, handle):
    """Wrap an element handle in a locator-like object exposing fill()."""
    class _Wrapped:
        def __init__(self, element):
            self.element = element
        def fill(self, value, timeout=None):
            self.element.fill(value, timeout=timeout)
    return _Wrapped(handle.as_element())


def _test_account_login(context, side, options, budget, state):
    """Fill a configured login form with locally stored test-account credentials.

    Credentials come from qa.secrets only, never from options/report. The step
    returns a single check for the start page row and never raises.
    """
    from .secrets import load_credentials
    login = options.get('login') or {}
    seed = options['baseline_url' if side == 'a' else 'candidate_url']
    target = login.get('url') or seed
    credentials = load_credentials(side, login.get('accountKey', 'default'))
    if credentials is None:
        return check(side + '.login', 'BLOCKED', 'LOGIN_CREDENTIALS_MISSING',
                     expected='QA_LOGIN_[A|B]_ID/PW environment variables or secrets/accounts.json',
                     actual='No credentials available on this machine'), None
    if not host_allowed(target, options['allowed_hosts']):
        return check(side + '.login', 'BLOCKED', 'LOGIN_HOST_NOT_APPROVED',
                     expected='Login URL host in allowedHosts', actual=sanitize_url(target)), None
    page = _environment_page(context, state)
    state['manual_auth'] = True  # auth phase: the network guard permits the form POST on approved hosts
    try:
        page.goto(target, wait_until='domcontentloaded', timeout=budget.timeout(20000))
        try:
            page.wait_for_load_state('load', timeout=budget.timeout(8000))
        except Exception:
            pass
        auto = not login.get('usernameSelector')
        if options.get('entry'):
            # Mobile sites gate the login page behind /coverPage too: dismiss it first, same tab.
            gate_record = {'checks': [], 'depth': 0, 'url': page.url}
            _apply_entry_action(page, gate_record, options, side, budget)
            state['login_gate'] = [c['reason_code'] for c in gate_record['checks']]
        if auto:
            form = _find_login_form(page, budget, options, side)
            if form is None:
                return check(side + '.login', 'BLOCKED', 'LOGIN_FORM_NOT_FOUND',
                             expected='A visible password field (after following a 로그인/login link if needed)',
                             actual=sanitize_url(page.url)), credentials
            username, password, submit = form
        else:
            username, password = page.locator(login['usernameSelector']).first, page.locator(login['passwordSelector']).first
            submit = page.locator(login['submitSelector']).first
        username.fill(credentials.username, timeout=budget.timeout(5000))
        password.fill(credentials.password, timeout=budget.timeout(5000))
        before = page.url
        if submit is not None:
            submit.click(timeout=budget.timeout(5000))
        else:
            password.press('Enter', timeout=budget.timeout(5000))
        try:
            page.wait_for_load_state('load', timeout=budget.timeout(10000))
        except Exception:
            pass
        page.wait_for_timeout(min(400, budget.timeout(400)))
        failure_visible = bool(login.get('failureSelector')) and page.locator(login['failureSelector']).first.is_visible()
        if login.get('successSelector'):
            success = page.locator(login['successSelector']).first.is_visible() and not failure_visible
            basis = 'successSelector'
        else:
            password_fields = page.locator(login['passwordSelector']) if not auto else page.locator('input[type=password]:visible')
            still_on_form = password_fields.count() > 0 and page.url == before
            logged_in_marker = page.locator('text=/로그아웃|logout|마이페이지|my ?page/i').first.count() > 0
            success = not failure_visible and (logged_in_marker or not still_on_form)
            basis = 'logout/마이페이지 marker, or password field gone / URL changed'
        if success:
            return check(side + '.login', 'PASS', 'TEST_ACCOUNT_LOGIN_OK', expected='Login success evidence: ' + basis,
                         actual={'credentials': credentials.source.split(':')[0], 'loginUrl': sanitize_url(before),
                                 'afterUrl': sanitize_url(page.url), 'gate': state.get('login_gate') or []}), credentials
        return check(side + '.login', 'BLOCKED', 'LOGIN_FAILED', expected='Login success evidence: ' + basis,
                     actual='Failure marker visible' if failure_visible else 'Login form still present'), credentials
    except Exception as exc:
        return check(side + '.login', 'ERROR', 'LOGIN_STEP_ERROR', expected='Login form interaction', actual=type(exc).__name__), credentials
    finally:
        state['manual_auth'] = False


def _crawl(browser, side, options, artifact_root, run_id, progress, budget, auth_gate):
    options = dict(options)
    options['_side_action_start'] = budget.actions
    # Reserve at least half the action allowance for B before A starts.
    options['_side_action_limit'] = (budget.maximum // 2 if side == 'a' and options.get('test_type', 'comparison') == 'comparison'
                                     else budget.maximum - budget.actions)
    seed = options['baseline_url' if side == 'a' else 'candidate_url']
    options['_environment_seed'] = seed
    context = browser.new_context(viewport=options.get('viewport', {'width': 1365, 'height': 768}),
                                  device_scale_factor=1, locale='ko-KR', timezone_id='Asia/Seoul',
                                  color_scheme='light', reduced_motion='reduce',
                                  service_workers='block', accept_downloads=False)
    state = dict(record=None, blocked=[], blocked_urls=set(), manual_auth=False, scenario_done=False)
    _network_guard(context, options, _seed_urls(options), side, state, budget)
    pages, deferred = OrderedDict(), []
    trails = {normalize_url(seed): ['start-page']}
    queue, seen = deque([(seed, 0)]), {normalize_url(seed)}
    sample_limit = int(options.get('instance_sample_limit', 3) or 0)
    template_counts = {instance_template(normalize_url(seed)): 1}
    mirror_paths, mirrored_identities = set(), set()
    for mirrored in options.get('_mirror_urls', []):
        try:
            identity = normalize_url(mirrored['url'])
        except (ValueError, KeyError, TypeError):
            continue
        if identity in seen:
            continue
        seen.add(identity)
        mirrored_identities.add(identity)
        template_counts[instance_template(identity)] = template_counts.get(instance_template(identity), 0) + 1
        # Keep A's menu trail so semantic corroboration (same trail + heading) still applies.
        trails[identity] = list(mirrored.get('trail') or ['start-page'])
        queue.append((identity, int(mirrored.get('depth') or 1)))
        parts = urlsplit(identity)
        mirror_paths.add((parts.path or '/') + ('#' + parts.fragment.split('?', 1)[0] if parts.fragment else ''))
    options['_mirror_paths'] = mirror_paths
    def deferred_page(url, reason, depth):
        record = _skipped_page(url, side, reason, depth)
        record['navigationTrail'] = trails.get(normalize_url(url), [])
        return record
    try:
        if options.get('manual_login'):
            if auth_gate is None:
                return OrderedDict([(seed, _skipped_page(seed, side, 'MANUAL_AUTH_REQUIRED'))]), [], state
            state['manual_auth'] = True
            try:
                try:
                    auth_gate(side, context, seed, _environment_page(context, state))
                except TypeError as exc:
                    if 'positional' not in str(exc):
                        raise
                    auth_gate(side, context, seed)
            except InterruptedError:
                state['auth_cancelled'] = True
                return OrderedDict([(seed, _skipped_page(seed, side, 'CANCELLED'))]), [], state
            except TimeoutError:
                state['auth_timeout'] = True
                return OrderedDict([(seed, _skipped_page(seed, side, 'AUTH_TIME_LIMIT_REACHED'))]), [], state
            except Exception as exc:
                return OrderedDict([(seed, _skipped_page(seed, side, 'MANUAL_AUTH_ERROR',
                                                        status='ERROR', actual=type(exc).__name__))]), [], state
            finally:
                state['manual_auth'] = False
            if budget.reason():
                return OrderedDict([(seed, _skipped_page(seed, side, budget.reason()))]), [], state
        login_check = None
        if options.get('login') and not options.get('manual_login'):
            progress(f'{side.upper()}: 테스트 계정으로 로그인 중')
            login_check, credentials = _test_account_login(context, side, options, budget, state)
            if credentials is not None:
                # Never let the typed account name reach a capture.
                masks = list(options.get('private_mask_selectors', []))
                masks.extend(selector for selector in (options['login'].get('usernameSelector'),) if selector and selector not in masks)
                options['private_mask_selectors'] = masks
            state['login_check'] = login_check
            if budget.reason():
                return OrderedDict([(seed, _skipped_page(seed, side, budget.reason()))]), [], state
        while queue and len(pages) < int(options.get('max_pages', 5)):
            url, depth = queue.popleft()
            if budget.reason():
                deferred.append(deferred_page(url, budget.reason(), depth))
                break
            progress(f'{side.upper()}: {len(pages) + 1}/{options.get("max_pages", 5)} {sanitize_url(url)}')
            record = _visit(context, url, side, depth, options, artifact_root, run_id, budget, state)
            record['navigationTrail'] = trails.get(normalize_url(url), [])
            if normalize_url(url) in mirrored_identities:
                record['mirroredFromBaseline'] = True
            if login_check is not None:
                login_check = dict(login_check, environment=side, pageId=record['pageId'], timestamp=_now())
                record['checks'].insert(0, login_check)
                login_check = None
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
                template = instance_template(normalized)
                if sample_limit:
                    if template_counts.get(template, 0) >= sample_limit:
                        # Same page shape with another record (prev/next post, page 7 of 40): enough samples.
                        action.update(state='SKIP', reason='SAMPLE_LIMIT_REACHED')
                        deferred.append(deferred_page(normalized, 'SAMPLE_LIMIT_REACHED', depth + 1))
                        continue
                    template_counts[template] = template_counts.get(template, 0) + 1
                trails[normalized] = [*record.get('navigationTrail', []),
                                      sanitize_message(action.get('label') or page_key(normalized), 100)]
                if depth >= int(options.get('max_depth', 1)):
                    action.update(state='BLOCKED', reason='DEPTH_LIMIT_REACHED')
                    deferred.append(deferred_page(normalized, 'DEPTH_LIMIT_REACHED', depth + 1))
                else:
                    action['state'] = 'QUEUED'
                    queue.append((normalized, depth + 1))
        reason = budget.reason() or 'PAGE_LIMIT_REACHED'
        deferred.extend(deferred_page(url, reason, depth) for url, depth in queue)
        for record in pages.values():
            for action in record['actions']:
                target = action.pop('_target_identity', None)
                if target in pages and pages[target].get('navigated'):
                    action.update(state='URL_VISITED', reason='NAVIGATION_VISITED_NOT_CLICK_ASSERTED')
                elif action['state'] == 'QUEUED':
                    action.update(state='BLOCKED', reason=reason)
    finally:
        context.close()
    return pages, deferred, state


def _result_rows(pairs, options, artifact_root, run_id):
    rows = []
    for pair in pairs:
        a, b, match = pair['baseline'], pair['candidate'], pair['match']
        comparable = bool(a and b and match.get('approved') and a.get('captureReady') and b.get('captureReady'))
        comparison_context = {'comparable': comparable,
                              'uncertainty_reason': 'REVIEW_MATCH' if not match.get('approved') else 'COMPARISON_CONDITIONS_UNCONFIRMED'}
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
        base = dict(id=_id(pair['key'] + (a or b)['url']), key=sanitize_url(pair['key']), region_id='page',
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
                    region_checks.append(check(f'region.{rid}.match', 'BLOCKED', 'MATCH_SIDE_UNAVAILABLE', required=region.get('required', True)))
                    visual = None
                elif any(r and r.get('state') in ('MISSING', 'HIDDEN') for r in (left, right)):
                    region_checks.append(check(f'region.{rid}.visual', 'BLOCKED', 'REGION_PREREQUISITE_FAILED', required=region.get('required', True)))
                    visual = None
                elif any(c['status'] == 'BLOCKED' and c.get('required', True) for c in checks) and not (left and right):
                    region_checks.append(check(f'region.{rid}.visual', 'BLOCKED', 'CAPTURE_PREREQUISITE_FAILED',
                                               required=region.get('required', True)))
                    visual = None
                else:
                    visual = image_diff(left, right, artifact_root, run_id, pair['key'] + '#' + rid)
                    region_checks.append(visual_check(visual, options.get('visual_threshold', 2),
                                                      f'region.{rid}.visual', **comparison_context))
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
                if any(c['status'] == 'BLOCKED' and c.get('required', True) for c in checks) and not (a.get('screenshotFile') and b.get('screenshotFile')):
                    visual = None
                    checks.append(check('visual', 'BLOCKED', 'CAPTURE_PREREQUISITE_FAILED'))
                else:
                    visual = image_diff(a, b, artifact_root, run_id, pair['key'])
                    checks.append(visual_check(visual, options.get('visual_threshold', 2), **comparison_context))
            else:
                visual = None
                checks.append(check('visual', 'BLOCKED', 'MATCH_SIDE_UNAVAILABLE'))
            base.update(visual=visual, checks=checks, status=aggregate_status(checks),
                        flags=sorted({c['reason_code'] for c in checks if c['status'] != 'PASS'}))
            rows.append(base)
    return rows


def _single_rows(pages, options):
    """Independent assertions only; omitting B never invents a missing-match issue."""
    rows = []
    for page in pages.values():
        checks = list(page.get('checks', []))
        if not checks:
            checks.append(check('scope', 'SKIP', 'NO_ASSERTIONS_SELECTED', expected='At least one explicit assertion'))
        base = dict(id=_id('single:' + page['url']), key=page_key(sanitize_url(page['url'])), region_id='page',
                    baseline=_safe_record(page), candidate=None, visual=None, checks=checks,
                    status=aggregate_status(checks), flags=sorted({c['reason_code'] for c in checks if c['status'] != 'PASS'}),
                    match={'method': 'SINGLE_ENVIRONMENT', 'confidence': None, 'approved': False,
                           'reason': 'CROSS_ENVIRONMENT_COMPARISON_NOT_REQUESTED'},
                    review={'status': 'UNREVIEWED', 'revision': 0, 'events': []})
        rows.append(base)
        for region in options.get('regions', []):
            rid = region['id']
            region_checks = [c for c in checks if c.get('check_id') in (f'a.region.{rid}', f'a.region.{rid}.capture')]
            if not region_checks:
                region_checks = [check(f'a.region.{rid}', 'BLOCKED', 'PAGE_PREREQUISITE_UNAVAILABLE',
                                       expected='Independent region assertion', required=region.get('required', True))]
            capture = next((r for r in page.get('regions', []) if r['id'] == rid), {})
            rows.append(dict(base, id=_id(base['id'] + rid), region_id=rid,
                             baseline=dict(base['baseline'], screenshot=capture.get('screenshot')),
                             checks=region_checks, status=aggregate_status(region_checks),
                             flags=sorted({c['reason_code'] for c in region_checks if c['status'] != 'PASS'})))
    return rows


def run_scan(options, run_id, artifact_root, progress, cancelled, auth_gate=None):
    """Run one bounded scan; contexts and credentials never enter report/store state."""
    options = dict(options)
    test_type = options.get('test_type', 'comparison')
    if test_type not in ('comparison', 'single', 'regression', 'conditional'):
        raise ValueError('Unsupported test type.')
    comparison = test_type == 'comparison'
    options['test_type'] = test_type
    options['baseline_url'] = normalize_url(options['baseline_url'])
    options['candidate_url'] = normalize_url(options['candidate_url']) if comparison else None
    if not options.get('allowed_hosts'):
        options['allowed_hosts'] = sorted({urlsplit(seed).hostname for seed in _seed_urls(options)})
    for key in ('baseline_url', 'candidate_url') if comparison else ('baseline_url',):
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
            if not comparison:
                b, b_skip, b_state = OrderedDict(), [], {'blocked': []}
            elif budget.reason() or a_state.get('auth_cancelled') or a_state.get('auth_timeout'):
                reason = ('CANCELLED' if a_state.get('auth_cancelled') else
                          'AUTH_TIME_LIMIT_REACHED' if a_state.get('auth_timeout') else budget.reason())
                b = OrderedDict([(options['candidate_url'], _skipped_page(options['candidate_url'], 'b', reason))])
                b_skip, b_state = [], {'blocked': []}
            else:
                # Pair-first crawl: B visits the routes A actually reached (translated to B's origin)
                # before its own link discovery, so most rows pair instead of splitting into A-only/B-only.
                mirror = []
                a_seed, b_seed = urlsplit(options['baseline_url']), urlsplit(options['candidate_url'])
                from .matching import equivalent_route_key
                # Mirroring only makes sense for "same app on another host" pairs: different hosts whose
                # start pages are the same route. Same-host pairs (demo /a vs /b) keep independent crawls.
                mirror_enabled = (bool(options.get('mirror_routes', True)) and a_seed.netloc != b_seed.netloc
                                  and equivalent_route_key(options['baseline_url']) == equivalent_route_key(options['candidate_url']))
                for page in (a.values() if mirror_enabled else []):
                    if not page.get('navigated'):
                        continue
                    for source in (page.get('finalUrl'), page.get('url')):
                        if not source:
                            continue
                        parts = urlsplit(source)
                        if (parts.scheme, parts.netloc) != (a_seed.scheme, a_seed.netloc):
                            continue
                        if readonly_navigation_reason({'url': source}, options.get('safety_level', 'strict')) and parts.path not in ('', '/'):
                            continue
                        mirror.append({'url': _translate_route(source, options['baseline_url'], options['candidate_url']),
                                       'trail': page.get('navigationTrail') or ['start-page'], 'depth': max(1, int(page.get('depth') or 1))})
                        break
                b_options = dict(options, _mirror_urls=mirror)
                b, b_skip, b_state = _crawl(browser, 'b', b_options, artifact_root, run_id, progress, budget, auth_gate)
        finally:
            browser.close()
    progress('Comparing route mappings and region evidence' if comparison else 'Summarizing independent environment assertions')
    start_pair = ({'baseline': options['baseline_url'], 'candidate': options['candidate_url']}
                  if comparison and options.get('pair_start_pages', False) else None)
    pairs = match_pages(a, b, options.get('route_aliases', []), start_pair=start_pair,
                        route_equivalence=bool(options.get('route_equivalence', True))) if comparison else []
    rows = (_result_rows(pairs, options, artifact_root, run_id)
            if comparison else _single_rows(a, options))
    for side, deferred in (('a', a_skip), ('b', b_skip)):
        # One summary row per (environment, reason): every unvisited page stays in the inventory,
        # but hundreds of "page limit reached" rows would bury the real findings.
        groups = OrderedDict()
        for page in deferred:
            groups.setdefault(page['checks'][0]['reason_code'], []).append(page)
        for reason, pages_for_reason in groups.items():
            first = pages_for_reason[0]
            urls = [page_key(sanitize_url(page['url'])) for page in pages_for_reason]
            summary_check = dict(first['checks'][0], check_id=side + '.visit', expected='Planned page visits',
                                 actual={'unvisitedPages': len(urls), 'examples': urls[:20]})
            record = dict(first, url=first['url'], title=f'{len(urls)}개 페이지 미방문 · {reason}', checks=[summary_check])
            rows.append(dict(id=_id(side + reason + '.deferred'), key=f'__unvisited__/{side}/{reason.lower()}', region_id='page',
                             status=aggregate_status([summary_check]), flags=[reason], checks=[summary_check],
                             unvisitedPages=urls, unvisitedCount=len(urls),
                             baseline=_safe_record(record) if side == 'a' else None,
                             candidate=_safe_record(record) if side == 'b' else None, visual=None,
                             match={'method': 'NOT_EXECUTED' if comparison else 'SINGLE_ENVIRONMENT', 'confidence': 'LOW', 'approved': False},
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
                   for status in STATUSES})
    totals['checks'] = {status.lower(): sum(c['status'] == status for c in unique_checks.values()) for status in STATUSES}
    totals['checkStatusCounts'] = {status: totals['checks'][status.lower()] for status in STATUSES}
    blocked_requests = a_state['blocked'] + b_state['blocked']
    scope = dict(targetShape='pair' if comparison else 'single', baselineUrl=sanitize_url(options['baseline_url']),
                 candidateUrl=sanitize_url(options['candidate_url']) if comparison else None,
                 maxPages=options.get('max_pages', 5), maxDepth=options.get('max_depth', 1),
                 maxActions=options.get('max_actions', 10), allowedPaths=sorted(options.get('allowed_paths', [])),
                 allowedHosts=sorted(options.get('allowed_hosts', [])),
                 resourceHosts=sorted(options.get('resource_hosts', [])), regions=options.get('regions', []),
                 crawlScope=options.get('crawl_scope', 'approved_paths'))
    capture = dict(browser=browser_version, viewport=options.get('viewport', {'width': 1365, 'height': 768}), dpr=1,
                   locale='ko-KR', timezone='Asia/Seoul', colorScheme='light', reducedMotion='reduce',
                   fullPage=False, maskVersion='v2', pixelTolerance=25)
    rules = {key: options.get(key, []) for key in ('route_aliases', 'regions', 'scenario_ids', 'conditions', 'safe_actions', 'private_mask_selectors')}
    rules.update(visual_threshold=options.get('visual_threshold', 2), rule_version='v2.3',
                 pair_start_pages=bool(options.get('pair_start_pages', False)),
                 route_equivalence=bool(options.get('route_equivalence', True)),
                 login_form={key: value for key, value in (options.get('login') or {}).items()} or None,
                 entry=options.get('entry') or None, xhr_policy=options.get('xhr_policy', 'allow_allowed_hosts'),
                 dismiss_selectors=options.get('dismiss_selectors', []), auto_dismiss=bool(options.get('auto_dismiss')), observation_mode=options.get('observation_mode', 'strict'),
                 smoke_actions=bool(options.get('smoke_actions')), smoke_action_limit=int(options.get('smoke_action_limit', 20)),
                 safety_level=options.get('safety_level', 'strict'), instance_sample_limit=int(options.get('instance_sample_limit', 3) or 0))
    checksum = lambda value: sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    incomplete = bool(blocked_requests or a_skip or b_skip or budget.reason()
                      or any(c['status'] in ('BLOCKED', 'ERROR') and c.get('required', True) for c in unique_checks.values()))
    was_cancelled = bool(cancelled() or a_state.get('auth_cancelled') or b_state.get('auth_cancelled'))
    from .inventory import build_inventory
    inventory = build_inventory(options, a, b, a_skip, b_skip, pairs)
    return dict(testType=test_type, previousRunId=options.get('previous_run_id'), inventory=inventory,
                baselineUrl=sanitize_url(options['baseline_url']), candidateUrl=sanitize_url(options['candidate_url']) if comparison else None,
                maxPages=options.get('max_pages', 5), maxDepth=options.get('max_depth', 1),
                visualThreshold=options.get('visual_threshold', 2), totals=totals, results=rows,
                manifest=dict(schemaVersion='2.0', runId=run_id, profileId=options.get('profile_id', 'custom'),
                              operatorId=options.get('operator_id', ''), startedAt=started, finishedAt=_now(),
                              python=platform.python_version(), playwright=version('playwright'), pillow=version('Pillow'),
                              browser=browser_version, viewport=options.get('viewport', {'width': 1365, 'height': 768}),
                              mode=options.get('mode', 'combined'), testType=test_type,
                              status='CANCELLED' if was_cancelled else 'PARTIAL' if incomplete else 'COMPLETED',
                              ruleVersion='v2.3', rulesHash=checksum(rules), scope=scope, scopeHash=checksum(scope), capture=capture,
                              environmentNames={'a': options.get('baseline_name') or 'A',
                                                'b': options.get('candidate_name') or 'B'} if comparison else {'a': options.get('baseline_name') or 'A'},
                              environmentIds={'a': options.get('baseline_environment_id', 'custom'),
                                              'b': options.get('candidate_environment_id', 'custom')} if comparison else {'a': options.get('baseline_environment_id', 'custom')},
                              pairStartPages=bool(start_pair), routeEquivalence=bool(options.get('route_equivalence', True)),
                              entry=options.get('entry') or None, xhrPolicy=options.get('xhr_policy', 'allow_allowed_hosts'),
                              dismissSelectors=options.get('dismiss_selectors', []), autoDismiss=bool(options.get('auto_dismiss')), observationMode=options.get('observation_mode', 'strict'),
                              smokeActions=bool(options.get('smoke_actions')), safetyLevel=options.get('safety_level', 'strict'),
                              instanceSampleLimit=int(options.get('instance_sample_limit', 3) or 0),
                              login={'method': 'MANUAL' if options.get('manual_login') else 'TEST_ACCOUNT' if options.get('login') else 'NONE',
                                     'form': {key: value for key, value in (options.get('login') or {}).items()} or None,
                                     'credentialsStored': False},
                              scenarioIds=options.get('scenario_ids', []), conditions=options.get('conditions', []),
                              routeAliases=options.get('route_aliases', []), dataPolicy='INDEPENDENT_LIVE_WITH_CONFIGURED_MASKS'),
                coverage=dict(discoveredPages=len(a) + len(b) + len(a_skip) + len(b_skip),
                              deferredPages=len(a_skip) + len(b_skip), discoveredActions=len(actions),
                              executedActions=budget.completed, attemptedActions=budget.actions,
                              navigationTargetsVisited=sum(a.get('state') == 'URL_VISITED' for a in actions),
                              blockedActions=totals['blockedActions'],
                              blockedRequests=blocked_requests, incomplete=incomplete,
                              limitations=['No shadow DOM/canvas coverage', 'Iframes are inventory only',
                                           'Click dispatch without an assertion is REVIEW', 'Viewport capture only',
                                           'No direct database equality comparison',
                                           'Login redirects returning HTTP 200 are not automatically recognized',
                                           'API payload and business contracts are not inferred']))
