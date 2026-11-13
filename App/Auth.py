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
:root{color-scheme:dark;--bg:#0e1013;--bg2:#16191f;--bg3:#1e222a;--line:rgba(255,255,255,.08);
--line2:rgba(255,255,255,.16);--fg:#e8ebf0;--fg2:#aab2c0;--muted:#7f8795;--acc:#6fd3c3}
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
@media (prefers-color-scheme: light){
  :root{color-scheme:light;--bg:#f4f5f8;--bg2:#ffffff;--bg3:#f2f4f7;--line:rgba(16,20,28,.08);
  --line2:rgba(16,20,28,.16);--fg:#141821;--fg2:#525b6b;--muted:#7b8494;--acc:#0f766e}
  input{background:#f2f4f7}
  button{background:#0f766e;color:#fff}
  button:hover{background:#115e59}
  p.err{color:#b91c1c}
}
</style>"""

TOKEN_FORM = """<details><summary>토큰으로 들어가기 (비상용)</summary>
<form method="post" action="/api/login"><input name="token" type="password" placeholder="WEB_TOKEN">
<button type="submit">토큰 로그인</button></form></details>"""

LOGIN_HTML = """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="dark"><link rel="icon" type="image/png" href="data:image/png;base64,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"><link rel="shortcut icon" href="/favicon.ico?v=3">
<title>Multirole Web</title>""" + STYLE + """
<div class="wrap"><form method="post" action="/api/login"><h1>Multirole Web</h1>
<p class="sub">패널 관리자 계정으로 로그인</p>
<label for="id">아이디</label>
<input id="id" name="id" type="text" autofocus autocomplete="username">
<label for="pw">비밀번호</label>
<input id="pw" name="pw" type="password" autocomplete="current-password">
<button type="submit">로그인</button><p class="err"><!--ERR--></p></form>""" + TOKEN_FORM + """</div></html>"""

SETUP_HTML = """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="dark"><link rel="icon" type="image/png" href="data:image/png;base64,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"><link rel="shortcut icon" href="/favicon.ico?v=3">
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
