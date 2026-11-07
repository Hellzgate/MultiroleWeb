# -*- coding: utf-8 -*-
"""접속 이력 로그 (JSONL) — 누가(실IP) 어느 방에 들어왔고 왜 끊겼는지.

패널 로그(`multirole.log`)는 multirole 출력과 섞여 금방 밀려나므로, 접속 이벤트만 따로 남긴다.

    {"ts":"2026-11-07T20:15:03","ev":"connect","ip":"114.200.216.10","pseudo":"127.0.1.7"}
    {"ts":"2026-11-07T20:15:04","ev":"join","ip":"...","pseudo":"...","room":3,"name":"ComicLO"}
    {"ts":"2026-11-07T20:21:10","ev":"close","ip":"...","pseudo":"...","room":3,"why":"client-fin"}

  - 회전: 20MB 초과 → `access-YYYYmmdd-HHMMSS.log` (최근 10개), 30일 지난 파일 삭제
  - 조회: `tail(n, ip=..., room=...)` — 파일 끝 512KB만 읽어 빠르게
"""

import io
import json
import os
import threading
import time


def _stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class AccessLog(object):
    def __init__(self, st):
        self.dir = getattr(st, "log_dir", None) or "."
        self.path = os.path.join(self.dir, "access.log")
        self.max_bytes = int(getattr(st, "access_max", 20 * 1024 * 1024))
        self.keep = int(getattr(st, "access_keep", 10))
        self.keep_days = int(getattr(st, "access_days", 30))
        self._lock = threading.Lock()
        self._day = ""

    # -- 쓰기 ------------------------------------------------------------- #
    def write(self, ev, ip="", pseudo="", room=None, name="", deck="", why=""):
        rec = {"ts": _stamp(), "ev": ev}
        if ip:
            rec["ip"] = ip
        if pseudo:
            rec["pseudo"] = pseudo
        if room is not None:
            rec["room"] = int(room)
        if name:
            rec["name"] = name
        if deck:
            rec["deck"] = deck
        if why:
            rec["why"] = why
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        try:
            with self._lock:
                try:
                    os.makedirs(self.dir, exist_ok=True)
                except OSError:
                    pass
                self._rotate_if_needed()
                with io.open(self.path, "a", encoding="utf-8") as f:
                    f.write(line)
        except OSError:
            pass

    def _rotate_if_needed(self):
        day = time.strftime("%Y%m%d")
        try:
            size = os.path.getsize(self.path)
        except OSError:
            size = 0
        if size >= self.max_bytes:
            self._rotate(time.strftime("%Y%m%d-%H%M%S"))
        elif self._day and self._day != day and size > 0:
            self._rotate(day)                       # 날짜가 바뀌면 새 파일
        self._day = day
        self._prune()

    def _rotate(self, suffix):
        try:
            os.replace(self.path, os.path.join(self.dir, "access-%s.log" % suffix))
        except OSError:
            pass
        files = sorted(self._rotated())
        while len(files) > self.keep:
            try:
                os.remove(files.pop(0))
            except OSError:
                pass

    def _rotated(self):
        try:
            names = os.listdir(self.dir)
        except OSError:
            return []
        return [os.path.join(self.dir, n) for n in names
                if n.startswith("access-") and n.endswith(".log")]

    def _prune(self):
        limit = time.time() - self.keep_days * 86400
        for full in self._rotated():
            try:
                if os.path.getmtime(full) < limit:
                    os.remove(full)
            except OSError:
                pass

    # -- 읽기 ------------------------------------------------------------- #
    def tail(self, n=100, ip=None, room=None):
        n = max(1, min(int(n or 100), 2000))
        lines = self._read_tail(max_bytes=512 * 1024)
        out = []
        for line in reversed(lines):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if ip and ip not in (rec.get("ip") or ""):
                continue
            if room is not None and int(rec.get("room", -1)) != int(room):
                continue
            out.append(rec)
            if len(out) >= n:
                break
        out.reverse()
        return out

    def _read_tail(self, max_bytes):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return []
        start = max(0, size - max_bytes)
        try:
            with io.open(self.path, "rb") as f:
                f.seek(start)
                data = f.read()
        except OSError:
            return []
        text = data.decode("utf-8", "replace")
        lines = text.split("\n")
        if start > 0:
            lines = lines[1:]                       # 첫 줄은 잘렸을 수 있다
        return [x for x in lines if x.strip()]
