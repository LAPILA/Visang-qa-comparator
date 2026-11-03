"""Bounded read-only UI contracts. Configuration never contains executable code."""
from __future__ import annotations

import copy
import fnmatch
import re
from urllib.parse import urlsplit

from .policy import check

KINDS = frozenset({'visible', 'count', 'text_length', 'overflow', 'attribute'})
CASES = frozenset({'custom', 'long_title', 'empty', 'pagination'})
_ATTRIBUTE = re.compile(r'^(?:id|class|role|title|type|disabled|hidden|maxlength|aria-[a-z-]+|data-[a-z0-9-]+)$')
_PRIVATE_ATTRIBUTE = re.compile(r'password|passwd|token|secret|session|cookie|credential|auth|api.?key', re.I)
# Fixed, side-effect-free DOM measurement; caller JavaScript is never accepted.
_OVERFLOW = '(el) => ({x:el.scrollWidth>el.clientWidth+1,y:el.scrollHeight>el.clientHeight+1})'


def _text(value, label, maximum=500):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError(f'{label} must be nonempty text of at most {maximum} characters.')
    return value.strip()


def _validate_predicate(raw, precondition=False):
    if not isinstance(raw, dict):
        raise ValueError('A condition must be an object.')
    allowed = {'selector', 'kind', 'expected', 'attribute', 'unit'}
    if not precondition:
        allowed |= {'id', 'case', 'url_pattern', 'preconditions', 'label'}
    if set(raw) - allowed:
        raise ValueError('Unsupported condition fields; scripts, actions and request mocking are not supported.')
    item = copy.deepcopy(raw)
    item['selector'] = _text(raw.get('selector'), 'selector')
    kind = raw.get('kind')
    if kind not in KINDS:
        raise ValueError('Unsupported condition kind.')
    if raw.get('unit', 'codepoints') not in ('codepoints', 'utf16'):
        raise ValueError('text_length unit must be codepoints or utf16.')
    if 'unit' in raw and kind != 'text_length':
        raise ValueError('unit is only supported for text_length.')
    if kind == 'attribute':
        name = _text(raw.get('attribute'), 'attribute', 100)
        if not _ATTRIBUTE.fullmatch(name) or _PRIVATE_ATTRIBUTE.search(name):
            raise ValueError('Only nonsecret presentation attributes are supported.')
        item['attribute'] = name
    elif 'attribute' in raw:
        raise ValueError('attribute is only supported for an attribute condition.')
    if 'expected' not in raw:
        if precondition:
            raise ValueError('Preconditions require an explicit expected value.')
        return item
    expected = raw['expected']
    if kind in ('visible', 'overflow') and not isinstance(expected, bool):
        raise ValueError('visible/overflow expected must be a boolean.')
    if kind in ('count', 'text_length'):
        if not isinstance(expected, dict) or not expected or set(expected) - {'equals', 'min', 'max'}:
            raise ValueError('count/text_length expected requires equals, min or max.')
        for value in expected.values():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 1000000:
                raise ValueError('Numeric condition bounds must be nonnegative integers no larger than 1000000.')
        if expected.get('min', 0) > expected.get('max', 1000000):
            raise ValueError('Condition min cannot exceed max.')
        if 'equals' in expected and not expected.get('min', 0) <= expected['equals'] <= expected.get('max', 1000000):
            raise ValueError('equals must satisfy the specified bounds.')
    if kind == 'attribute' and not (isinstance(expected, str) or expected is None or
            (isinstance(expected, dict) and set(expected) == {'exists'} and isinstance(expected['exists'], bool))):
        raise ValueError('attribute expected must be text, null, or {exists: boolean}.')
    return item


def validate_conditions(raw):
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 30:
        raise ValueError('conditions must be an array of at most 30 entries.')
    result, identifiers = [], set()
    for raw_item in raw:
        item = _validate_predicate(raw_item)
        identifier = _text(item.get('id'), 'condition id', 100)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', identifier) or identifier in identifiers:
            raise ValueError('Condition IDs must be unique letters, digits, dots, underscores or hyphens.')
        item['id'] = identifier
        identifiers.add(identifier)
        case = item.get('case', 'custom')
        if case not in CASES:
            raise ValueError('Unsupported condition case.')
        item['case'] = case
        if 'url_pattern' in item:
            item['url_pattern'] = _text(item['url_pattern'], 'url_pattern', 2000)
        if 'label' in item:
            item['label'] = _text(item['label'], 'label', 200)
        prerequisites = item.get('preconditions', [])
        if not isinstance(prerequisites, list) or len(prerequisites) > 10:
            raise ValueError('At most 10 preconditions are supported.')
        if case != 'custom' and not prerequisites:
            raise ValueError('long_title, empty and pagination require explicit data preconditions.')
        item['preconditions'] = [_validate_predicate(value, True) for value in prerequisites]
        result.append(item)
    return result


