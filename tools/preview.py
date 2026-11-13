#!/usr/bin/env python3
"""디자인 프리뷰용 스텁 서버 (실서비스 아님).

Web/ 정적 파일을 그대로 서빙하고, /api/* 는 **그럴듯한 가짜 데이터**로 응답한다.
unslop 검증(스크린샷)용. 실제 배포는 Docker 이미지로 한다.

사용:  python tools/preview.py [포트]
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "..", "Web")

CONFIG = {
    "host": "192.168.0.4", "lobbyPort": 7922, "duelPort": 7911, "webPort": 8090,
    "concurrencyHint": 4, "logLevel": "info", "webhookToken": "…",
    "coreProvider": {"type": "local", "fileRegex": ".*libocgcore\\.so", "loadPerRoom": True},
    "logSinks": [{"type": "file", "properties": {"path": "./logs/multirole.log"}}],
    "autoUpdate": {"enabled": True, "interval": 21600},
    "repos": {"databases": {"url": "https://github.com/ProjectIgnis/BabelCDB.git", "branch": "master"}},
    "instanceName": "Multirole", "allowGuests": True, "maxRooms": 32,
}

PING = {
    "process": {"running": True, "pid": 9124, "uptime": 3725, "restarts": 3, "lastExit": 0, "want": True},
    "clients": {"7911": 2, "7922": 3},
    "config": {"pendingRestart": False},
    "now": "11-13 06:42:10",
}

STATUS = dict(PING, **{
    "config": {"path": "/multirole/config.json", "mtime": "11-13 06:12", "sha256": "9f3c1a…b7e21",
                "pendingRestart": False, "error": None},
    "repos": [
        {"name": "databases", "head": "3c1f0aa", "files": 15, "path": "/multirole/sync/databases",
         "lastSync": {"at": "11-13 06:10", "ok": True, "changed": True, "from": "1d0c72f", "to": "3c1f0aa"}},
        {"name": "scripts", "head": "88be213", "files": 22953, "path": "/multirole/sync/scripts",
         "lastSync": {"at": "11-13 06:10", "ok": True, "changed": False}},
        {"name": "lflists", "head": "1d0c72f", "files": 8, "path": "/multirole/sync/lflists",
         "lastSync": {"at": "11-13 05:58", "ok": True, "changed": False}},
        {"name": "bin", "head": "aa71c9e", "files": 4, "path": "/multirole/sync/bin",
         "lastSync": {"at": "11-13 06:10", "ok": False, "error": "fetch 실패 (timeout 20s)"}},
    ],
    "sync": {"lastAll": {"at": "11-13 06:10", "total": 4, "changed": 1, "failed": 1, "durationMs": 7310,
                         "results": []}},
    "providers": [{"name": "local", "files": 22953, "repos": ["scripts"]}],
    "ports": [{"port": 7911, "open": True}, {"port": 7922, "open": True}, {"port": 7914, "open": True},
              {"port": 8090, "open": True}, {"port": 7930, "open": False}],
    "replays": {"count": 2214, "latest": "2214.yrpX", "latestTime": "11-13 06:12", "bytes": 1843200},
    "cores": {"files": ["1-0-ocgcore.so", "2-0-ocgcore.so", "3-0-ocgcore.so"]},
})

BOTS = {
    "enabled": True, "max": 2, "windbot": True,
    "default": {"deck": "Raisemoon"},
    "running": [
        {"room": 12, "deck": "Raisemoon", "name": "Raisemoon", "pid": 9188, "uptimeText": "12분 4초",
         "alive": True, "log": "/multirole/logs/bot-9188.log"},
        {"room": 15, "deck": "Tearlaments", "name": "Tearlaments", "pid": 9210, "uptimeText": "2분 41초",
         "alive": True, "log": "/multirole/logs/bot-9210.log"},
    ],
    "rooms": [
        {"id": 12, "notes": "duel", "users": ["Hellz", "Raisemoon"], "free": False, "started": True, "bot": "Raisemoon"},
        {"id": 15, "notes": "친구들", "users": ["Sora"], "free": False, "started": True, "bot": "Tearlaments"},
        {"id": 18, "notes": "(이름 없음)", "users": ["Yugi"], "free": True, "started": False, "bot": None},
    ],
    "decks": [
        {"name": "ABC", "running": 0, "missing": False},
        {"name": "Altergeist"}, {"name": "Blackwing", "running": 0},
        {"name": "Blue-Eyes"}, {"name": "Brave"}, {"name": "Burn"},
        {"name": "ChainBurn"}, {"name": "CyberDragon"}, {"name": "DarkMagician"},
        {"name": "Dogmatika"}, {"name": "Dragon"}, {"name": "Evilswarm"},
        {"name": "Graydle"}, {"name": "Mathmech"}, {"name": "Nekroz"},
        {"name": "Raisemoon", "running": 1}, {"name": "Rank V", "missing": True},
        {"name": "SunGodTimeWizard"}, {"name": "Tearlaments", "running": 1},
        {"name": "Timethief"}, {"name": "Zoodiac"},
    ],
    "catalog": [
        {"deck": "ABC", "name": "ABC-드래곤 버스터", "difficulty": "어려움", "call": "b:ABC", "known": True, "space": False},
        {"deck": "Altergeist", "name": "얼터가이스트", "difficulty": "어려움", "call": "b:Altergeist", "known": True, "space": False},
        {"deck": "Blackwing", "name": "[AI] Blackwing (port)", "difficulty": "보통", "call": "b:Blackwing", "known": True, "space": False},
        {"deck": "Blue-Eyes", "name": "푸른 눈의 백룡", "difficulty": "보통", "call": "b:Blue-Eyes", "known": True, "space": False},
        {"deck": "Rank V", "name": "—", "difficulty": "—", "call": "b:Rank V", "known": False, "space": True},
        {"deck": "Raisemoon", "name": "레이즈문", "difficulty": "보통", "call": "b", "known": True, "space": False},
        {"deck": "SunGodTimeWizard", "name": "시흑양신", "difficulty": "보통", "call": "b:SunGodTimeWizard", "known": True, "space": False},
        {"deck": "Tearlaments", "name": "티아라멘츠", "difficulty": "어려움", "call": "b:Tearlaments", "known": True, "space": False},
    ],
}

ROOMS = {"rooms": [
    {"id": 12, "name": "duel", "notes": "duel", "users": ["Hellz", "Raisemoon"], "free": False, "started": True, "bot": "Raisemoon", "ips": ["192.168.0.50"]},
    {"id": 15, "name": "친구들", "notes": "친구들", "users": ["Sora"], "free": False, "started": True, "bot": "Tearlaments", "ips": ["192.168.0.61"]},
    {"id": 18, "name": "", "notes": "", "users": ["Yugi"], "free": True, "started": False, "bot": None, "ips": ["192.168.0.7"]},
]}

FRONT = {
    "enabled": True, "frontPort": 7914, "path": "/multirole/front.json",
    "banlists": ["N/A", "2026.10 OCG", "2026.10 TCG", "GOAT", "World", "Rush"],
    "room": {
        "default_room": "lobby", "lp": 8000, "hand": 5, "draw": 1, "time": 180, "best": 1,
        "mr": 5, "main_min": 40, "main_max": 60, "extra_max": 15, "side_max": 15,
        "mode": "pre", "tag": 0, "banlist": "2026.10 OCG", "nocheck": 0,
    },
}
BOT_INFO = {"enabled": True, "status": {"bots": [1, 2], "max": 2, "decks": 53}}

ACCESS = {"items": [
    {"at": "06:31:02", "event": "join", "ip": "192.168.0.50", "alias": "127.0.210.15", "room": 12, "name": "Hellz", "reason": ""},
    {"at": "06:29:44", "event": "leave", "ip": "192.168.0.61", "alias": "127.0.210.22", "room": 15, "name": "Sora", "reason": "client closed"},
    {"at": "06:12:10", "event": "drop", "ip": "192.168.0.7", "alias": "127.0.210.31", "room": 18, "name": "Yugi", "reason": "timeout"},
]}

AUTH_BACKUPS = {"dir": "/multirole/_auth-backups", "keep": 30, "hours": 24, "total": 3,
                "last": "11-13 06:00", "items": [
                    {"name": "auth-20261113-060000.json", "bytes": 308, "at": "11-13 06:00"},
                    {"name": "auth-20261112-220000.json", "bytes": 308, "at": "11-12 22:00"},
                    {"name": "auth-20261112-013000.json", "bytes": 296, "at": "11-12 01:30"}]}

LOGS = """[06:41:58] [info] lobby: room 12 duel started (2 players)
[06:41:59] [info] core: handling 1204 messages, 0 errors
[06:42:01] [warn] bot: windbot heartbeat 3.2s (slow)
[06:42:02] [info] room 15: Tearlaments joined as spectator
[06:42:03] [info] webhook: databases fetch ok (3c1f0aa)
[06:42:04] [error] repo bin: fetch timeout after 20s
[06:42:05] [info] room 12: turn 4, Hellz LP 6100 / Raisemoon LP 4200
"""

REPLAYS = {"dir": "/multirole/replays", "items": [
    {"name": "2214.yrpX", "bytes": 366148, "at": "11-13 06:12"},
    {"name": "2213.yrpX", "bytes": 402911, "at": "11-13 05:58"},
    {"name": "2212.yrpX", "bytes": 288034, "at": "11-13 04:40"},
    {"name": "2211.yrpX", "bytes": 517220, "at": "11-12 23:12"},
]}

CARDS = {"total": 3, "items": [
    {"id": 14558127, "name": "Ash Blossom & Joyous Spring", "type": "몬스터", "level": 3,
     "atk": 0, "def": 1800, "src": "cards.cdb", "desc": "When a card or effect is activated..."},
    {"id": 101403001, "name": "The Sun God's Poet - Helpoemer", "type": "몬스터", "level": 4,
     "atk": 2000, "def": 1400, "src": "prerelease-imph.cdb", "desc": "If this card is Summoned..."},
    {"id": 10045474, "name": "Infinite Impermanence", "type": "함정", "level": 0,
     "atk": 0, "def": 0, "src": "cards.cdb", "desc": "Target 1 face-up monster your opponent controls..."},
]}

CARDS_CHANGES = {"changed": True, "added": 2, "removed": 0, "modified": 1,
                 "items": [{"kind": "추가", "id": 101403001, "name": "The Sun God's Poet"},
                           {"kind": "변경", "id": 10045474, "name": "Infinite Impermanence"}],
                 "at": "11-13 06:10"}


class Handler(BaseHTTPRequestHandler):
    server_version = "MRPreview/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        full = os.path.normpath(os.path.join(WEB, path))
        if not full.startswith(os.path.abspath(WEB)) or not os.path.isfile(full):
            self.send_error(404)
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8", ".png": "image/png",
                 ".json": "application/json; charset=utf-8"}.get(ext, "application/octet-stream")
        data = open(full, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        q = parse_qs(u.query)
        if p == "/" or p == "/index.html":
            return self._file("index.html")
        if p == "/api/ping":
            return self._json(PING)
        if p == "/api/status":
            return self._json(STATUS)
        if p == "/api/config":
            return self._json({"config": CONFIG, "path": "/multirole/config.json", "warnings": [],
                               "pendingRestart": False, "docs": {}})
        if p == "/api/front":
            return self._json(FRONT)
        if p == "/api/bot":
            return self._json(BOT_INFO)
        if p == "/api/rooms":
            return self._json(ROOMS)
        if p == "/api/access":
            return self._json(ACCESS)
        if p == "/api/auth/backups":
            return self._json(AUTH_BACKUPS)
        if p == "/api/bots":
            return self._json(BOTS)
        if p == "/api/logs":
            text = LOGS.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(text)))
            self.end_headers()
            self.wfile.write(text)
            return
        if p == "/api/replays":
            return self._json(REPLAYS)
        if p == "/api/cards/changes":
            return self._json(CARDS_CHANGES)
        if p == "/api/cards":
            return self._json(CARDS)
        if p.startswith("/api/cards/"):
            return self._json(CARDS["items"][1])
        if p.startswith("/api/"):
            return self._json({"ok": True})
        return self._file(unquote(p.lstrip("/")))

    def do_POST(self):
        return self._json({"ok": True})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("preview http://127.0.0.1:%d/  (stub)" % port)
    srv.serve_forever()


if __name__ == "__main__":
    main()
