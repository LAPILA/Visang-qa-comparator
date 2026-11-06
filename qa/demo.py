"""Local, synthetic comparison targets. No company source or data is used."""

from __future__ import annotations

import html
import json
import threading
from urllib.parse import parse_qs, urlencode, urlsplit

DEMO_MARKER = "web-qa-comparator-v1"
_COUNTER_LOCK = threading.Lock()
_MUTATIONS = {"a": {"save": 0, "delete": 0}, "b": {"save": 0, "delete": 0}}
_NOTICE_DATA = {
    "a": [("a-101", "Synthetic autumn classroom update"), ("a-102", "Synthetic reading guide")],
    "b": [("b-701", "Synthetic spring classroom update"), ("b-702", "Synthetic science guide")],
}


def reset_demo_counts():
    """Reset only in-process synthetic counters; intended for local test setup."""
    with _COUNTER_LOCK:
        for counts in _MUTATIONS.values():
            counts.update(save=0, delete=0)


def get_demo_summary():
    with _COUNTER_LOCK:
        counts = {side: dict(values) for side, values in _MUTATIONS.items()}
    return {
        "demo_marker": DEMO_MARKER,
        "synthetic": True,
        "network_dependencies": [],
        "mutation_counts": counts,
        "ground_truth": [
            {"id": "demo.missing-help-action", "environment": "b", "label": "DEFECT",
             "selector": "#required-action", "scope": "shared-header",
             "description": "The candidate omits the required help action on every page."},
            {"id": "demo.notice-content", "label": "EXPECTED_DIFFERENCE",
             "selector": "[data-qa-dynamic]",
             "description": "Each environment has its own synthetic notice IDs and titles."},
            {"id": "demo.route-alias", "label": "EXPECTED_DIFFERENCE",
             "description": "Candidate feature routes use .do; baseline routes do not."},
            {"id": "demo.mutation-trap", "label": "SAFETY_ASSERTION",
             "expected_mutation_count": 0},
        ],
    }


def _route(side, feature="", **query):
    path = "/demo/" + side + "/" + feature
    if feature and side == "b":
        path += ".do"
    return path + ("?" + urlencode(query) if query else "")


def demo_profile(base_origin):
    """Return an explicit profile for the two loopback-hosted demo targets."""
    parsed = urlsplit(base_origin)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("The synthetic demo profile requires a loopback HTTP(S) origin.")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    aliases = [
        {"baseline": _route("a", feature), "candidate": _route("b", feature), "page_class": page_class}
        for feature, page_class in [("", "home"), ("search", "search.results"),
                                    ("notice", "notice.list"), ("detail", "notice.detail"),
                                    ("input", "input.boundary")]
    ]
    return {
        "id": "synthetic-demo",
        "name": "Local synthetic A/B demo",
        "baselineUrl": origin + _route("a"),
        "candidateUrl": origin + _route("b"),
        "options": {
            "profile_id": "synthetic-demo",
            "scenario_ids": ["demo.search", "demo.input_length", "demo.history"],
            "route_aliases": aliases,
            "allowed_paths": [entry[side] for entry in aliases for side in ("baseline", "candidate")],
            "regions": [
                {"id": "navigation", "selector": "#site-nav", "required": True, "mask_selectors": []},
                {"id": "main", "selector": "#main-content", "required": True,
                 "mask_selectors": ["[data-qa-dynamic]"]},
                {"id": "required-help", "selector": "#required-action", "required": True,
                 "mask_selectors": []},
            ],
            "safe_actions": [{"id": "demo.show-panel", "selector": "#safe-toggle", "kind": "click"}],
            "max_pages": 10,
            "max_depth": 2,
            "max_actions": 80,
            "timeout_seconds": 120,
        },
    }


