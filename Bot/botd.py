#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""봇 컨트롤러 (multirole-bot 컨테이너).

머큐리 프론트(7914)가 "이 방에 봇을 붙여라" 라고 요청하면
Mono 위에서 WindBot 을 띄워 **방 번호로** 입장시킨다.

    POST /start {"roomId": 3, "deck": "raisemoon", "name": "Raisemoon"}
    POST /stop  {"roomId": 3}
    GET  /status            실행 중인 봇 + 사용 가능한 덱 수
    GET  /decks             덱 목록(name 만, AI_ 제외)

방이 사라지면(7922 목록에서 사라짐) 봇 프로세스를 자동 종료한다.
"""

import base64
import glob
import json
import os
import signal
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOT_DIR = os.environ.get("MR_BOT_DIR", "/bot")
WIND_DIR = os.path.join(BOT_DIR, "windbot")
LOG_DIR = os.path.join(BOT_DIR, "logs")
DB_GLOB = os.environ.get("MR_BOT_DB_GLOB", "/db/*.cdb")
PORT = int(os.environ.get("MR_BOT_PORT", "7930"))
FRONT_PORT = int(os.environ.get("MR_FRONT_PORT", "7914"))
LIST_PORT = int(os.environ.get("MR_LIST_PORT", "7922"))
MAX_BOTS = int(os.environ.get("MR_BOT_MAX", "2"))
DEFAULT_NAME = os.environ.get("MR_BOT_NAME", "Raisemoon")
GRACE_SEC = float(os.environ.get("MR_BOT_GRACE", "10"))

_lock = threading.Lock()
_bots = {}                       # roomId -> {proc, deck, name, since, log}
_db_paths_b64 = None


def log(text):
    print("[botd] %s" % text, flush=True)


def db_paths_b64():
    """WindBot DbPaths 인자 (경로 배열 JSON → base64)."""
    global _db_paths_b64
    if _db_paths_b64 is None:
        paths = sorted(glob.glob(DB_GLOB))
        raw = json.dumps(paths, separators=(",", ":")).encode("utf-8")
        _db_paths_b64 = base64.b64encode(raw).decode("ascii")
        log("cdb %d개 → DbPaths %d자" % (len(paths), len(_db_paths_b64)))
    return _db_paths_b64


def deck_list():
    out = []
    for p in sorted(glob.glob(os.path.join(WIND_DIR, "Decks", "*.ydk"))):
        name = os.path.basename(p)[:-4]
        if name.upper().startswith("AI_"):
            name = name[3:]
        out.append(name)
    return out


def room_exists(room_id):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/getrooms" % LIST_PORT,
                                    timeout=3) as r:
            raw = r.read().decode("utf-8", "replace")
        rooms = json.loads(raw.split("\r\n\r\n", 1)[-1]).get("rooms", [])
    except Exception:
        return True                      # 목록을 못 읽으면 유지(성급한 종료 방지)
    return any(int(x.get("roomid", -1)) == int(room_id) for x in rooms)


def stop_bot(room_id, why=""):
    with _lock:
        info = _bots.pop(room_id, None)
    if not info:
        return False
    proc = info["proc"]
    try:
        if proc.poll() is None:
            proc.terminate()
            for _ in range(20):
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
            if proc.poll() is None:
                proc.kill()
    except OSError:
        pass
    log("stop room=%s%s" % (room_id, (" (%s)" % why) if why else ""))
    return True


def start_bot(room_id, deck, name):
    deck = (deck or "raisemoon").strip()
    name = (name or DEFAULT_NAME).strip() or DEFAULT_NAME
    if not os.path.isfile(os.path.join(WIND_DIR, "Decks", "AI_%s.ydk" % deck)):
        return {"error": "unknown deck: %s" % deck, "decks": deck_list()[:80]}
    with _lock:
        if room_id in _bots:
            return {"ok": True, "already": True}
        if len(_bots) >= MAX_BOTS:
            return {"error": "max bots (%d)" % MAX_BOTS}
        os.makedirs(LOG_DIR, exist_ok=True)
        log_path = os.path.join(LOG_DIR, "room%s-%s.log"
                                % (room_id, time.strftime("%Y%m%d-%H%M%S")))
        args = ["mono", "WindBot.exe",
                "Host=127.0.0.1", "Port=%d" % FRONT_PORT,
                "RoomId=%d" % room_id, "Deck=%s" % deck, "Name=%s" % name,
                "Version=41", "DbPaths=%s" % db_paths_b64()]
        lf = open(log_path, "wb")
        proc = subprocess.Popen(args, cwd=WIND_DIR, stdin=subprocess.PIPE,
                                stdout=lf, stderr=subprocess.STDOUT)
        try:
            proc.stdin.write(b"\n")
            proc.stdin.flush()
            proc.stdin.close()
        except OSError:
            pass
        _bots[room_id] = {"proc": proc, "deck": deck, "name": name,
                          "since": time.time(), "log": log_path}
    log("start room=%s deck=%s name=%s pid=%d" % (room_id, deck, name, proc.pid))
    return {"ok": True, "pid": proc.pid, "deck": deck, "name": name}


def status():
    with _lock:
        items = []
        for rid, info in list(_bots.items()):
            proc = info["proc"]
            items.append({"room": rid, "deck": info["deck"], "name": info["name"],
                          "pid": proc.pid, "alive": proc.poll() is None,
                          "uptime": int(time.time() - info["since"]),
                          "log": info["log"]})
    return {"bots": items, "decks": len(deck_list()),
            "windbot": os.path.isfile(os.path.join(WIND_DIR, "WindBot.exe")),
            "max": MAX_BOTS}


def watcher():
    """방이 사라지거나 프로세스가 죽으면 정리한다."""
    gone = {}
    while True:
        time.sleep(5)
        with _lock:
            rooms = list(_bots.items())
        for rid, info in rooms:
            if info["proc"].poll() is not None:
                stop_bot(rid, "exited")
                gone.pop(rid, None)
                continue
            if room_exists(rid):
                gone.pop(rid, None)
                continue
            gone[rid] = gone.get(rid, 0) + 1
            if gone[rid] >= max(1, int(GRACE_SEC / 5.0)):
                stop_bot(rid, "room gone")


class Handler(BaseHTTPRequestHandler):
    server_version = "MultiroleBot/1.0"

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n > 0 else b""
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return {}

    def do_GET(self):
        if self.path.startswith("/status"):
            self._json(status())
        elif self.path.startswith("/decks"):
            self._json({"decks": deck_list()})
        elif self.path.startswith("/health"):
            self._json({"ok": True, "bots": len(_bots)})
        else:
            self._json({"error": "no route"}, 404)

    def do_POST(self):
        req = self._body()
        if self.path.startswith("/start"):
            try:
                rid = int(req.get("roomId") or 0)
            except (TypeError, ValueError):
                rid = 0
            if rid <= 0:
                self._json({"error": "roomId 필요"}, 400)
                return
            self._json(start_bot(rid, req.get("deck"), req.get("name")))
        elif self.path.startswith("/stopall"):
            rids = list(_bots.keys())
            for rid in rids:
                stop_bot(rid, "stopall")
            self._json({"ok": True, "stopped": rids})
        elif self.path.startswith("/stop"):
            try:
                rid = int(req.get("roomId") or 0)
            except (TypeError, ValueError):
                rid = 0
            self._json({"ok": stop_bot(rid, "requested")})
        else:
            self._json({"error": "no route"}, 404)


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.isfile(os.path.join(WIND_DIR, "WindBot.exe")):
        log("WARN: %s/WindBot.exe 없음" % WIND_DIR)
    log("listening 127.0.0.1:%d (front :%d, windbot=%s, decks=%d)"
        % (PORT, FRONT_PORT, WIND_DIR, len(deck_list())))
    threading.Thread(target=watcher, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for rid in list(_bots.keys()):
            stop_bot(rid, "shutdown")


if __name__ == "__main__":
    main()
