# -*- coding: utf-8 -*-
"""듀얼 프로토콜 프록시 (기본 7912 → 7911, 0x17 제거).

왜 필요한가
    MDPro4 같은 **srvpro 계열 클라이언트**는 접속 직후 ``CTOS_EXTERNAL_ADDRESS (0x17)``
    와 길이 0 쓰레기 프레임(`00 00 00 00`)을 보낸다. Multirole 은 둘 다 모르기 때문에
    **연결을 바로 끊는다**(실측). srvpro 는 EXTERNAL_ADDRESS 를 "uint32 BE IP,
    0이면 무시"로 처리하므로 정보 손실 없이 **그 프레임만 버리면** 나머지 흐름이 진행된다.

동작
    클라 → 서버 : 프레임 재조립 → ``drop_types``(기본 0x17)와 길이<3 프레임만 버리고 중계
    서버 → 클라 : 바이트는 그대로 전달, 로그용으로만 프레임 해석

프레임 규격 (ygopro)
    ``[uint16 length(Little endian)][uint8 type][body]`` — length 는 헤더 포함 전체 길이

설정
    MR_PROXY_PORT / MR_PROXY_BIND / MR_PROXY_TARGET      (0x17 제거용, 예: 7912)
    MR_PROXY2_PORT / MR_PROXY2_TARGET                    (기록용 순수 중계, 예: 7913 → 외부 서버)
"""

import socket
import struct
import threading

DROP_TYPES = {0x17}          # CTOS_EXTERNAL_ADDRESS

CTOS_NAMES = {
    0x01: "RESPONSE", 0x02: "UPDATE_DECK", 0x03: "RPS_CHOICE", 0x04: "TURN_CHOICE",
    0x10: "PLAYER_INFO", 0x11: "CREATE_GAME", 0x12: "JOIN_GAME", 0x13: "LEAVE_GAME",
    0x14: "SURRENDER", 0x15: "TIME_CONFIRM", 0x16: "CHAT", 0x17: "EXTERNAL_ADDRESS",
    0x20: "TO_DUELIST", 0x21: "TO_OBSERVER", 0x22: "READY", 0x23: "NOT_READY",
    0x24: "TRY_KICK", 0x25: "TRY_START", 0xF0: "REMATCH",
}
STOC_NAMES = {
    0x01: "GAME_MSG", 0x02: "ERROR_MSG", 0x03: "CHOOSE_RPS", 0x04: "CHOOSE_ORDER",
    0x05: "RPS_RESULT", 0x06: "ORDER_RESULT", 0x07: "CHANGE_SIDE", 0x08: "WAITING_SIDE",
    0x11: "CREATE_GAME", 0x12: "JOIN_GAME", 0x13: "TYPE_CHANGE", 0x14: "LEAVE_GAME",
    0x15: "DUEL_START", 0x16: "DUEL_END", 0x17: "REPLAY", 0x18: "TIME_LIMIT",
    0x19: "CHAT", 0x20: "PLAYER_ENTER", 0x21: "PLAYER_CHANGE", 0x22: "WATCH_CHANGE",
    0x30: "NEW_REPLAY", 0xF0: "CATCHUP", 0xF1: "REMATCH", 0xF2: "REMATCH_WAIT",
    0xF3: "CHAT_2",
}


