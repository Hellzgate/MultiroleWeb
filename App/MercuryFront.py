# -*- coding: utf-8 -*-
"""머큐리 프론트 (P1) — 방 이름 기반 클라이언트를 Multirole 에 연결.

머큐리/Evolution 계열 클라이언트(MDPro4 등)는
    JOIN_GAME(48B) = version u16 | align u16 | gameId u32 | pass utf16[20]  ← pass 가 "방 이름"
으로 접속하고, 서버가 **없으면 방을 만들어** 준다.

Multirole 은
    JOIN_GAME(52B) = version2 u16 | (pad 2) | id u32 | pass utf16[20] | client41.0/core11.0
으로 **이미 있는 방 번호**만 받는다(자동 생성 없음).

이 프론트가 그 차이를 메운다.
    1) 0x17(EXTERNAL_ADDRESS)·길이0 쓰레기 프레임 제거
    2) JOIN(이름) → 이름→방번호 해석
         · 프론트가 만든 방: 내부 맵
         · EDOPro 가 만든 방: Multirole 7922 `/api/getrooms` 조회
       없으면 CREATE_GAME(348B) 을 대신 보내 방을 만들고, 응답의 roomId 를 기록
    3) 나머지 프레임은 그대로 통과(듀얼 메시지는 양쪽이 동일)

설정
    MR_FRONT_PORT   0 이면 비활성 (예: 7914)
    MR_FRONT_TARGET 목적지 host:port (기본 127.0.0.1:7911)
    MR_LIST_PORT    방 목록 HTTP 포트 (기본 7922)
"""

import json
import socket
import struct
import threading
import time
import urllib.request

from . import Banlists, RoomSpec

HANDSHAKE = 4043399681
CLIENT_VER = (41, 0)
CORE_VER = (11, 0)
DROP_TYPES = {0x17}

STOC_NAMES = {
    0x01: "GAME_MSG", 0x02: "ERROR", 0x03: "SELECT_HAND", 0x04: "SELECT_TP",
    0x05: "HAND_RESULT", 0x06: "TP_RESULT", 0x07: "CHANGE_SIDE", 0x08: "WAITING_SIDE",
    0x10: "PLAYER_INFO", 0x11: "CREATE_GAME", 0x12: "JOIN_GAME", 0x13: "TYPE_CHANGE",
    0x14: "LEAVE_GAME", 0x15: "DUEL_START", 0x16: "DUEL_END", 0x17: "REPLAY",
    0x18: "TIME_LIMIT", 0x19: "CHAT", 0x20: "PLAYER_ENTER", 0x21: "PLAYER_CHANGE",
    0x22: "WATCH_CHANGE", 0x23: "KICK", 0x24: "START", 0x25: "READY",
    0xF0: "REMATCH", 0xF2: "CHAT_1", 0xF3: "CHAT_2",
}


def type_name(typ):
    return STOC_NAMES.get(typ, "0x%02X" % typ)


def frame(msg_type, body, declared=None):
    """declared = body+1 규약 (Multirole GetLength() == sizeof(struct))."""
    n = len(body) + 1 if declared is None else declared
    return struct.pack("<H", n) + bytes([msg_type]) + body


def utf16_fixed(text, slot_bytes):
    raw = text.encode("utf-16-le")[: max(0, slot_bytes - 2)]
    return raw + b"\x00" * (slot_bytes - len(raw))


def parse_utf16(raw):
    try:
        s = raw.decode("utf-16-le", "ignore")
    except Exception:
        return ""
    return s.split("\x00")[0].strip()


def build_create_game(spec, banlist_hash=0):
    """방 사양(RoomSpec.parse 결과) → CTOS_CREATE_GAME 프레임."""
    return RoomSpec.build_create_game(spec, HANDSHAKE, CLIENT_VER, CORE_VER, banlist_hash)


def build_join(room_id, password=""):
    """Multirole JOIN_GAME(52B)."""
    return RoomSpec.build_join(room_id, password, CLIENT_VER, CORE_VER)