_CSS = """
*{box-sizing:border-box}body{margin:0;background:#f4f6fb;color:#202a40;font:16px Arial,sans-serif}
header,main,footer{max-width:900px;margin:auto;padding:24px}header{background:white;border-bottom:1px solid #dce2ed}
nav{display:flex;gap:18px;flex-wrap:wrap;min-height:28px}a{color:#2458b3}h1{font-size:28px;margin:0 0 16px}
h2{font-size:20px}section{background:white;padding:22px;margin-bottom:20px;border:1px solid #dce2ed;border-radius:10px}
label{display:block;margin-bottom:8px}input{padding:10px;border:1px solid #8090ab;border-radius:4px;font:inherit}
button{padding:10px 16px;font:inherit;border:1px solid #2458b3;border-radius:4px;background:#eaf1ff;color:#173f81;cursor:pointer}
li{margin:10px 0}.subtle{color:#566177;font-size:14px}.trap{margin-top:18px;border:1px dashed #aa4560;padding:12px}
.trap form{display:inline-block;margin:5px}#required-action{display:inline-block;margin:12px 0}#safe-panel{padding:12px;background:#edf5f0}
"""


_LOGIN_FORM = ("<section id=\"login-section\"><h2>Test account sign-in</h2>"
               "<form id=\"login-form\" method=\"post\" action=\"{action}\">"
               "<label for=\"login-id\">Account</label><input id=\"login-id\" name=\"id\" type=\"text\" autocomplete=\"off\">"
               "<label for=\"login-pw\">Password</label><input id=\"login-pw\" name=\"pw\" type=\"password\" autocomplete=\"off\">"
               "<button id=\"login-submit\" type=\"submit\">Sign in</button></form>{error}"
               "<p class=\"subtle\">Synthetic fixture: any account whose password is <code>demo-pass</code> signs in.</p></section>")


def _cover_page(side):
    """Landing gate like a legacy mobile SPA's /#/coverPage: a click reveals the real home."""
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>Cover | Synthetic QA demo</title>'
            f'<style>{_CSS}</style></head><body data-qa-demo="{DEMO_MARKER}" data-qa-environment="{side}" data-qa-feature="cover">'
            f'<main id="main-content"><h1>앱 설치 안내</h1><section id="cover-gate"><p>앱에서 더 편하게 이용하세요.</p>'
            f'<button id="enter-mobile-web" type="button">모바일 웹으로 이동하기</button></section></main>'
            f'<script>document.getElementById("enter-mobile-web").addEventListener("click", () => {{ location.href = "/demo/{side}/"; }});</script>'
            f'</body></html>')


def _login_page(side, error=False):
    body = _LOGIN_FORM.format(action=f"/demo/{side}/login",
                              error='<p id="login-error" role="alert">Invalid account or password.</p>' if error else '')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Sign in | Synthetic QA demo</title>'
            f'<style>{_CSS}</style></head><body data-qa-demo="{DEMO_MARKER}" data-qa-environment="{side}" '
            f'data-qa-feature="login"><main id="main-content"><h1>Sign in</h1>{body}</main></body></html>')


