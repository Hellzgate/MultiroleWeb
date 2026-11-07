# -*- coding: utf-8 -*-
"""유령 방 정리 — 봇만 남은 방을 닫는다.

Multirole 은 **사용자가 0명**이 될 때 방을 닫는다. 그런데 봇은 `room_exists()` 가 참인 한
계속 붙어 있으므로, 사람만 끊기면 **[봇 혼자 남은 방]** 이 그대로 유지된다(봇도 계속 대기).

이 모듈은
    ① 프론트가 센 방별 세션 수 (사람 + 봇)
    ② botd 가 아는 봇 방 목록
을 비교해 "사람 세션이 0" 인 방을 찾고, 유예시간이 지나면
    · 남은 세션을 끊고(kick)   · 봇을 중지(stop)   → 방이 비어 Multirole 이 닫는다.
"""

import threading
import time
import urllib.request
import json


def classify(room_ids, session_counts, bot_rooms, seen, now, timeout, ever=None):
    """방별 판정.

    room_ids        : [id, ...]  (7922 로비 목록)
    session_counts  : {id: 세션수} (프론트가 센 값, 사람+봇)
    bot_rooms       : {id: deck}  (botd 가 관리하는 봇 방)
    seen            : {id: 첫 관측 시각}  ← 이 함수가 갱신한다
    ever            : {id, ...} 사람 세션을 **한 번이라도** 본 방(직결 사용자 오탐 방지)
    반환            : {"ghost": [...], "alive": [...], "unknown": [...]}

    ⚠ Multirole 은 **방장(host)이 끊기면 방을 즉시 닫는다**(Waiting.cpp ConnectionLost).
      그래서 '봇만 남은 방'은 프론트 세션이 사라졌는데도 방이 살아 있는 **비정상 상황**에서만 생긴다.
      직결(7911) 사용자는 프론트가 볼 수 없으므로, 사람을 한 번도 못 본 방은 건드리지 않는다.
    """
    ghost, alive, unknown = [], [], []
    rooms = set(room_ids)
    for rid in room_ids:
        total = int(session_counts.get(rid, 0))
        has_bot = rid in bot_rooms
        humans = total - (1 if (has_bot and total > 0) else 0)
        if humans > 0:
            alive.append(rid)
            if ever is not None:
                ever.add(rid)
            continue
        if not has_bot:
            # 프론트를 거치지 않은(직결) 사람일 수 있다 → 건드리지 않는다
            unknown.append(rid)
            continue
        first = seen.get(rid)
        if first is None:
            first = now
            seen[rid] = first
        if now - first >= timeout and (ever is None or rid in ever):
            ghost.append(rid)
        else:
            alive.append(rid)          # 유예 중
    for rid in list(seen):
        if rid not in rooms:
            seen.pop(rid, None)
    if ever is not None:
        for rid in list(ever):
            if rid not in rooms:
                ever.discard(rid)
    return {"ghost": ghost, "alive": alive, "unknown": unknown}


class GhostReaper(threading.Thread):
    """10초마다 로비를 훑어 '봇만 남은 방'을 정리한다."""

    def __init__(self, st, app, log):
        threading.Thread.__init__(self, daemon=True, name="ghost-reaper")
        self.st = st
        self.app = app
        self.log = log
        self.enabled = bool(getattr(st, "ghost_auto", True))
        self.timeout = float(getattr(st, "ghost_timeout", 90) or 90)
        self.interval = 10.0
        self._stop = False
        self._seen = {}
        self._ever = set()
        self.bot_rooms = {}
        self.ghost_rooms = set()
        self.history = []              # 최근 정리 기록(최대 20)

    # -- io --------------------------------------------------------------- #
    def _list_rooms(self):
        try:
            url = "http://127.0.0.1:%d/api/getrooms" % self.st.list_port
            with urllib.request.urlopen(url, timeout=3) as r:
                raw = r.read().decode("utf-8", "replace")
            rooms = json.loads(raw.split("\r\n\r\n", 1)[-1]).get("rooms", [])
            return [int(x.get("roomid")) for x in rooms]
        except Exception:                      # noqa: BLE001
            return None

    def _bot_rooms(self):
        if not getattr(self.st, "bot_enabled", False):
            return {}
        try:
            with urllib.request.urlopen(self.st.bot_url + "/status", timeout=2) as r:
                data = json.loads(r.read().decode("utf-8", "replace") or "{}")
        except Exception:                      # noqa: BLE001
            return {}
        return dict((int(b["room"]), b.get("deck") or "")
                    for b in (data.get("bots") or []) if b.get("room") is not None)

    def _stop_bot(self, rid):
        if not getattr(self.st, "bot_enabled", False):
            return False
        try:
            req = urllib.request.Request(
                self.st.bot_url + "/stop",
                data=json.dumps({"roomId": rid}).encode("utf-8"),
                method="POST", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as r:
                return bool(json.loads(r.read().decode("utf-8", "replace") or "{}").get("ok"))
        except Exception:                      # noqa: BLE001
            return False

    # -- 작업 ------------------------------------------------------------- #
    def close_room(self, rid, why="manual"):
        """그 방의 세션을 끊고 봇을 중지 → 사용자 0 → Multirole 이 방을 닫는다."""
        front = getattr(self.app, "front", None)
        kicked = front.kick_room(rid) if front is not None else 0
        stopped = self._stop_bot(rid)
        self._seen.pop(rid, None)
        self.ghost_rooms.discard(rid)
        msg = "room %d 정리(%s) — 세션 %d개 종료 · 봇 중지=%s" % (rid, why, kicked, stopped)
        self.log("[ghost] " + msg)
        self.history.append({"at": time.strftime("%H:%M:%S"), "room": rid,
                             "why": why, "kicked": kicked, "stopped": stopped})
        del self.history[:-20]
        return {"room": rid, "kicked": kicked, "stopped": stopped, "why": why}

    def sweep(self):
        rooms = self._list_rooms()
        if rooms is None:
            return None
        front = getattr(self.app, "front", None)
        counts = front.session_counts() if front is not None else {}
        self.bot_rooms = self._bot_rooms()
        res = classify(rooms, counts, self.bot_rooms, self._seen, time.time(), self.timeout,
                       self._ever)
        self.ghost_rooms = set(res["ghost"])
        if self.enabled:
            for rid in res["ghost"]:
                self.close_room(rid, why="auto")
        return res

    def status(self):
        return {"enabled": self.enabled, "timeout": self.timeout,
                "ghost": sorted(self.ghost_rooms), "history": list(self.history)}

    def run(self):
        while not self._stop:
            try:
                self.sweep()
            except Exception as exc:            # noqa: BLE001
                self.log("[ghost] sweep error: %s" % exc)
            for _ in range(int(self.interval)):
                if self._stop:
                    break
                time.sleep(1)

    def stop(self):
        self._stop = True