class _MissingTarget(Exception):
    pass


class _AmbiguousTarget(Exception):
    pass


def _measure(page, predicate, timeout):
    locator = page.locator(predicate['selector'])
    count = locator.count()  # Invalid selectors raise, rather than becoming absent.
    kind = predicate['kind']
    if kind == 'count':
        return count
    if kind == 'visible' and count == 0:
        return False
    if count == 0:
        raise _MissingTarget()
    if count != 1:
        raise _AmbiguousTarget()
    if kind == 'visible':
        return locator.is_visible(timeout=timeout)
    if kind == 'attribute':
        return locator.get_attribute(predicate['attribute'], timeout=timeout)
    if kind == 'text_length':
        text = locator.inner_text(timeout=timeout)
        return len(text.encode('utf-16-le')) // 2 if predicate.get('unit') == 'utf16' else len(text)
    if kind == 'overflow':
        measured = locator.evaluate(_OVERFLOW, timeout=timeout)
        return bool(measured['x'] or measured['y'])
    raise ValueError('Unknown predicate')


def _satisfies(actual, predicate):
    expected = predicate['expected']
    if predicate['kind'] in ('count', 'text_length'):
        return (('equals' not in expected or actual == expected['equals']) and
                ('min' not in expected or actual >= expected['min']) and
                ('max' not in expected or actual <= expected['max']))
    if predicate['kind'] == 'attribute' and isinstance(expected, dict):
        return (actual is not None) == expected['exists']
    return actual == expected


def run_condition_checks(page, conditions, environment, options, cancelled):
    """Evaluate only the supplied contracts on the current document; no navigation."""
    result = []
    timeout = max(100, min(int(options.get('condition_timeout_ms', 3000)), 10000))
    validated = validate_conditions(conditions)
    for item in validated:
        cid = 'condition.' + item['id']
        def output(status, reason, actual=None, category='STRUCTURE', subtype=None):
            value = check(cid, status, reason, expected=item.get('expected'), actual=actual,
                          scenario_id='conditions', step_id=item['id'], required=True)
            value.update(environment=environment, category=category, subtype=subtype or reason,
                         condition_id=item['id'], executed=status in ('PASS', 'FAIL'),
                         preconditions=copy.deepcopy(item['preconditions']))
            result.append(value)
        if cancelled():
            output('BLOCKED', 'CANCELLED', category='TEST_INFRA')
            continue
        pattern = item.get('url_pattern')
        if pattern and not (fnmatch.fnmatchcase(page.url, pattern) or fnmatch.fnmatchcase(urlsplit(page.url).path, pattern)):
            output('SKIP', 'CONDITION_OUT_OF_SCOPE', category='TEST_INFRA')
            continue
        try:
            blocked = False
            for prerequisite in item['preconditions']:
                if cancelled():
                    output('BLOCKED', 'CANCELLED', category='TEST_INFRA')
                    blocked = True
                    break
                try:
                    measured = _measure(page, prerequisite, timeout)
                    satisfied = _satisfies(measured, prerequisite)
                except _MissingTarget:
                    measured, satisfied = None, False
                if not satisfied:
                    output('BLOCKED', 'CONDITION_PRECONDITION_UNMET',
                           {'precondition': prerequisite, 'measured': measured}, 'DATA', 'INSUFFICIENT_DATA')
                    blocked = True
                    break
            if blocked:
                continue
            if 'expected' not in item:
                output('REVIEW', 'CONDITION_EXPECTATION_MISSING', category='TEST_INFRA', subtype='EXPECTATION_UNDEFINED')
                continue
            measured = _measure(page, item, timeout)
            satisfied = _satisfies(measured, item)
            category, subtype = {
                'visible': ('STRUCTURE', 'VISIBILITY_MISMATCH'),
                'count': ('STRUCTURE', 'ELEMENT_COUNT_MISMATCH'),
                'text_length': ('FUNCTIONAL', 'VALIDATION_MISMATCH'),
                'overflow': ('VISUAL', 'TEXT_OVERFLOW'),
                'attribute': ('STRUCTURE', 'ATTRIBUTE_MISMATCH'),
            }[item['kind']]
            output('PASS' if satisfied else 'FAIL', 'CONDITION_SATISFIED' if satisfied else 'CONDITION_MISMATCH',
                   measured, category, subtype)
        except _MissingTarget:
            output('FAIL', 'CONDITION_TARGET_MISSING', 0, 'STRUCTURE', 'REQUIRED_ELEMENT_MISSING')
        except _AmbiguousTarget:
            output('ERROR', 'CONDITION_TARGET_AMBIGUOUS', category='TEST_INFRA', subtype='AMBIGUOUS_SELECTOR')
        except Exception as exc:
            output('ERROR', 'CONDITION_EVALUATION_ERROR', {'exceptionType': type(exc).__name__},
                   'TEST_INFRA', 'CONDITION_EVALUATION_FAILED')
    return result
