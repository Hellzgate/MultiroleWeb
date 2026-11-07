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

STYLE = """<style>body{background:#12141a;color:#e6e9ef;font-family:system-ui,'Malgun Gothic',sans-serif;display:flex;
min-height:100vh;align-items:center;justify-content:center;margin:0}
form{background:#1a1d26;padding:28px 32px;border-radius:12px;border:1px solid #2a2f3d;width:340px}
h1{font-size:17px;margin:0 0 6px}.sub{color:#8b93a7;font-size:12px;margin:0 0 16px}
input{width:100%;padding:9px 10px;border-radius:8px;border:1px solid #333a4a;
background:#0e1016;color:#e6e9ef;font-size:14px;box-sizing:border-box;margin-bottom:8px}
button{margin-top:10px;width:100%;padding:10px;border:0;border-radius:8px;background:#3b82f6;color:#fff;
font-size:14px;cursor:pointer}p{color:#f87171;font-size:13px;margin:10px 0 0}
details{margin-top:14px;font-size:12px;color:#8b93a7}summary{cursor:pointer}</style>"""

TOKEN_FORM = """<details><summary>토큰으로 들어가기(비상용)</summary>
<form method="post" action="/api/login"><input name="token" type="password" placeholder="WEB_TOKEN">
<button type="submit">토큰 로그인</button></form></details>"""

LOGIN_HTML = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>Multirole Web</title>""" + STYLE + """
<form method="post" action="/api/login"><h1>Multirole Web 접속</h1>
<p class="sub">패널 관리자 계정으로 로그인하세요.</p>
<input name="id" type="text" placeholder="아이디" autofocus autocomplete="username">
<input name="pw" type="password" placeholder="비밀번호" autocomplete="current-password">
<button type="submit">로그인</button><p><!--ERR--></p></form>""" + TOKEN_FORM + """</html>"""

SETUP_HTML = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>Multirole Web — 패널 관리자 계정 만들기</title>""" + STYLE + """
<form method="post" action="/api/setup"><h1>패널 관리자 계정 만들기</h1>
<p class="sub">처음 한 번만 설정하고, 이후 이 계정으로 로그인합니다.<br>
비밀번호는 <b>해시로만</b> 저장되며, 아래 <b>다시 입력</b>과 같아야 합니다.</p>
<input name="id" type="text" placeholder="아이디 (예: admin)" autofocus autocomplete="username">
<input name="pw" type="password" placeholder="비밀번호 (4자 이상)" autocomplete="new-password">
<input name="pw2" type="password" placeholder="비밀번호 다시 입력" autocomplete="new-password">
<button type="submit">만들고 시작하기</button><p><!--ERR--></p></form></html>"""


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


def login_cookie_headers(token):
    return {
        "Set-Cookie": "%s=%s; Path=/; HttpOnly; SameSite=Lax" % (COOKIE_NAME, token),
        "Location": "/",
    }


def session_cookie_headers(value, max_age=None):
    extra = ""
    if max_age:
        extra = "; Max-Age=%d" % int(max_age)
    return {
        "Set-Cookie": "%s=%s; Path=/; HttpOnly; SameSite=Lax%s" % (SESSION_COOKIE, value, extra),
        "Location": "/",
    }


def clear_cookie_headers():
    return {
        "Set-Cookie": "%s=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax" % SESSION_COOKIE,
        "Location": "/",
    }
