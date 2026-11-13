# -*- coding: utf-8 -*-
"""인증 — ①패널 관리자 계정(세션 쿠키) ②비상용 WEB_TOKEN.

    Cookie: mr_session=<id>.<만료>.<HMAC>     (계정 로그인)
    Cookie: mr_auth=<WEB_TOKEN>               (비상용)
    Header: X-MR-Token: <WEB_TOKEN>           (curl / 스크립트)

`MR_AUTH` = both(기본) | account | token
    both    계정이 있으면 계정 로그인, 토큰도 허용
    account 계정만 (토큰 비활성)
    token   기존 토큰만
WEB_TOKEN 이 비어 있고 계정도 없으면 인증 없이 동작한다(LAN 전용일 때만).
"""

import hmac

from .AuthStore import COOKIE as SESSION_COOKIE

COOKIE_NAME = "mr_auth"
ERROR_MARK = "<!--ERR-->"

STYLE = """<style>
:root{--bg:#0e1013;--bg2:#15181d;--bg3:#1b1f26;--line:rgba(255,255,255,.07);
--line2:rgba(255,255,255,.14);--fg:#e8ebf0;--fg2:#a6aebc;--muted:#737b8a;--acc:#6fd3c3}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);margin:0;min-height:100vh;
display:flex;align-items:center;justify-content:center;padding:24px;
font:14px/1.5 system-ui,'Malgun Gothic','Apple SD Gothic Neo',sans-serif}
.wrap{width:100%;max-width:380px}
h1{font-size:17px;font-weight:600;margin:0 0 6px}
.sub{color:var(--muted);font-size:12.5px;margin:0 0 20px;line-height:1.6}
form{background:var(--bg2);border:1px solid var(--line2);border-radius:14px;padding:24px}
label{display:block;font-size:12px;color:var(--fg2);margin:0 0 6px}
input{width:100%;padding:9px 10px;border-radius:8px;border:1px solid var(--line2);
background:#0b0d11;color:var(--fg);font:inherit;font-size:13px;margin-bottom:12px}
input:focus{outline:2px solid var(--acc);outline-offset:1px;border-color:transparent}
button{margin-top:4px;width:100%;padding:10px;border:0;border-radius:8px;
background:#e8ebf0;color:#12151a;font:600 13px inherit;cursor:pointer}
button:hover{background:#fff}
button:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
p.err{color:#ef8f8f;font-size:12.5px;margin:10px 0 0}
details{margin-top:16px;border-top:1px solid var(--line);padding-top:12px}
summary{cursor:pointer;color:var(--muted);font-size:12.5px;list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"›";margin-right:6px;color:var(--muted)}
details[open] summary::before{content:"⌄"}
details form{background:transparent;border:0;padding:12px 0 0}
</style>"""

TOKEN_FORM = """<details><summary>토큰으로 들어가기 (비상용)</summary>
<form method="post" action="/api/login"><input name="token" type="password" placeholder="WEB_TOKEN">
<button type="submit">토큰 로그인</button></form></details>"""

LOGIN_HTML = """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Multirole Web</title>""" + STYLE + """
<div class="wrap"><form method="post" action="/api/login"><h1>Multirole Web</h1>
<p class="sub">패널 관리자 계정으로 로그인</p>
<label for="id">아이디</label>
<input id="id" name="id" type="text" autofocus autocomplete="username">
<label for="pw">비밀번호</label>
<input id="pw" name="pw" type="password" autocomplete="current-password">
<button type="submit">로그인</button><p class="err"><!--ERR--></p></form>""" + TOKEN_FORM + """</div></html>"""

SETUP_HTML = """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Multirole Web — 패널 관리자 계정 만들기</title>""" + STYLE + """
<div class="wrap"><form method="post" action="/api/setup"><h1>패널 관리자 계정 만들기</h1>
<p class="sub">처음 한 번만 설정하고, 이후 이 계정으로 로그인합니다. 비밀번호는 해시로만 저장됩니다.</p>
<label for="id">아이디</label>
<input id="id" name="id" type="text" placeholder="admin" autofocus autocomplete="username">
<label for="pw">비밀번호</label>
<input id="pw" name="pw" type="password" placeholder="4자 이상" autocomplete="new-password">
<label for="pw2">비밀번호 다시 입력</label>
<input id="pw2" name="pw2" type="password" autocomplete="new-password">
<button type="submit">만들고 시작하기</button><p class="err"><!--ERR--></p></form></div></html>"""


def token_ok(headers, expected):
    """헤더(Cookie/X-MR-Token)에 유효한 토큰이 있는지."""
    if not expected:
        return True
    cookie = headers.get("Cookie") or ""
    for part in cookie.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() == COOKIE_NAME and hmac.compare_digest(v.strip(), expected):
                return True
    tok = headers.get("X-MR-Token") or ""
    return bool(tok) and hmac.compare_digest(tok, expected)


def cookie_value(headers, name):
    for part in (headers.get("Cookie") or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() == name:
                return v.strip()
    return ""


def matches(given, expected):
    return bool(expected) and hmac.compare_digest(given, expected)


def login_page(error=""):
    return LOGIN_HTML.replace(ERROR_MARK, error)


def setup_page(error=""):
    return SETUP_HTML.replace(ERROR_MARK, error)


def login_cookie_headers(token, secure=False):
    return {
        "Set-Cookie": "%s=%s; Path=/; HttpOnly; SameSite=Lax%s"
                      % (COOKIE_NAME, token, "; Secure" if secure else ""),
        "Location": "/",
    }


def session_cookie_headers(value, max_age=None, secure=False):
    extra = ""
    if max_age:
        extra = "; Max-Age=%d" % int(max_age)
    if secure:
        extra += "; Secure"          # HTTPS(역방향 프록시)일 때만 — HTTP 직접 접속도 계속 동작하게
    return {
        "Set-Cookie": "%s=%s; Path=/; HttpOnly; SameSite=Lax%s" % (SESSION_COOKIE, value, extra),
        "Location": "/",
    }


def clear_cookie_headers(secure=False):
    return {
        "Set-Cookie": "%s=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax%s"
                      % (SESSION_COOKIE, "; Secure" if secure else ""),
        "Location": "/",
    }