def _page(side, feature, query, signed_in=None):
    esc = html.escape
    title = {"": "Home", "search": "Search", "notice": "Notices", "detail": "Notice detail", "input": "Input length",
             "mypage": "My page"}[feature]
    links = "".join(f'<a href="{_route(side, route)}">{label}</a>' for route, label in
                    [("", "Home"), ("search", "Search"), ("notice", "Notices"), ("input", "Input length")])
    required = '<button id="required-action" type="button">Help</button>' if side == "a" else ""
    notices = _NOTICE_DATA[side]
    notice_list = "".join(
        f'<li><a data-testid="notice-link" data-qa-dynamic href="{_route(side, "detail", id=item_id)}">{esc(text)}</a></li>'
        for item_id, text in notices
    )
    if feature == "":
        popup = ('<div id="demo-popup" class="layer-popup" role="dialog" style="position:fixed;left:10%;top:10%;width:80%;height:50%;background:#fff;border:2px solid #aa4560;z-index:50;padding:20px">'
                 '<h2>오늘의 공지</h2><p>Synthetic marketing popup shown only with ?popup=1.</p>'
                 '<button id="demo-popup-close" type="button">오늘 하루 보지 않기</button></div>') if query.get("popup", [""])[0] == "1" else ""
        members = (f'<section id="members"><h2>Members</h2><a id="mypage-link" href="{_route(side, "mypage")}">My page</a></section>'
                   if query.get("members", [""])[0] == "1" else "")
        body = (popup + members + f'<section id="home-notice"><h2>Notices</h2><ul>{notice_list}</ul></section>'
                '<section><h2>Safe interface state</h2><button id="safe-toggle" type="button" aria-expanded="false" '
                'aria-controls="safe-panel">Show details</button><div id="safe-panel" hidden>Deterministic local panel.</div></section>'
                f'<section class="trap" data-qa-risk="mutation"><h2>Safety traps — do not execute</h2>'
                f'<a href="/demo/{side}/unsafe/delete" data-qa-risk="mutation">Delete synthetic record</a>'
                + "".join(f'<form method="post" action="/demo/{side}/unsafe/{action}" data-qa-risk="mutation">'
                          f'<button type="submit">{action.title()} synthetic record</button></form>' for action in ("save", "delete"))
                + '</section>')
    elif feature == "notice":
        body = f'<section><h2>Available notices</h2><ul id="notice-list">{notice_list}</ul></section>'
    elif feature == "detail":
        item_id = query.get("id", [""])[0]
        item = next((text for key, text in notices if key == item_id), None)
        if item is None:
            body = '<section id="notice-not-found"><h2>Notice not found</h2></section>'
        else:
            body = f'<section><h2 id="notice-title" data-qa-dynamic>{esc(item)}</h2><p data-qa-dynamic>Local notice ID: {esc(item_id)}</p></section>'
        body += f'<a id="notice-list-link" href="{_route(side, "notice")}">Back to notices</a>'
    elif feature == "mypage":
        body = f'<section id="mypage"><h2>Members only</h2><p data-qa-dynamic>Signed in as {esc(signed_in or "")}</p></section>'
    elif feature == "search":
        keyword = query.get("q", [""])[0][:200]
        results = [text for text in ("Synthetic mathematics lesson", "Synthetic reading lesson") if keyword.strip() and keyword.casefold() in text.casefold()]
        result_markup = "".join(f'<li>{esc(text)}</li>' for text in results)
        body = (f'<section><form id="search-form" method="get" action="{_route(side, "search")}">'
                '<label for="search-input">Search keyword</label>'
                f'<input id="search-input" name="q" type="search" value="{esc(keyword, quote=True)}" maxlength="200"> '
                '<button id="search-submit" type="submit">Search</button></form></section>'
                f'<section id="search-results" data-result-count="{len(results)}"><h2>Search results</h2>'
                f'<p id="search-keyword">{esc(keyword)}</p><ul>{result_markup}</ul>'
                + ('' if results else '<p id="search-empty">No results</p>') + '</section>')
    else:
        body = ('<section><label for="limited-input">At most 10 UTF-16 code units</label>'
                '<input id="limited-input" type="text" maxlength="10" autocomplete="off">'
                '<p>Length: <output id="input-count">0</output> / 10</p>'
                '<p class="subtle">This synthetic limit is a fixture contract, not a live product requirement.</p></section>')
    session = f'<p id="session-state" data-qa-dynamic>Signed in as {esc(signed_in)}</p>' if signed_in else ''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} | Synthetic QA demo</title><style>{_CSS}</style></head>
