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
import re
import select
import socket
import sys
import traceback
import zlib
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
        self._decks = set()              # 봇 덱 이름 캐시(공백 덱 호출용, 60초)
        self._deck_at = 0.0
        # 방 번호별 세션 추적(유령 방 정리용). tag -> {"room": id, "client": sock, "upstream": sock}
        self._sessions = {}
        self._sess_lock = threading.Lock()
        # 실IP → 멀티롤이 보는 별칭(127.0.a.b). 같은 사람은 항상 같은 별칭
        self._ip_map = {}
        self._pseudo_used = set()
        self.access = None               # App 이 AccessLog 를 넣어준다

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

    # -- 세션 추적(유령 방 정리) ------------------------------------------- #
    def pseudo_ip(self, ip):
        """실제 IP → 별칭 루프백 주소(127.0.a.b). multirole 이 클라이언트별로 구분할 수 있게."""
        ip = ip or "0.0.0.0"
        with self._sess_lock:
            known = self._ip_map.get(ip)
            if known:
                return known
            h = zlib.crc32(ip.encode("utf-8")) & 0xFFFFFFFF
            for attempt in range(0, 254):
                a = 1 + ((h >> 8) + attempt) % 254
                b = 1 + (h % 254)
                cand = "127.0.%d.%d" % (a, b)
                if cand not in self._pseudo_used:
                    self._pseudo_used.add(cand)
                    self._ip_map[ip] = cand
                    return cand
            return "127.0.254.254"

    def ip_of(self, tag):
        with self._sess_lock:
            return (self._sessions.get(tag) or {}).get("ip") or ""

    def pseudo_of(self, tag):
        with self._sess_lock:
            return (self._sessions.get(tag) or {}).get("pseudo") or ""

    def room_ips(self, rid):
        """그 방에 있는 프론트 세션들의 실제 IP(중복 제거)."""
        rid = int(rid)
        with self._sess_lock:
            ips = [(i.get("ip") or "") for i in self._sessions.values() if i.get("room") == rid]
        seen, out = set(), []
        for ip in ips:
            if ip and ip not in seen:
                seen.add(ip)
                out.append(ip)
        return out

    def _register(self, tag, client, upstream, ip="", pseudo=""):
        with self._sess_lock:
            self._sessions[tag] = {"room": None, "client": client, "upstream": upstream,
                                   "ip": ip, "pseudo": pseudo, "t0": time.time()}

    def _unregister(self, tag):
        with self._sess_lock:
            self._sessions.pop(tag, None)

    def _set_room(self, tag, rid):
        with self._sess_lock:
            if tag in self._sessions:
                self._sessions[tag]["room"] = int(rid)

    def session_counts(self):
        """방 번호 -> 세션 수(사람+봇)."""
        out = {}
        with self._sess_lock:
            for info in self._sessions.values():
                rid = info.get("room")
                if rid is not None:
                    out[rid] = out.get(rid, 0) + 1
        return out

    def kick_room(self, rid):
        """그 방에 물린 프론트 세션을 모두 끊는다(사용자 제거 → 방이 비면 Multirole 이 닫는다)."""
        rid = int(rid)
        with self._sess_lock:
            victims = [(t, i["client"], i["upstream"], i.get("ip") or "", i.get("pseudo") or "")
                       for t, i in self._sessions.items() if i.get("room") == rid]
        for tag, client, upstream, ip, pseudo in victims:
            _close(client)
            _close(upstream)
            self.log("[front] %s kick (room %d, %s)" % (tag, rid, ip or "?"))
            if self.access:
                self.access.write("kick", ip=ip, pseudo=pseudo, room=rid, why="kick")
        return len(victims)

    def _handle(self, client, addr):
        tag = "%s:%d" % (addr[0], addr[1])
        pseudo = self.pseudo_ip(addr[0])
        try:
            upstream = socket.create_connection(
                (self.st.front_target_host, self.st.front_target_port), timeout=15,
                source_address=(pseudo, 0))
        except OSError as exc:
            # 별칭 바인딩 실패(드묾) → 일반 연결로 폴백
            try:
                self.log("[front] %s 별칭 %s 실패(%s) → 기본 연결" % (tag, pseudo, exc))
                upstream = socket.create_connection(
                    (self.st.front_target_host, self.st.front_target_port), timeout=15)
                pseudo = "127.0.0.1"
            except OSError as exc2:
                self.log("[front] %s upstream 실패: %s" % (tag, exc2))
                _close(client)
                return
        # create_connection 의 15초 타임아웃이 recv 까지 남아 15초 침묵하면 끊기므로 해제
        upstream.settimeout(30.0)          # 유휴는 정상 → 펌프가 continue 로 계속 대기
        client.settimeout(30.0)
        _keepalive(client)
        _keepalive(upstream)
        self.log("[front] %s connected (별칭 %s)" % (tag, pseudo))
        st = {"pending_name": None, "thread": threading.current_thread()}
        self._register(tag, client, upstream, addr[0], pseudo)
        if self.access:
            self.access.write("connect", ip=addr[0], pseudo=pseudo)
        threading.Thread(target=self._srv_pump, args=(upstream, client, tag, st), daemon=True).start()
        threading.Thread(target=self._watch_session, args=(client, upstream, tag, st), daemon=True).start()
        try:
            self._cli_pump(client, upstream, tag, st)
        except Exception as exc:                       # noqa: BLE001 — 어떤 예외든 소켓은 닫는다
            self.log("[front] %s session error: %s: %s" % (tag, type(exc).__name__, exc))
        finally:
            st["done"] = True
            info = {}
            with self._sess_lock:
                info = dict(self._sessions.get(tag) or {})
            if self.access:
                self.access.write("close", ip=info.get("ip") or "",
                                  pseudo=info.get("pseudo") or "",
                                  room=info.get("room"), why="closed")
            self._unregister(tag)
            _close(upstream)
            _close(client)
            self.log("[front] %s closed" % tag)

    def _watch_session(self, client, upstream, tag, st):
        """FIN 만 받고 스레드가 멈춘 소켓(CLOSE_WAIT)을 강제로 정리한다.

        이걸 안 하면 프론트가 7911 업스트림을 계속 붙잡아 방이 로비에 남는다(유령 방).
        """
        try:
            peer = client.getpeername()
        except OSError:
            return
        seen = 0
        while not st.get("done") and not self._stop:
            time.sleep(2)
            state = _conn_state(peer)
            if state in ("08", "07", "09"):            # CLOSE_WAIT / CLOSE / LAST_ACK
                seen += 1
                if seen >= 2:                          # 약 4초 이상 방치 → 강제 종료
                    self._dump_stack(tag, st)
                    self.log("[front] %s stale socket(%s) 4s → 강제 종료" % (tag, state))
                    st["done"] = True
                    _close(client)
                    _close(upstream)
                    return
            elif state in ("01", "02", "03", "0B"):    # 살아있음/연결 중
                seen = 0

    def _dump_stack(self, tag, st):
        """방치된 세션의 **스레드 스택**을 로그에 남긴다(원인 추적용)."""
        th = st.get("thread")
        if th is None:
            return
        try:
            frame = sys._current_frames().get(th.ident)
            if frame is None:
                return
            stack = "".join(traceback.format_stack(frame, limit=8))
            one = " | ".join(x.strip() for x in stack.split("\n") if x.strip())
            self.log("[front] %s stack: %s" % (tag, one[:900]))
        except Exception:                      # noqa: BLE001
            pass

    def _srv_pump(self, upstream, client, tag, st):
        buf = b""
        try:
            while True:
                try:
                    data = upstream.recv(8192)
                except socket.timeout:
                    if st.get("done"):
                        break
                    continue
                if not data:
                    self.log("[front] %s server closed" % tag)
                    break
                _send(client, data)
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
                        st["room_id"] = rid
                        self._set_room(tag, rid)
                        if self.access:
                            self.access.write("create", ip=self.ip_of(tag),
                                              pseudo=self.pseudo_of(tag), room=rid,
                                              name=st.get("pending_name") or "")
                        name = st.get("pending_name")
                        key = (name or self.st.front_autoroom or "lobby").strip().lower()
                        self.rooms[key] = rid
                        self._room_at[key] = time.time()
                        self.created += 1
                        self.log("[front] %s room created '%s' id=%d"
                                 % (tag, name or self.st.front_autoroom, rid))
                        self._index_at = 0.0            # 목록 캐시 무효화
                        want = st.get("bot_deck")
                        if want and not st.get("bot_spawned"):
                            st["bot_spawned"] = True
                            self._spawn_bot(rid, want)
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
                            if st.get("server_join"):
                                # 방 번호로 온 입장은 새 방을 만들지 않는다(클라이언트가 오류를 표시)
                                self.log("[front] 서버모드 입장 실패 → 방 생성 안 함")
                            else:
                                spec = st.get("spec") or RoomSpec.parse("", self.st.effective_room())
                                try:
                                    _send(upstream, build_create_game(spec, self._banlist_hash(spec)))
                                except OSError:
                                    pass
        except Exception as exc:                       # noqa: BLE001
            if getattr(exc, "errno", None) != 9:          # 9 = 이미 닫힌 소켓(정상 종료 경합)
                self.log("[front] %s server pump error: %s: %s"
                         % (tag, type(exc).__name__, exc))
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
                try:
                    data = client.recv(8192)
                except socket.timeout:
                    if st.get("done"):
                        break
                    continue
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

                    if typ == 0x11:                        # CREATE_GAME(서버모드) → 방 이름(notes) 기억
                        try:
                            name_u = parse_utf16(body[68:108])
                            notes = body[148:348].split(b"\x00", 1)[0].decode("utf-8", "ignore").strip()
                        except Exception:
                            name_u, notes = "", ""
                        st["pending_name"] = notes or name_u or None
                        st["server_create"] = True
                        # 서버모드에서도 봇 호출: Notes(또는 Host Name)가 bot / b:<덱>
                        bot_deck = self._bot_trigger(notes) or self._bot_trigger(name_u)
                        if bot_deck:
                            st["bot_deck"] = bot_deck
                            st["bot_spawned"] = False
                            self.log("[front] 봇 트리거(서버모드) '%s' → deck=%s"
                                     % (st["pending_name"] or "", bot_deck))
                            if getattr(self.st, "bot_nocheck", False):
                                buf = bytearray(fr)
                                buf[3 + 7] = 1              # HostInfo.dontCheckDeckContent
                                fr = bytes(buf)
                                self.log("[front] 봇 방(서버모드) → 덱 확인하지 않기 ON")
                        _send(upstream, fr)
                        self.log("[front] 서버모드 방 생성 요청 '%s'" % (st["pending_name"] or ""))
                        continue

                    if typ == 0x10:                        # PLAYER_INFO → 이름 기억
                        st["player"] = parse_utf16(body)
                        _send(upstream, fr)
                        if self.st.front_autocreate:
                            self._arm_autocreate(upstream, tag, st)
                        continue

                    if typ == 0x12:                        # JOIN (게임 id 또는 방 이름)
                        raw_text, game_id = self._parse_client_join(body)
                        known_id = None
                        if game_id:
                            idx = self._live_index()
                            if game_id in set(idx.values()) or game_id in set(self.rooms.values()):
                                known_id = game_id
                        if known_id:
                            # 서버 대전 모드: 방 번호로 들어오고, pass 필드는 **비밀번호**다
                            spec = RoomSpec.parse("", self.st.effective_room())
                            spec["password"] = raw_text.strip()
                            self.log("[front] 서버모드 입장 id=%d (pass=%s)"
                                     % (known_id, "있음" if spec["password"] else "없음"))
                        else:
                            spec = RoomSpec.parse(raw_text, self.st.effective_room())
                        for warn in spec["warnings"]:
                            self.log("[front] %s 옵션 무시: %s" % (tag, warn))
                        st["spec"] = spec
                        st["pending_name"] = spec["name"]
                        st["joined"] = True
                        st["server_join"] = bool(game_id)   # 번호로 온 입장(서버모드)
                        bot_deck = self._bot_trigger(spec["name"])
                        if bot_deck:
                            st["bot_deck"] = bot_deck
                            st["bot_spawned"] = False
                            self.log("[front] 봇 트리거 '%s' → deck=%s" % (spec["name"], bot_deck))
                            if getattr(self.st, "bot_nocheck", False):
                                # 봇 방은 덱 내용 검사를 끈다(서버 DB 에 없는 카드가 섞인 봇 덱 보호)
                                spec["opts"]["nocheck"] = 1
                                self.log("[front] 봇 방 → 덱 확인하지 않기 ON")
                        rid = self._resolve_room(game_id, spec["name"])
                        if rid:
                            _send(upstream, build_join(rid, spec["password"]))
                            st["sent_join"] = True
                            st["room_id"] = rid
                            self._set_room(tag, rid)
                            if self.access:
                                self.access.write("join", ip=self.ip_of(tag),
                                                  pseudo=self.pseudo_of(tag), room=rid,
                                                  name=st.get("player") or "")
                            self.joined += 1
                            self.log("[front] %s join '%s' -> id=%d" % (tag, spec["name"], rid))
                            if st.get("bot_deck") and not st.get("bot_spawned"):
                                st["bot_spawned"] = True
                                self._spawn_bot(rid, st["bot_deck"])
                        else:
                            _send(upstream, build_create_game(spec, self._banlist_hash(spec)))
                            st["created_here"] = True
                            self.log("[front] %s create '%s' [%s] (없는 방)"
                                     % (tag, spec["name"], spec["notes"]))
                        continue

                    _send(upstream, fr)                   # 나머지는 그대로
        except Exception as exc:                       # noqa: BLE001
            if getattr(exc, "errno", None) != 9:          # 9 = 이미 닫힌 소켓(정상 종료 경합)
                self.log("[front] %s client pump error: %s: %s"
                         % (tag, type(exc).__name__, exc))
        _close(upstream)
        _close(client)

    # 덱 이름은 대소문자를 구분하므로 **원문에서** 뽑아낸다(매칭만 무시).
    BOT_TRIGGER = re.compile(r"^(?:b|bot)(?::([A-Za-z0-9_\-]+))?$", re.IGNORECASE)

    def _known_decks(self):
        """봇 컨트롤러가 가진 덱 이름(60초 캐시). 실패하면 직전 값."""
        now = time.time()
        if self._deck_at and now - self._deck_at < 60.0:
            return self._decks
        try:
            with urllib.request.urlopen(self.st.bot_url + "/decks", timeout=2) as r:
                raw = r.read().decode("utf-8", "replace")
            decks = set((json.loads(raw) or {}).get("decks") or [])
        except Exception:                       # noqa: BLE001 — 봇 서비스가 없어도 대전은 계속
            return self._decks
        if decks:
            self._decks = decks
            self._deck_at = now
        return self._decks

    def _bot_trigger(self, name):
        """방 이름이 b / bot / b:<deck> 이면 봇 덱 이름을 돌려준다(아니면 None).

        덱 이름에 **공백**이 있는 덱(`Rank V`, `Toadally Awesome` …)은 정규식으로는
        잡히지 않으므로, 실제 덱 목록과 대조해 한 번 더 시도한다.
        """
        if not getattr(self.st, "bot_enabled", False):
            return None
        name = (name or "").strip()
        m = self.BOT_TRIGGER.match(name)
        if m:
            deck = (m.group(1) or self.st.bot_deck or "raisemoon").strip()
        elif name.lower().startswith(("b:", "bot:")):
            deck = name.split(":", 1)[1].strip()      # 공백 든 덱(Rank V 등)
        else:
            return None
        if not deck:
            return None
        # 대소문자만 다른 입력도 실제 덱 이름으로 맞춘다(리눅스는 파일명 대소문자 구분)
        canon = dict((d.lower(), d) for d in self._known_decks())
        return canon.get(deck.lower(), deck)

    def _spawn_bot(self, room_id, deck):
        """봇 컨트롤러에 '이 방에 붙어라' 요청(비동기, 실패해도 대전은 계속)."""
        if not room_id:
            return
        url = "%s/start" % self.st.bot_url
        # 기본 덱이면 지정한 봇 이름, 다른 덱을 부르면 덱 이름을 그대로 쓴다
        name = self.st.bot_name if deck == self.st.bot_deck else deck
        body = json.dumps({"roomId": int(room_id), "deck": deck, "name": name},
                          ensure_ascii=False).encode("utf-8")

        def worker():
            try:
                req = urllib.request.Request(url, data=body, method="POST",
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
                if data.get("error"):
                    self.log("[front] 봇 실패 room=%s deck=%s: %s"
                             % (room_id, deck, data["error"]))
                else:
                    self.log("[front] 봇 투입 room=%s deck=%s pid=%s"
                             % (room_id, deck, data.get("pid", "-")))
            except Exception as exc:
                self.log("[front] 봇 요청 실패 room=%s: %s" % (room_id, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _banlist_hash(self, spec):
        """선택한 금지/제한 목록의 해시(없으면 0 = N/A)."""
        try:
            return Banlists.resolve(self.st, (spec.get("opts") or {}).get("banlist"))
        except Exception:
            return 0

    def _resolve_room(self, game_id, name):
        """gameid 가 실제로 존재하는 방이면 그대로, 아니면 이름→번호, 없으면 None(생성).

        이름이 **숫자만**이면 방 번호로도 시도한다(서버모드 방의 Notes 가 비어 있을 때 대비).
        """
        index = self._live_index()
        if game_id:
            # 서버 대전 모드: 클라이언트가 방 번호를 명시했으면 **그대로 신뢰**한다.
            # (7922 목록은 2초 지연이 있어 방금 만든 방이 없을 수 있다)
            return game_id
        text = (name or "").strip()
        if text:
            rid = self._find_room(text)
            if rid:
                return rid
            if text.isdigit():
                cand = int(text)
                if cand in set(index.values()) or cand in set(self.rooms.values()):
                    self.log("[front] 숫자 '%s' → 방 번호 %d 로 입장" % (text, cand))
                    return cand
            return None
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
                    _send(upstream, build_join(rid, spec["password"]))
                    self.joined += 1
                    self.log("[front] %s autocreate join '%s' -> id=%d (JOIN 없음)"
                             % (tag, room, rid))
                else:
                    _send(upstream, build_create_game(spec, self._banlist_hash(spec)))
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


def _send(sock, data, timeout=10.0):
    """상대가 읽지 않아 sendall 이 영원히 멈추는 것을 막는다.

    쓰기 버퍼가 `timeout` 초 동안 비지 않으면 연결이 죽은 것으로 보고 OSError 를 낸다
    (호출부의 except 가 세션을 닫는다). 관측: 클라이언트 FIN 이후 펌프가 sendall 에
    걸려 EOF 를 처리하지 못하고 CLOSE_WAIT 으로 10초 남던 사례가 있었다.
    """
    view = memoryview(data)
    while view:
        try:
            _, writable, _ = select.select([], [sock], [], timeout)
        except (OSError, ValueError):
            raise OSError("select failed")
        if not writable:
            raise OSError("send timeout (peer not reading)")
        try:
            n = sock.send(view)
        except (BlockingIOError, InterruptedError):
            continue
        if n <= 0:
            raise OSError("send returned %d" % n)
        view = view[n:]


def _close(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


# --- 소켓 위생 (2026-11-07) -------------------------------------------------
# 사고: 클라이언트가 FIN 만 보내고 사라졌는데(관찰: 7914 CLOSE_WAIT) 프론트가
#      7911 업스트림을 붙잡고 있어 Multirole 이 사용자를 계속 유지 → 로비에 유령 방.
#   원인 1) 펌프 스레드가 OSError 가 아닌 예외로 죽으면 close 를 건너뛴다.
#   원인 2) half-open(전원/네트워크 끊김)은 커널 타임아웃(기본 2시간)까지 남는다.
def _dec4(h):
    return socket.inet_ntop(socket.AF_INET, bytes.fromhex(h)[::-1])


def _dec6(h):
    b = bytes.fromhex(h)
    out = b""
    for i in range(0, 16, 4):
        out += b[i:i + 4][::-1]
    return socket.inet_ntop(socket.AF_INET6, out)


def _norm_ip(ip):
    return (ip or "").replace("::ffff:", "")


def _keepalive(sock, idle=60, intvl=15, cnt=4):
    """half-open 을 커널이 정리하도록(기본 2시간 → 약 105초)."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for name, val in (("TCP_KEEPIDLE", idle), ("TCP_KEEPINTVL", intvl), ("TCP_KEEPCNT", cnt)):
            opt = getattr(socket, name, None)
            if opt is not None:
                sock.setsockopt(socket.IPPROTO_TCP, opt, val)
    except OSError:
        pass


def _conn_state(peer):
    """(ip, port) 피어의 TCP 상태 코드('01'=ESTAB, '08'=CLOSE_WAIT ...) 또는 None."""
    want_ip, want_port = _norm_ip(peer[0]), int(peer[1])
    for path, v6 in (("/proc/net/tcp", False), ("/proc/net/tcp6", True)):
        try:
            lines = open(path).read().splitlines()[1:]
        except OSError:
            continue
        for ln in lines:
            f = ln.split()
            if len(f) < 4 or f[3] == "0A":
                continue
            try:
                rh, rp = f[2].split(":")
                rip = _dec6(rh) if v6 else _dec4(rh)
                if _norm_ip(rip) == want_ip and int(rp, 16) == want_port:
                    return f[3]
            except (ValueError, OSError):
                continue
    return None
