# -*- coding: utf-8 -*-
"""HTTP 라우팅 (API + 정적 파일).

정적 파일은 Web/ 폴더만, 확장자 화이트리스트(.html/.css/.js/.svg/.png)만 허용하고
realpath 로 폴더 이탈을 막는다. 나머지 경로는 /api/* 라우터로 보낸다.
"""

import json
import os
import ssl
import re
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import VERSION, WEB_DIR
from .Auth import (clear_cookie_headers, cookie_value, login_cookie_headers, login_page,
                   matches, session_cookie_headers, setup_page, token_ok)
from .AuthStore import COOKIE as SESSION_COOKIE, SESSION_TTL
from .ConfigSchema import KEY_DOCS, is_int, validate
from . import Bots
from .ConfigStore import ConfigError, load_config, save_config
from .Context import CTX
from .GitSync import SyncState, sync_all
from .Status import collect_ping, collect_status
from .SysInfo import client_counts, file_sha256

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}

# 상태 탭은 디렉터리를 훑기 때문에 5초 캐시를 둔다(헤더는 /api/ping 사용).
_STATUS_TTL = 5.0
_status_cache = {"at": 0.0, "value": None}


class PanelServer(ThreadingHTTPServer):
    """listen backlog 를 넉넉히 준다.

    기본값(socketserver.TCPServer.request_queue_size = 5)은 브라우저가 JS/CSS 를
    동시에 여러 개 받을 때 금방 차서 연결이 거부되고, 로컬 HTTP 프록시(AdGuard 등)가
    그것을 **502 Bad Gateway** 로 바꿔 보고한다(실측: 파일마다 매번 다른 1~2개가 502).
    """

    daemon_threads = True
    request_queue_size = 256
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    server_version = "MultiroleWeb/" + VERSION
    protocol_version = "HTTP/1.1"

    # -- 공통 ------------------------------------------------------------- #
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # 클라이언트/로컬 프록시가 먼저 끊은 경우 — 정상적인 상황이라 조용히 넘긴다
            self.close_connection = True

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _read_body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return b""
        return self.rfile.read(n)

    @property
    def app(self):
        return CTX.get()

    def _client_ip(self):
        """실제 클라이언트 IP. DSM 역방향 프록시 뒤(피어=127.0.0.1)면 X-Forwarded-For 첫 값."""
        peer = self.client_address[0] if self.client_address else "?"
        if peer in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            xff = self.headers.get("X-Forwarded-For") or ""
            first = xff.split(",")[0].strip()
            if first:
                return first
        return peer

    def _is_secure(self):
        """HTTPS 로 들어왔는지(TLS 직접 또는 프록시의 X-Forwarded-Proto)."""
        try:
            if isinstance(self.connection, ssl.SSLSocket):
                return True
        except Exception:                  # noqa: BLE001
            pass
        return (self.headers.get("X-Forwarded-Proto") or "").strip().lower() == "https"

    def _authed(self):
        """①세션 쿠키(관리자 계정) ②비상용 토큰. MR_AUTH 로 모드 결정."""
        st = self.app.st
        mode = getattr(st, "auth_mode", "both")
        auth = self.app.auth
        if mode == "token":
            return token_ok(self.headers, st.token)          # 토큰 없으면 통과(기존 동작)
        if st.token and token_ok(self.headers, st.token):
            return True
        has_account = bool(auth and auth.exists())
        if mode in ("both", "account") and has_account:
            if auth.verify_session(cookie_value(self.headers, SESSION_COOKIE)):
                return True
        if mode != "account" and not st.token and not has_account:
            return True                                       # 인증 미설정(LAN 전용)
        return False

    def _guard(self):
        if self._authed():
            return True
        self._json({"error": "unauthorized", "login": True}, 401)
        return False

    # -- 정적 파일 -------------------------------------------------------- #
    def _serve_static(self, rel):
        safe = os.path.normpath(rel).replace("\\", "/")
        if safe.startswith("../") or safe.startswith("/"):
            return False
        ext = os.path.splitext(safe)[1].lower()
        if ext not in STATIC_TYPES:
            return False
        full = os.path.realpath(os.path.join(WEB_DIR, safe))
        if not full.startswith(os.path.realpath(WEB_DIR) + os.sep):
            return False
        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            return False
        self._send(200, data, STATIC_TYPES[ext])
        return True

    # -- 메서드 ----------------------------------------------------------- #
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            self.route_get()
        except Exception as exc:  # noqa: BLE001 - 패널이 죽지 않게
            self._log("GET %s failed: %r" % (self.path, exc))
            self._json({"error": str(exc)}, 500)

    def do_POST(self):
        try:
            self.route_post()
        except Exception as exc:  # noqa: BLE001
            self._log("POST %s failed: %r" % (self.path, exc))
            self._json({"error": str(exc)}, 500)

    def do_PUT(self):
        try:
            self.route_put()
        except Exception as exc:  # noqa: BLE001
            self._log("PUT %s failed: %r" % (self.path, exc))
            self._json({"error": str(exc)}, 500)

    def _log(self, text):
        app = self.app
        if app is not None:
            app.sup.log("[webui] " + text)

    # -- GET -------------------------------------------------------------- #
    def route_get(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/api/health":
            self._json({"ok": True, "version": VERSION})
            return

        if path in ("/", "/index.html"):
            if not self._authed():
                st = self.app.st
                need_setup = (getattr(st, "auth_mode", "both") != "token"
                              and self.app.auth is not None and not self.app.auth.exists())
                self._send(200, setup_page() if need_setup else login_page(),
                           "text/html; charset=utf-8")
                return
            if qs.get("raw"):
                if not self._serve_static("index.html"):
                    self._send(500, "<h1>Web/index.html missing</h1>", STATIC_TYPES[".html"])
                return
            page = render_index()
            if page is None:
                self._send(500, "<h1>Web/index.html missing</h1>", STATIC_TYPES[".html"])
                return
            self._send(200, page, "text/html; charset=utf-8")
            return

        if path == "/favicon.ico":
            self._send(204)
            return

        # css/js 는 인증 없이 (로그인 페이지도 같은 스타일을 쓸 수 있게)
        if path.startswith("/js/") or path in ("/app.css",):
            if not self._serve_static(path.lstrip("/")):
                self._send(404, "not found", "text/plain; charset=utf-8")
            return

        if not self._guard():
            return

        if path == "/api/config":
            try:
                cfg = load_config(self.app.st)
            except ConfigError as exc:
                self._json({"error": exc.errors, "docs": KEY_DOCS}, 422)
                return
            errors, warnings = validate(cfg)
            real = self.app.st.real_config()
            sup = self.app.sup
            self._json(
                {
                    "config": cfg,
                    "errors": errors,
                    "warnings": warnings,
                    "docs": KEY_DOCS,
                    "path": real,
                    "pendingRestart": bool(
                        sup.is_running() and sup.running_hash and sup.running_hash != file_sha256(real)
                    ),
                }
            )
            return

        if path == "/api/ping":
            data = collect_ping(self.app.st, self.app.sup)
            data["proxy"] = _proxy_status(self.app)
            self._json(data)
            return

        if path == "/api/front":
            from .RoomSpec import BASE_DEFAULTS
            from . import Banlists
            st = self.app.st
            room = st.effective_room()
            docs = {
                "lp": "시작 LP (100~40000)",
                "hand": "시작 패 (1~10)",
                "draw": "턴당 드로우 (1~10)",
                "time": "제한 시간 초 (30~6000)",
                "best": "1 = 단판, 3 = 3판 2선승",
                "mr": "마스터 룰 5 = 최신(2020)",
                "main_min": "메인 덱 최소", "main_max": "메인 덱 최대",
                "extra_min": "엑스트라 최소", "extra_max": "엑스트라 최대",
                "side_min": "사이드 최소", "side_max": "사이드 최대",
                "tag": "1 = 태그 듀얼(2:2)",
                "mode": "ocg / tcg / both / pre / any",
                "default_room": "비밀번호 칸이 비었을 때 쓸 방 이름",
                "banlist": "금지/제한 목록(파일|섹션). 빈 값 = 사용 안 함",
                "nocheck": "1 = 덱 내용 검사 안 함(커스텀 카드 통과)",
            }
            try:
                banlists = Banlists.scan(st)
            except Exception:
                banlists = []
            self._json({"room": room, "base": BASE_DEFAULTS,
                        "overrides": st.room_overrides, "docs": docs,
                        "banlists": banlists,
                        "banlistHash": Banlists.resolve(st, room.get("banlist")),
                        "path": st.front_json,
                        "frontPort": st.front_port,
                        "enabled": st.front_port > 0})
            return

        if path == "/api/status":
            now = time.time()
            cached = _status_cache["value"]
            if cached is not None and now - _status_cache["at"] < _STATUS_TTL:
                self._json(cached)
                return
            value = collect_status(self.app.st, self.app.sup)
            value["proxy"] = _proxy_status(self.app)
            _status_cache.update({"at": now, "value": value})
            self._json(value)
            return

        if path == "/api/lflists.zip":
            self._lflists_zip()
            return

        if path == "/api/account":
            st = self.app.st
            auth = self.app.auth
            self._json({"mode": getattr(st, "auth_mode", "both"),
                        "hasAccount": bool(auth and auth.exists()),
                        "id": (auth.data or {}).get("id") if auth else None,
                        "tokenEnabled": bool(st.token) and st.auth_mode != "account"})
            return

        if path == "/api/rooms":
            st = self.app.st
            rooms = []
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/api/getrooms" % st.list_port,
                                            timeout=4) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                rooms = json.loads(raw.split("\r\n\r\n", 1)[-1]).get("rooms", [])
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc), "rooms": []}, 502)
                return
            ghost = getattr(self.app, "ghost", None)
            counts = self.app.front.session_counts() if getattr(self.app, "front", None) else {}
            bots = getattr(ghost, "bot_rooms", None) or {}
            ghosts = getattr(ghost, "ghost_rooms", None) or set()
            slim = []
            for r in rooms:
                try:
                    rid = int(r.get("roomid"))
                except (TypeError, ValueError):
                    continue
                total = counts.get(rid, 0)
                humans = total - (1 if (rid in bots and total > 0) else 0)
                ips = []
                front = getattr(self.app, "front", None)
                if front is not None:
                    try:
                        ips = front.room_ips(rid)
                    except Exception:              # noqa: BLE001
                        ips = []
                slim.append({"id": rid, "notes": r.get("roomnotes"),
                             "needpass": r.get("needpass"), "started": r.get("istart") == "start",
                             "users": [u.get("name") for u in (r.get("users") or [])],
                             "ips": ips,
                             "humans": max(0, humans),
                             "bot": bots.get(rid),
                             "ghost": rid in ghosts})
            self._json({"rooms": slim,
                        "ghost": {"enabled": bool(getattr(ghost, "enabled", False)),
                                  "timeout": getattr(ghost, "timeout", 0),
                                  "history": getattr(ghost, "history", [])[-5:]}})
            return

        if path == "/api/bot":
            st = self.app.st
            out = {"enabled": st.bot_enabled, "url": st.bot_url,
                   "deck": st.bot_deck, "name": st.bot_name, "status": None, "error": None}
            if st.bot_enabled:
                try:
                    req = urllib.request.Request(st.bot_url + "/status")
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        out["status"] = json.loads(resp.read().decode("utf-8", "replace") or "{}")
                except Exception as exc:  # noqa: BLE001
                    out["error"] = str(exc)
            self._json(out)
            return

        if path == "/api/bots":
            st = self.app.st
            status, decks, err = None, [], None
            if st.bot_enabled:
                try:
                    with urllib.request.urlopen(st.bot_url + "/status", timeout=3) as resp:
                        status = json.loads(resp.read().decode("utf-8", "replace") or "{}")
                    with urllib.request.urlopen(st.bot_url + "/decks", timeout=3) as resp:
                        decks = (json.loads(resp.read().decode("utf-8", "replace") or "{}")
                                 or {}).get("decks") or []
                except Exception as exc:  # noqa: BLE001
                    err = str(exc)
            rooms = []
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/api/getrooms" % st.list_port,
                                            timeout=4) as resp:
                    raw_rooms = resp.read().decode("utf-8", "replace")
                for r in json.loads(raw_rooms.split("\r\n\r\n", 1)[-1]).get("rooms", []):
                    rooms.append({"id": r.get("roomid"), "notes": r.get("roomnotes"),
                                  "started": r.get("istart") == "start",
                                  "users": [u.get("name") for u in (r.get("users") or [])]})
            except Exception:  # noqa: BLE001 — 로비가 잠시 없어도 봇 목록은 보여준다
                pass
            self._json(Bots.build_view(st.bot_deck, st.bot_name, st.bot_enabled,
                                       status, decks, rooms, err))
            return

        if path == "/api/auth/backups":
            ab = getattr(self.app, "authbackup", None)
            if ab is None:
                self._json({"items": [], "dir": None})
                return
            self._json(ab.status())
            return

        if path == "/api/access":
            try:
                n = int((qs.get("tail") or ["100"])[0])
            except ValueError:
                n = 100
            room = (qs.get("room") or [None])[0]
            try:
                room = int(room) if room not in (None, "") else None
            except ValueError:
                room = None
            ipq = (qs.get("ip") or [None])[0] or None
            acc = getattr(self.app, "access", None)
            if acc is None:
                self._json({"items": [], "path": None})
                return
            self._json({"items": acc.tail(n, ip=ipq, room=room), "path": acc.path})
            return

        if path == "/api/logs":
            try:
                n = int((qs.get("tail") or ["300"])[0])
            except ValueError:
                n = 300
            n = max(1, min(n, 2000))
            self._json(
                {
                    "lines": self.app.sup.tail(n),
                    "counter": self.app.sup.counter,
                    "path": self.app.st.log_path,
                }
            )
            return

        if path == "/api/replays":
            cfg = load_config(self.app.st)
            rp = self.app.st.rel((cfg.get("replayManager") or {}).get("path"))
            self._json({"dir": rp, "items": list_replays(rp)})
            return

        if path == "/api/replay":
            name = (qs.get("name") or [""])[0]
            cfg = load_config(self.app.st)
            rp = self.app.st.rel((cfg.get("replayManager") or {}).get("path"))
            safe = os.path.basename(name)
            full = os.path.join(rp, safe)
            if not safe.lower().endswith(".yrpx") or not os.path.isfile(full):
                self._json({"error": "not found"}, 404)
                return
            try:
                with open(full, "rb") as f:
                    data = f.read()
            except OSError as exc:
                self._json({"error": str(exc)}, 500)
                return
            self._send(
                200,
                data,
                "application/octet-stream",
                {"Content-Disposition": 'attachment; filename="%s"' % safe},
            )
            return

        self._json({"error": "no route"}, 404)

    # -- POST ------------------------------------------------------------- #
    def route_post(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/setup":
            auth = self.app.auth
            if auth is None or auth.exists():
                self._json({"error": "이미 계정이 있습니다"}, 409)
                return
            body = self._read_body().decode("utf-8", "replace")
            form = urllib.parse.parse_qs(body)
            admin_id = (form.get("id") or [""])[0]
            pw = (form.get("pw") or [""])[0]
            pw2 = (form.get("pw2") or [pw])[0]
            if pw != pw2:
                self._send(400, setup_page("비밀번호 확인이 일치하지 않습니다."), STATIC_TYPES[".html"])
                return
            err = auth.create(admin_id, pw)
            if err:
                self._send(400, setup_page(err), STATIC_TYPES[".html"])
                return
            self._log("admin account created: %s" % auth.data.get("id"))
            self._send(302, b"", "text/plain",
                       session_cookie_headers(auth.issue(), SESSION_TTL, secure=self._is_secure()))
            return

        if path == "/api/login":
            body = self._read_body().decode("utf-8", "replace")
            form = urllib.parse.parse_qs(body)
            st = self.app.st
            auth = self.app.auth
            ip = self._client_ip()
            # ① 관리자 계정 로그인
            admin_id = (form.get("id") or [""])[0]
            pw = (form.get("pw") or [""])[0]
            if admin_id and auth is not None and auth.exists():
                wait = auth.locked(ip)
                if wait > 0:
                    self._send(429, login_page("너무 많이 틀렸습니다. %d초 뒤 다시 시도하세요." % wait),
                               STATIC_TYPES[".html"])
                    return
                ok, msg = auth.check(admin_id, pw)
                if ok:
                    auth.clear_fails(ip)
                    self._log("login ok: %s" % admin_id)
                    self._send(302, b"", "text/plain",
                               session_cookie_headers(auth.issue(), SESSION_TTL,
                                                      secure=self._is_secure()))
                else:
                    auth.note_fail(ip)
                    self._log("login failed: %s (%s)" % (admin_id, ip))
                    self._send(403, login_page(msg), STATIC_TYPES[".html"])
                return
            # ② 비상용 토큰 로그인
            given = (form.get("token") or [""])[0]
            if getattr(st, "auth_mode", "both") != "account" and matches(given, st.token):
                self._send(302, b"", "text/plain",
                           login_cookie_headers(given, secure=self._is_secure()))
            else:
                self._send(403, login_page("아이디 또는 비밀번호가 올바르지 않습니다."),
                           STATIC_TYPES[".html"])
            return

        if path == "/api/logout":
            self._send(302, b"", "text/plain", clear_cookie_headers(secure=self._is_secure()))
            return

        if not self._guard():
            return

        if path == "/api/password":
            auth = self.app.auth
            try:
                req = json.loads(self._read_body().decode("utf-8") or "{}")
            except ValueError:
                req = {}
            err = auth.change_password(req.get("old") or "", req.get("new") or "")
            if err:
                self._json({"error": err}, 400)
                return
            self._log("admin password changed")
            ab = getattr(self.app, "authbackup", None)
            if ab is not None:
                ab.backup("password-change")
            self._json({"ok": True})
            return

        if path == "/api/restart":
            self._restart()
            return

        if path == "/api/start":
            self._json({"ok": self.app.sup.start()})
            return

        if path == "/api/stop":
            self.app.sup.want = False
            threading.Thread(target=lambda: self.app.sup.stop(graceful=True), daemon=True).start()
            self._json({"ok": True})
            return

        if path == "/api/auth/backup":
            ab = getattr(self.app, "authbackup", None)
            if ab is None:
                self._json({"error": "백업기가 없습니다"}, 503)
                return
            res = ab.backup("manual")
            self._log("auth backup: %s" % res)
            self._json(res)
            return

        if path == "/api/rooms/close":
            body = self._read_body()
            try:
                req = json.loads(body.decode("utf-8") or "{}")
            except ValueError:
                req = {}
            try:
                rid = int(req.get("roomId") or req.get("id") or 0)
            except (TypeError, ValueError):
                rid = 0
            ghost = getattr(self.app, "ghost", None)
            if rid <= 0 or ghost is None:
                self._json({"error": "roomId 필요"}, 400)
                return
            self._json({"ok": True, "result": ghost.close_room(rid, why="manual")})
            return

        if path == "/api/bot/start":
            body = self._read_body()
            try:
                req = json.loads(body.decode("utf-8") or "{}")
            except ValueError:
                req = {}
            self._bot_proxy("/start", req)
            return

        if path == "/api/bot/stop":
            body = self._read_body()
            try:
                req = json.loads(body.decode("utf-8") or "{}")
            except ValueError:
                req = {}
            self._bot_proxy("/stop", req)
            return

        if path == "/api/bot/stopall":
            self._bot_proxy("/stopall", {})
            return

        if path == "/api/sync":
            self._sync()
            return

        self._json({"error": "no route"}, 404)

    def _bot_proxy(self, sub, payload):
        st = self.app.st
        if not st.bot_enabled:
            self._json({"error": "봇 서비스가 꺼져 있습니다(MR_BOT_URL)"}, 503)
            return
        if sub == "/start" and isinstance(payload, dict) and not payload.get("name"):
            deck = str(payload.get("deck") or st.bot_deck)
            payload["name"] = st.bot_name if deck == st.bot_deck else deck
        try:
            req = urllib.request.Request(st.bot_url + sub, data=json.dumps(payload).encode("utf-8"),
                                         method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
        except Exception as exc:  # noqa: BLE001
            self._json({"error": "bot service: %s" % exc}, 502)
            return
        self._log("bot %s %s -> %s" % (sub, payload, data))
        self._json(data)

    def _restart(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        force = (qs.get("force") or ["0"])[0] == "1"
        cfg = load_config(self.app.st)
        ports = [p for p in (cfg.get("lobbyListingPort"), cfg.get("roomHostingPort")) if is_int(p)]
        counts = client_counts(ports) or {}
        active = sum(counts.values())
        if active > 0 and not force:
            self._json(
                {
                    "error": "active_clients",
                    "clients": counts,
                    "message": "진행 중인 접속이 %d개 있습니다. 재시작하면 방이 끊깁니다." % active,
                },
                409,
            )
            return
        errors, _w = validate(cfg)
        if errors:
            self._json({"error": errors, "message": "설정에 오류가 있어 재시작을 중단했습니다."}, 422)
            return
        threading.Thread(target=lambda: self.app.sup.restart(graceful=True), daemon=True).start()
        self._json({"ok": True, "restarting": True, "clients": counts})

    def _lflists_zip(self):
        """서버의 금지/제한 목록(*.conf)을 ZIP 으로 — 클라이언트 `lflists` 폴더에 풀면 이름이 표시된다."""
        import io as _io
        import zipfile
        from . import Banlists
        entries = Banlists.scan(self.app.st)
        seen = set()
        buf = _io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for e in entries:
                name = e["file"]
                if name in seen:
                    continue
                seen.add(name)
                try:
                    with open(e["path"], "rb") as f:
                        zf.writestr(name, f.read())
                except OSError:
                    continue
        if not seen:
            self._json({"error": "금지/제한 목록 파일이 없습니다"}, 404)
            return
        self._log("lflists.zip -> %d files" % len(seen))
        self._send(200, buf.getvalue(), "application/zip",
                   {"Content-Disposition": 'attachment; filename="lflists.zip"'})

    def _put_front(self):
        raw = self._read_body()
        try:
            req = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            self._json({"error": ["JSON 파싱 실패"]}, 400)
            return
        room = req.get("room") if isinstance(req, dict) else None
        if not isinstance(room, dict):
            self._json({"error": ["room 객체가 필요합니다"]}, 400)
            return
        try:
            saved = self.app.st.save_room_overrides(room)
        except OSError as exc:
            self._json({"error": ["저장 실패: %s" % exc]}, 500)
            return
        self._log("front.json saved -> %s" % self.app.st.front_json)
        from . import Banlists
        room_now = self.app.st.effective_room()
        self._json({"ok": True, "room": room_now, "overrides": saved,
                    "banlistHash": Banlists.resolve(self.app.st, room_now.get("banlist")),
                    "path": self.app.st.front_json})

    def _sync(self):
        """리포 갱신. `{"name": "<리포>"}` → 그 리포만, 이름이 없으면 **전체 갱신**.

        응답: {"ok": bool, "all": bool, "summary": {...}, "results": [리포별 결과]}
        리포별 결과에는 before→after HEAD, 커밋/파일 목록, 실패 사유, 자식 로그가 들어간다.
        """
        body = self._read_body()
        try:
            req = json.loads(body.decode("utf-8") or "{}")
        except ValueError:
            self._json({"error": "bad json"}, 400)
            return
        name = (req.get("name") or "").strip()
        st = self.app.st
        try:
            cfg = load_config(st)
        except ConfigError as exc:
            self._json({"error": (exc.errors or ["config error"])[0]}, 422)
            return
        state = SyncState(st.sync_state_path)
        out = sync_all(st, cfg, state, self._log, name or None)
        if out is None:
            self._json({"error": "unknown repo: %s" % name}, 404)
            return
        _status_cache.update({"at": 0.0, "value": None})     # 다음 상태 조회는 새로 수집
        results = out["results"]
        summary = out["summary"]
        self._log("sync %s: %d repos, %d changed, %d failed (%dms)" % (
            ("'%s'" % name) if name else "ALL",
            summary["total"], summary["changed"], summary["failed"], summary["durationMs"]))
        payload = {"ok": summary["failed"] == 0, "all": not name,
                   "summary": summary, "results": results}
        if name:
            payload["repo"] = name
            payload["status"] = 200
        self._json(payload)

    # -- PUT -------------------------------------------------------------- #
    def route_put(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._guard():
            return
        if path == "/api/front":
            self._put_front()
            return
        if path != "/api/config":
            self._json({"error": "no route"}, 404)
            return
        raw = self._read_body()
        try:
            cfg = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            self._json({"error": ["JSON 파싱 실패: %s" % exc]}, 400)
            return
        try:
            warnings = save_config(self.app.st, cfg)
        except ConfigError as exc:
            self._json({"error": exc.errors, "warnings": exc.warnings}, 422)
            return
        self._log("config.json saved (backup created)")
        self._json(
            {
                "ok": True,
                "warnings": warnings,
                "pendingRestart": True,
                "path": self.app.st.real_config(),
            }
        )


_SCRIPT_RE = re.compile(r'<script src="/js/([A-Za-z0-9_.\-]+)"></script>')
_LINK_RE = re.compile(r'<link rel="stylesheet" href="/app\.css">')


def _read_web(rel):
    try:
        with open(os.path.join(WEB_DIR, rel), "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def render_index():
    """index.html + app.css + js/*.js 를 **한 응답**으로 합쳐 준다.

    소스는 Web/ 아래에 잘게 나눠 두고(파일 1개 = 책임 1개), 브라우저에는 한 번에 보낸다.
    로컬 HTTP 프록시(AdGuard 등)가 동시 연결을 여러 개 받으면 간헐적으로 502 를
    돌려주는 문제가 실측되어(파일 9개 중 1~3개), 요청 수를 1개로 줄인다.
    ?raw=1 로 원본(분리된 링크/스크립트)을 그대로 받을 수 있다.
    """
    html = _read_web("index.html")
    if html is None:
        return None
    css = _read_web("app.css")
    if css is not None:
        html = _LINK_RE.sub(lambda m: "<style>\n" + css + "\n</style>", html, count=1)

    def inline(m):
        js = _read_web(os.path.join("js", m.group(1)))
        if js is None:
            return m.group(0)
        return "<script>\n" + js + "\n</script>"

    return _SCRIPT_RE.sub(inline, html)


def _proxy_status(app):
    proxy = getattr(app, "proxy", None)
    return proxy.status() if proxy is not None else None


def list_replays(folder, limit=200):
    """replays 폴더의 .yrpX 목록 — **최근에 만들어진 것이 맨 위**."""
    items = []
    if not os.path.isdir(folder):
        return items
    try:
        names = os.listdir(folder)
    except OSError:
        return items
    rows = []
    for fn in names:
        if not fn.lower().endswith(".yrpx"):
            continue
        full = os.path.join(folder, fn)
        try:
            stt = os.stat(full)
        except OSError:
            continue
        rows.append((stt.st_mtime, fn, stt.st_size))
    # 최신 → 과거. 같은 시각이면 파일명 내림차순으로 안정 정렬
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    for mtime, fn, size in rows[:limit]:
        items.append(
            {
                "name": fn,
                "bytes": size,
                "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime)),
            }
        )
    return items


def reset_status_cache():
    _status_cache.update({"at": 0.0, "value": None})