class MercuryFront(object):
    def __init__(self, st, log):
        self.st = st
        self.log = log
        self.port = 0
        self.sock = None
        self._stop = False
        self.rooms = {}                 # name(lower) -> room id (우리가 만든 방)
        self._room_at = {}              # name(lower) -> 생성 시각(초)
        self._index = {}                # 이름 → 번호 (7922 실시간 목록, 2초 캐시)
        self._index_at = 0.0
        self.connections = 0
        self.created = 0
        self.joined = 0

    # -- lifecycle -------------------------------------------------------- #
    def start(self, port=None):
        port = self.st.front_port if port is None else port
        if port <= 0:
            return False
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", port))
        srv.listen(16)
        self.sock = srv
        self.port = srv.getsockname()[1]
        self.log("[front] listening 0.0.0.0:%d -> %s:%d (mercury join -> multirole)"
                 % (self.port, self.st.front_target_host, self.st.front_target_port))
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return True

    def stop(self):
        self._stop = True
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass

    def status(self):
        return {"port": self.port, "connections": self.connections,
                "created": self.created, "joined": self.joined, "rooms": len(self.rooms)}

    # -- helpers ---------------------------------------------------------- #
    def _list_rooms(self):
        """살아있는 방 목록. **조회 실패면 None**, 빈 목록이면 [] (구분이 중요하다)."""
        url = "http://127.0.0.1:%d/api/getrooms" % self.st.list_port
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                raw = r.read().decode("utf-8", "replace")
            body = raw.split("\r\n\r\n", 1)[-1]
            return json.loads(body).get("rooms", [])
        except Exception:
            return None

    def _live_index(self):
        """방 이름 → 방 번호 (실시간). 2초 캐시."""
        now = time.time()
        if self._index_at > now - 2.0:
            return self._index
        rooms = self._list_rooms()
        if rooms is None:                      # 7922 조회 실패 → 직전 값 유지
            return self._index
        index = {}
        for room in rooms:
            try:
                rid = int(room.get("roomid"))
            except (TypeError, ValueError):
                continue
            notes = (room.get("roomnotes") or "").strip()
            roomname = (room.get("roomname") or "").strip()
            keys = [notes.lower(), roomname.lower()]
            # 우리가 만든 방은 roomnotes 가 "이름 (규칙 요약)" 이다 → 이름 부분도 키로 둔다
            if " (" in notes:
                keys.append(notes.split(" (", 1)[0].strip().lower())
            for key in keys:
                if key:
                    index.setdefault(key, rid)
        # 캐시는 살아있는 방만 남긴다(죽은 방 번호로 JOIN 하면 'Room not found').
        # 단 **방금 만든 방**은 목록 반영(2초 직렬화) 전이라 지우면 안 된다.
        alive = set(index.values())
        now2 = time.time()
        for key in list(self.rooms):
            if self.rooms[key] in alive:
                continue
            if now2 - self._room_at.get(key, 0.0) < 20.0:
                continue                      # 최근 생성분 유지
            del self.rooms[key]
            self._room_at.pop(key, None)
        self._index = index
        self._index_at = now
        return index

    def _find_room(self, name):
        """이름 → 방 번호.

        7922 목록은 Multirole 이 2초마다 직렬화하므로 **방금 만든 방이 아직 없을 수 있다**.
        그 창(15초) 안에서는 우리가 받은 번호를 그대로 쓰고, 죽은 번호면 서버가
        ROOM_NOT_FOUND 를 주므로 그때 새로 만든다(중복 개설 방지).
        """
        key = name.strip().lower()
        if not key:
            return None
        index = self._live_index()
        if index:
            rid = index.get(key)
            if rid:
                self.rooms[key] = rid
                self._room_at.setdefault(key, 0.0)
                return rid
            fresh = self._room_at.get(key, 0.0)
            if key in self.rooms and (time.time() - fresh) < 15.0:
                return self.rooms[key]          # 방금 만든 방(목록 반영 대기)
            return None
        return self.rooms.get(key)             # 7922 를 못 읽을 때만 캐시 사용

    # -- accept / per connection ------------------------------------------ #
    def _accept_loop(self):
        while not self._stop:
            try:
                client, addr = self.sock.accept()
            except OSError:
                break
            self.connections += 1
            threading.Thread(target=self._handle, args=(client, addr), daemon=True).start()

    def _handle(self, client, addr):
        tag = "%s:%d" % (addr[0], addr[1])
        try:
            upstream = socket.create_connection(
                (self.st.front_target_host, self.st.front_target_port), timeout=15)
        except OSError as exc:
            self.log("[front] %s upstream 실패: %s" % (tag, exc))
            _close(client)
            return
        # create_connection 의 15초 타임아웃이 recv 까지 남아 15초 침묵하면 끊기므로 해제
        upstream.settimeout(None)
        client.settimeout(None)
        self.log("[front] %s connected" % tag)
        st = {"pending_name": None}
        threading.Thread(target=self._srv_pump, args=(upstream, client, tag, st), daemon=True).start()
        self._cli_pump(client, upstream, tag, st)
        _close(upstream)
        _close(client)
        self.log("[front] %s closed" % tag)

    def _srv_pump(self, upstream, client, tag, st):
        buf = b""
        try:
            while True:
                data = upstream.recv(8192)
                if not data:
                    self.log("[front] %s server closed" % tag)
                    break
                client.sendall(data)
                buf += data
                while len(buf) >= 3:
                    stored = struct.unpack("<H", buf[0:2])[0]
                    if stored < 1:              # 0 = 쓰레기(00 00). 1 = 본문 0 인 정상 패킷(READY 등)
                        buf = buf[2:]
                        continue
                    ln = stored + 2
                    if len(buf) < ln:
                        break
                    fr, buf = buf[:ln], buf[ln:]
                    typ = fr[2]
                    self._log_frame(tag, "<-", fr)
                    if typ == 0x11 and len(fr) >= 7:      # STOC_CREATE_GAME → room id
                        rid = struct.unpack("<I", fr[3:7])[0]
                        name = st.get("pending_name")
                        key = (name or self.st.front_autoroom or "lobby").strip().lower()
                        self.rooms[key] = rid
                        self._room_at[key] = time.time()
                        self.created += 1
                        self.log("[front] %s room created '%s' id=%d"
                                 % (tag, name or self.st.front_autoroom, rid))
                        self._index_at = 0.0            # 목록 캐시 무효화
                    elif typ == 0x20:
                        st["entered"] = True
                    elif typ == 0x02 and len(fr) >= 6 and st.get("sent_join") \
                            and not st.get("entered") and not st.get("retried"):
                        # JOIN_ERROR — 방이 정말 사라진 경우에만 새로 만든다.
                        # (비밀번호 오류/버전 오류로 방을 중복 개설하면 안 된다)
                        msg = fr[3]
                        code = struct.unpack("<I", fr[4:8])[0] if len(fr) >= 8 else 0
                        st["retried"] = True
                        name = (st.get("pending_name") or (self.st.front_autoroom or "lobby")).strip()
                        self.rooms.pop(name.lower(), None)
                        self._index_at = 0.0
                        if self._find_room(name):
                            self.log("[front] %s join 실패 msg=%d code=0x%08X 이지만 방 '%s' 은 존재 → 생성 안 함"
                                     % (tag, msg, code, name))
                        else:
                            self.log("[front] %s join 실패 msg=%d code=0x%08X · 방 '%s' 사라짐 → 새로 생성"
                                     % (tag, msg, code, name))
                            spec = st.get("spec") or RoomSpec.parse("", self.st.effective_room())
                            try:
                                upstream.sendall(build_create_game(spec, self._banlist_hash(spec)))
                            except OSError:
                                pass
        except OSError as exc:
            if getattr(exc, "errno", None) != 9:          # 9 = 이미 닫힌 소켓(정상 종료 경합)
                self.log("[front] %s server pump error: %s" % (tag, exc))
        _close(client)
        _close(upstream)

    def _log_frame(self, tag, arrow, fr):
        typ = fr[2]
        body = fr[3:]
        name = type_name(typ)
        if typ == 0x02 and len(body) >= 5:                 # ERROR_MSG
            msg = body[0]
            code = struct.unpack("<I", body[1:5])[0]
            self.log("[front] %s %s %s len=%d msg=%d code=0x%08X"
                     % (tag, arrow, name, len(fr), msg, code))
            return
        if typ in (0xF2, 0xF3) or typ == 0x19:             # 채팅 계열은 본문까지
            text = body.decode("utf-16-le", "ignore").strip("\x00").strip()
            self.log("[front] %s %s %s len=%d %r" % (tag, arrow, name, len(fr), text[:200]))
            return
        if not self.st.front_debug:
            return
        if typ in (0x11, 0x12) and len(body) >= 4:
            self.log("[front] %s %s %s len=%d id=%d"
                     % (tag, arrow, name, len(fr), struct.unpack("<I", body[:4])[0]))
        else:
            self.log("[front] %s %s %s len=%d" % (tag, arrow, name, len(fr)))

    def _cli_pump(self, client, upstream, tag, st):
        buf = b""
        try:
            while True:
                data = client.recv(8192)
                if not data:
                    self.log("[front] %s client closed" % tag)
                    break
                buf += data
                while len(buf) >= 3:
                    stored = struct.unpack("<H", buf[0:2])[0]
                    if stored < 1:              # 0 = 쓰레기(00 00). 1 = 본문 0 인 정상 패킷(READY 등)
                        buf = buf[2:]
                        continue
                    ln = stored + 2
                    if len(buf) < ln:
                        break
                    fr, buf = buf[:ln], buf[ln:]
                    typ = fr[2]
                    body = fr[3:]

                    if typ in DROP_TYPES:
                        self.log("[front] %s drop %s" % (tag, type_name(typ)))
                        continue

                    self._log_frame(tag, "->", fr)

                    if typ == 0x10:                        # PLAYER_INFO → 이름 기억
                        st["player"] = parse_utf16(body)
                        upstream.sendall(fr)
                        if self.st.front_autocreate:
                            self._arm_autocreate(upstream, tag, st)
                        continue

                    if typ == 0x12:                        # JOIN (게임 id 또는 방 이름)
                        raw_text, game_id = self._parse_client_join(body)
                        spec = RoomSpec.parse(raw_text, self.st.effective_room())
                        for warn in spec["warnings"]:
                            self.log("[front] %s 옵션 무시: %s" % (tag, warn))
                        st["spec"] = spec
                        st["pending_name"] = spec["name"]
                        st["joined"] = True
                        rid = self._resolve_room(game_id, spec["name"])
                        if rid:
                            upstream.sendall(build_join(rid, spec["password"]))
                            st["sent_join"] = True
                            self.joined += 1
                            self.log("[front] %s join '%s' -> id=%d" % (tag, spec["name"], rid))
                        else:
                            upstream.sendall(build_create_game(spec, self._banlist_hash(spec)))
                            st["created_here"] = True
                            self.log("[front] %s create '%s' [%s] (없는 방)"
                                     % (tag, spec["name"], spec["notes"]))
                        continue

                    upstream.sendall(fr)                   # 나머지는 그대로
        except OSError as exc:
            if getattr(exc, "errno", None) != 9:          # 9 = 이미 닫힌 소켓(정상 종료 경합)
                self.log("[front] %s client pump error: %s" % (tag, exc))
        _close(upstream)
        _close(client)

    def _banlist_hash(self, spec):
        """선택한 금지/제한 목록의 해시(없으면 0 = N/A)."""
        try:
            return Banlists.resolve(self.st, (spec.get("opts") or {}).get("banlist"))
        except Exception:
            return 0

    def _resolve_room(self, game_id, name):
        """gameid 가 실제로 존재하는 방이면 그대로, 아니면 이름→번호, 없으면 None(생성)."""
        index = self._live_index()
        if game_id:
            if game_id in set(index.values()) or game_id in set(self.rooms.values()):
                return game_id
        if name.strip():
            return self._find_room(name)
        return self._find_room(self.st.front_autoroom or "lobby")

    def _arm_autocreate(self, upstream, tag, st):
        """PLAYER_INFO 만 보내고 JOIN 을 안 보내는 클라이언트(예: MDPro4 커스텀 서버) 대응.

        LAN 모드처럼 '연결하면 방이 자동 개설' 되도록, 2초 안에 JOIN 이 없으면
        프론트가 대신 방을 만들어 그 방에 넣는다.
        """
        if st.get("autocreate_armed"):
            return
        st["autocreate_armed"] = True

        def worker():
            time.sleep(2.0)
            if st.get("joined") or st.get("closed"):
                return
            # JOIN 을 안 보내는 클라이언트끼리 **같은 방에서 만나도록** 고정 이름을 쓴다.
            spec = RoomSpec.parse("", self.st.effective_room())
            room = spec["name"]
            st["spec"] = spec
            rid = self._find_room(room)
            try:
                if rid:
                    upstream.sendall(build_join(rid, spec["password"]))
                    self.joined += 1
                    self.log("[front] %s autocreate join '%s' -> id=%d (JOIN 없음)"
                             % (tag, room, rid))
                else:
                    upstream.sendall(build_create_game(spec, self._banlist_hash(spec)))
                    st["pending_name"] = room
                    self.log("[front] %s autocreate '%s' [%s] (JOIN 없음 → 대신 개설)"
                             % (tag, room, spec["notes"]))
            except OSError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _parse_client_join(body):
        """JOIN 본문 → (비밀번호칸 문자열, 게임 id).

        레이아웃(52B, EDOPro/Multirole 동일): version u16 | pad 2 | id u32 | pass utf16[20] | ClientVersion 4
        Mercury 계열은 pass 에 **방 이름**을 넣고, EDOPro LAN 은 **비밀번호**를 넣는다.
        어느 쪽이든 `RoomSpec.parse` 가 `이름#비번#옵션` 문법으로 해석한다.
        """
        if len(body) >= 8 + 40:
            game_id = struct.unpack("<I", body[4:8])[0]
            raw = body[8:48]
        elif len(body) >= 8:                            # 변형: 헤더만
            game_id = struct.unpack("<I", body[4:8])[0]
            raw = b""
        else:
            return "", None
        return parse_utf16(raw), (game_id if game_id else None)


def _close(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass
