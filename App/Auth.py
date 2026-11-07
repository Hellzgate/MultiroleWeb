# -*- coding: utf-8 -*-
"""토큰 인증 + 로그인 페이지.

인증 방식(둘 중 하나면 통과):
    Cookie: mr_auth=<WEB_TOKEN>
    X-MR-Token: <WEB_TOKEN>          (curl / 스크립트용)

WEB_TOKEN 이 비어 있으면 인증 없이 동작한다(LAN 전용일 때만).
"""

import hmac

COOKIE_NAME = "mr_auth"
ERROR_MARK = "<!--ERR-->"

LOGIN_HTML = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>Multirole Web</title>
<style>body{background:#12141a;color:#e6e9ef;font-family:system-ui,'Malgun Gothic',sans-serif;display:flex;
min-height:100vh;align-items:center;justify-content:center;margin:0}
form{background:#1a1d26;padding:28px 32px;border-radius:12px;border:1px solid #2a2f3d;width:320px}
h1{font-size:17px;margin:0 0 16px}input{width:100%;padding:9px 10px;border-radius:8px;border:1px solid #333a4a;
background:#0e1016;color:#e6e9ef;font-size:14px;box-sizing:border-box}
button{margin-top:14px;width:100%;padding:10px;border:0;border-radius:8px;background:#3b82f6;color:#fff;
font-size:14px;cursor:pointer}p{color:#f87171;font-size:13px;margin:10px 0 0}</style>
<form method="post" action="/api/login"><h1>Multirole Web 접속</h1>
<input name="token" type="password" placeholder="WEB_TOKEN" autofocus>
<button type="submit">들어가기</button><p><!--ERR--></p></form></html>"""


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


def matches(given, expected):
    return bool(expected) and hmac.compare_digest(given, expected)


def login_page(error=""):
    return LOGIN_HTML.replace(ERROR_MARK, error)


def login_cookie_headers(token):
    return {
        "Set-Cookie": "%s=%s; Path=/; HttpOnly; SameSite=Lax" % (COOKIE_NAME, token),
        "Location": "/",
    }