<body data-qa-demo="{DEMO_MARKER}" data-qa-environment="{side}" data-qa-feature="{feature or 'home'}">
<header><p class="subtle">Local synthetic QA fixture</p><nav id="site-nav" aria-label="Main">{links}</nav>{required}{session}</header>
<main id="main-content"><h1>{title}</h1>{body}</main><footer class="subtle">Synthetic fixture. No external requests or production data. <a id="hidden-login-link" href="/demo/{side}/login" hidden>Sign in</a></footer>
<script>
const toggle = document.getElementById('safe-toggle');
if(toggle) toggle.addEventListener('click', () => {{ const panel = document.getElementById('safe-panel'); panel.hidden = !panel.hidden; toggle.setAttribute('aria-expanded', String(!panel.hidden)); }});
const popupClose = document.getElementById('demo-popup-close');
if(popupClose) popupClose.addEventListener('click', () => {{ document.getElementById('demo-popup').remove(); }});
const field = document.getElementById('limited-input');
if(field) field.addEventListener('input', () => {{ document.getElementById('input-count').textContent = String(field.value.length); }});
</script></body></html>'''


def _respond(handler, status, body, content_type="application/json; charset=utf-8"):
    if not isinstance(body, bytes):
        body = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Connection", "close")
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(body)
    handler.close_connection = True


def handle_demo(handler, path):
    """Handle /demo/* routes on the existing HTTP server, returning ownership."""
    parsed = urlsplit(handler.path)
    actual_path = parsed.path
    if not actual_path.startswith("/demo/"):
        return False
    method = handler.command.upper()
    if actual_path == "/demo/meta":
        _respond(handler, 200 if method in {"GET", "HEAD"} else 405,
                 json.dumps(get_demo_summary() if method in {"GET", "HEAD"} else {"error": "method_not_allowed"}))
        return True
    parts = actual_path.strip("/").split("/")
    if len(parts) < 2 or parts[1] not in {"a", "b"}:
        _respond(handler, 404, '{"error":"demo_route_not_found"}')
        return True
    side = parts[1]
    if len(parts) == 4 and parts[2] == "unsafe" and parts[3] in {"save", "delete"}:
        action = parts[3]
        if method in {"GET", "POST"}:
            with _COUNTER_LOCK:
                _MUTATIONS[side][action] += 1
            _respond(handler, 200, json.dumps({"synthetic_trap_triggered": True, "action": action}))
        else:
            _respond(handler, 405, '{"error":"method_not_allowed"}')
        return True
    if len(parts) == 3 and parts[2] == "cover":
        if method in {"GET", "HEAD"}:
            _respond(handler, 200, _cover_page(side), "text/html; charset=utf-8")
        else:
            _respond(handler, 405, '{"error":"method_not_allowed"}')
        return True
    if len(parts) == 3 and parts[2] == "login":
        if method in {"GET", "HEAD"}:
            _respond(handler, 200, _login_page(side), "text/html; charset=utf-8")
        elif method == "POST":
            length = int(handler.headers.get("Content-Length") or 0)
            form = parse_qs(handler.rfile.read(min(length, 4096)).decode("utf-8", "replace"), keep_blank_values=True)
            account, password = form.get("id", [""])[0][:50], form.get("pw", [""])[0]
            if account and password == "demo-pass":
                handler.send_response(303)
                handler.send_header("Location", f"/demo/{side}/")
                handler.send_header("Set-Cookie", f"demo_session_{side}={html.escape(account, quote=True)}; Path=/demo/{side}/; HttpOnly; SameSite=Lax")
                handler.send_header("Content-Length", "0")
                handler.send_header("Connection", "close")
                handler.end_headers()
                handler.close_connection = True
            else:
                _respond(handler, 200, _login_page(side, error=True), "text/html; charset=utf-8")
        else:
            _respond(handler, 405, '{"error":"method_not_allowed"}')
        return True
    if method not in {"GET", "HEAD"}:
        _respond(handler, 405, '{"error":"method_not_allowed"}')
        return True
    feature = parts[2] if len(parts) == 3 else "" if len(parts) == 2 else None
    if side == "b" and feature and feature.endswith(".do"):
        feature = feature[:-3]
    elif side == "b" and feature:
        feature = None
    if feature not in {"", "search", "notice", "detail", "input", "mypage"}:
        _respond(handler, 404, '{"error":"demo_route_not_found"}')
        return True
    cookies = {}
    for chunk in (handler.headers.get("Cookie") or "").split(";"):
        name, _, value = chunk.strip().partition("=")
        if name:
            cookies[name] = value
    if feature == "mypage" and not cookies.get(f"demo_session_{side}"):
        # Members-only fixture: anonymous visitors bounce to the sign-in page, like the real sites.
        handler.send_response(302)
        handler.send_header("Location", f"/demo/{side}/login")
        handler.send_header("Content-Length", "0")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.close_connection = True
        return True
    _respond(handler, 200, _page(side, feature, parse_qs(parsed.query, keep_blank_values=True),
                                 signed_in=cookies.get(f"demo_session_{side}") or None),
             "text/html; charset=utf-8")
    return True