class DuelProxy(object):
    def __init__(self, st, log, label="proxy", drop_types=None, target=None):
        self.st = st
        self.log = log
        self.label = label
        self.drop_types = set(DROP_TYPES if drop_types is None else drop_types)
        self.target = target               # (host, port) — None 이면 설정값
        self.port = 0
        self.sock = None
        self._stop = False
        self.dropped = 0
        self.connections = 0

    # -- lifecycle -------------------------------------------------------- #
    def _target(self):
        if self.target:
            return self.target
        return (self.st.proxy_target_host, self.st.proxy_target_port)

    def start(self, host=None, port=None):
        host = host or getattr(self.st, "proxy_bind", "0.0.0.0")
        if port is None:                   # 설정값 사용(0 이면 비활성)
            port = self.st.proxy_port
            if port <= 0:
                return False
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(16)
        self.sock = srv
        self.port = srv.getsockname()[1]
        th, tp = self._target()
        self.log("[%s] listening %s:%d -> %s:%d (drop=%s)"
                 % (self.label, host, self.port, th, tp,
                    ",".join("0x%02X" % x for x in sorted(self.drop_types)) or "none"))
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
                "dropped": self.dropped, "label": self.label}

    # -- accept ----------------------------------------------------------- #
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
        th, tp = self._target()
        try:
            upstream = socket.create_connection((th, tp), timeout=20)
        except OSError as exc:
            self.log("[%s] %s upstream 연결 실패: %s" % (self.label, tag, exc))
            _close(client)
            return
        self.log("[%s] %s connected" % (self.label, tag))
        threading.Thread(target=self._pump_server, args=(upstream, client, tag), daemon=True).start()
        self._pump_client(client, upstream, tag)
        _close(upstream)
        _close(client)
        self.log("[%s] %s closed (연결 종료)" % (self.label, tag))

    # -- 방향 2개 --------------------------------------------------------- #
    def _pump_server(self, upstream, client, tag):
        """서버 → 클라: 바이트는 그대로, 로그용으로만 프레임 해석."""
        buf = b""
        try:
            while True:
                data = upstream.recv(8192)
                if not data:
                    self.log("[%s] %s server EOF (서버가 먼저 끊음)" % (self.label, tag))
                    break
                client.sendall(data)
                buf += data
                while len(buf) >= 3:
                    stored = struct.unpack("<H", buf[0:2])[0]
                    if stored < 1:          # 0 = 쓰레기(00 00). 1 = 본문 0 인 정상 패킷(READY 등)
                        buf = buf[2:]
                        continue
                    ln = stored + 2          # 길이 필드 = body+1 이므로 실제 프레임 = stored+2
                    if len(buf) < ln:
                        break
                    frame, buf = buf[:ln], buf[ln:]
                    typ = frame[2]
                    self.log("[%s] %s <- %s(0x%02X) len=%d"
                             % (self.label, tag, STOC_NAMES.get(typ, "?"), typ, ln))
        except OSError:
            pass
        _close(client)
        _close(upstream)

    def _pump_client(self, client, upstream, tag):
        """클라 → 서버: 프레임 재조립 후 drop_types/쓰레기 프레임만 제거."""
        buf = b""
        try:
            while True:
                data = client.recv(8192)
                if not data:
                    self.log("[%s] %s client EOF (클라가 먼저 끊음)" % (self.label, tag))
                    break
                buf += data
                while len(buf) >= 3:
                    stored = struct.unpack("<H", buf[0:2])[0]
                    if stored < 1:          # 0 = 쓰레기(00 00). 1 = 본문 0 인 정상 패킷(READY 등)
                        # 00 00 00 00 00 00 같은 쓰레기 프레임 → Multirole 이 즉시 끊는다
                        self.log("[%s] %s dropped junk %s" % (self.label, tag, buf[:2].hex()))
                        buf = buf[2:]
                        continue
                    ln = stored + 2
                    if ln > 0x10000:
                        upstream.sendall(buf)
                        buf = b""
                        break
                    if len(buf) < ln:
                        break
                    frame, buf = buf[:ln], buf[ln:]
                    typ = frame[2]
                    if typ in self.drop_types:
                        self.dropped += 1
                        self.log("[%s] %s dropped %s(0x%02X) len=%d"
                                 % (self.label, tag, CTOS_NAMES.get(typ, "?"), typ, ln))
                        continue
                    self.log("[%s] %s pass %s(0x%02X) len=%d"
                             % (self.label, tag, CTOS_NAMES.get(typ, "?"), typ, ln))
                    upstream.sendall(frame)
        except OSError:
            pass
        if buf:
            try:
                upstream.sendall(buf)
            except OSError:
                pass
        _close(upstream)
        _close(client)


def _close(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass
