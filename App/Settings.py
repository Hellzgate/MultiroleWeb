# -*- coding: utf-8 -*-
"""실행 설정(환경변수 → 속성) 과 config.json 영속화 경로 처리.

환경변수
    MR_BASE             작업 폴더(기본 /multirole) — multirole 의 CWD
    MR_CONFIG           자식이 읽는 config 경로(기본 <base>/config.json)
    MR_CONFIG_PERSIST   실제 파일(바인드 마운트 안). 있으면 MR_CONFIG 는 심볼릭 링크
    MR_BIN              실행 파일(기본 ./multirole)
    MR_ARGS             추가 인자
    MR_LOG_DIR          로그 폴더(기본 <base>/logs)
    MR_LOG_MAX/KEEP     로그 회전 기준
    MR_RESTART_DELAY    자식이 죽은 뒤 재기동 대기(초)
    MR_STOP_GRACE       SIGTERM 유예(초)
    MR_STDOUT_LOG       0 이면 docker logs 로 안 보냄
    WEB_BIND/WEB_PORT/WEB_TOKEN   웹 패널
"""

import os
import io
import json
import shlex
import shutil

REQUIRED_BIN = "multirole"

# 방 규칙 기본값 키 (RoomSpec.BASE_DEFAULTS 와 동일해야 한다)
ROOM_KEYS = (
    "default_room", "lp", "hand", "draw", "time", "best", "mr", "mode",
    "main_min", "main_max", "extra_min", "extra_max", "side_min", "side_max", "tag",
    "banlist", "nocheck",
)

TEXT_ROOM_KEYS = ("default_room", "mode", "banlist")


def coerce_room_value(key, value):
    """폼에서 온 값(문자열 가능)을 키에 맞는 타입으로. 실패하면 None."""
    if key in TEXT_ROOM_KEYS:
        if isinstance(value, str):
            return value.strip()
        return "" if value is None else str(value)
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _env_room_defaults():
    """환경변수 MR_ROOM_* 로 기본값을 덮어쓴다. 잘못된 값은 조용히 무시."""
    room = {}
    text_keys = {"default_room": "MR_ROOM_DEFAULT", "mode": "MR_ROOM_MODE"}
    for key in ROOM_KEYS:
        env = text_keys.get(key, "MR_ROOM_" + key.upper())
        raw = os.environ.get(env)
        if raw is None or raw.strip() == "":
            continue
        raw = raw.strip()
        if key in text_keys:
            room[key] = raw
            continue
        try:
            room[key] = int(raw)
        except ValueError:
            continue
    return room


class Settings(object):
    def __init__(self, base=None):
        self.base = base or os.environ.get("MR_BASE", "/multirole")
        # config.json the child reads (its CWD) - see ensure_persist_link()
        self.config_path = os.environ.get("MR_CONFIG") or os.path.join(self.base, "config.json")
        # real file inside the bind-mounted folder (survives container recreation)
        self.config_persist = (os.environ.get("MR_CONFIG_PERSIST") or "").strip()
        self.log_dir = os.environ.get("MR_LOG_DIR") or os.path.join(self.base, "logs")
        self.log_path = os.path.join(self.log_dir, "multirole.log")
        self.log_max = int(os.environ.get("MR_LOG_MAX", 10 * 1024 * 1024))
        self.log_keep = int(os.environ.get("MR_LOG_KEEP", "3"))
        self.bin = os.environ.get("MR_BIN", os.path.join(".", REQUIRED_BIN))
        self.args = shlex.split(os.environ.get("MR_ARGS", ""))
        self.restart_delay = float(os.environ.get("MR_RESTART_DELAY", "3"))
        self.stop_grace = float(os.environ.get("MR_STOP_GRACE", "10"))
        self.bind = os.environ.get("WEB_BIND", "0.0.0.0")
        self.port = int(os.environ.get("WEB_PORT", "8080"))
        self.token = os.environ.get("WEB_TOKEN", "").strip()
        self.backup_keep = 20
        self.ring_max = 2000
        # 듀얼 프로토콜 프록시(0x17 제거) — 0 이면 비활성
        self.proxy_port = int(os.environ.get("MR_PROXY_PORT", "0"))
        self.proxy_bind = os.environ.get("MR_PROXY_BIND", "0.0.0.0")
        target = os.environ.get("MR_PROXY_TARGET", "127.0.0.1:7911")
        host, _, tport = target.partition(":")
        self.proxy_target_host = host or "127.0.0.1"
        self.proxy_target_port = int(tport or "7911")
        # 기록용 순수 중계(외부 서버 관찰). 0 이면 비활성
        self.proxy2_port = int(os.environ.get("MR_PROXY2_PORT", "0"))
        target2 = os.environ.get("MR_PROXY2_TARGET", "")
        h2, _, p2 = target2.partition(":")
        self.proxy2_target = (h2, int(p2)) if (h2 and p2) else None
        # 머큐리 프론트(방 이름 기반 클라이언트 → Multirole). 0 이면 비활성
        self.front_port = int(os.environ.get("MR_FRONT_PORT", "0"))
        target3 = os.environ.get("MR_FRONT_TARGET", "127.0.0.1:7911")
        h3, _, p3 = target3.partition(":")
        self.front_target_host = h3 or "127.0.0.1"
        self.front_target_port = int(p3 or "7911")
        self.list_port = int(os.environ.get("MR_LIST_PORT", "7922"))
        # JOIN 을 보내지 않는 클라이언트를 위해 2초 뒤 방을 대신 개설
        self.front_autocreate = os.environ.get("MR_FRONT_AUTOCREATE", "1") != "0"
        # JOIN 없이 접속하는 클라이언트가 함께 들어갈 고정 방 이름
        self.front_autoroom = os.environ.get("MR_FRONT_AUTOROOM", "lobby")
        # 모든 프레임을 로그에 남긴다(문제 진단용). 평시엔 꺼 둔다.
        self.front_debug = os.environ.get("MR_FRONT_DEBUG", "0") != "0"
        # ── 봇 컨트롤러 (multirole-bot 컨테이너) ──────────────────────────
        # 비밀번호 칸에 bot / b / b:<deck> 을 쓰면 그 방에 WindBot 을 붙인다.
        self.bot_url = (os.environ.get("MR_BOT_URL") or "").strip().rstrip("/")
        self.bot_enabled = bool(self.bot_url) and os.environ.get("MR_BOT_ENABLE", "1") != "0"
        self.bot_deck = (os.environ.get("MR_BOT_DECK") or "raisemoon").strip()
        self.bot_name = (os.environ.get("MR_BOT_NAME") or "Raisemoon").strip()
        # 봇 방(bot / b:<덱>)만 덱 내용 검사를 끈다(봇 덱에 서버 DB 에 없는 카드가 있어도 시작 가능)
        self.bot_nocheck = os.environ.get("MR_BOT_NOCHECK", "1") != "0"
        # ── 방 규칙 기본값 (LAN 클라이언트가 만드는 방) ──────────────────
        # 우선순위: BASE_DEFAULTS < 환경변수(MR_ROOM_*) < front.json(웹 패널)
        persist_dir = os.path.dirname(self.config_persist) if self.config_persist else self.base
        self.front_json = os.environ.get("MR_FRONT_JSON") or os.path.join(persist_dir, "front.json")
        # 관리자 계정(auth.json). 비밀번호는 PBKDF2 해시만 저장
        self.auth_path = os.environ.get("MR_AUTH_FILE") or os.path.join(persist_dir, "auth.json")
        # both(기본) | account | token
        self.auth_mode = (os.environ.get("MR_AUTH") or "both").strip().lower()
        # 리포 갱신 결과(마지막 성공/실패·커밋 목록) — 패널 재시작 후에도 표시
        self.sync_state_path = os.environ.get("MR_SYNC_STATE") or os.path.join(persist_dir, "sync.json")
        self.room_defaults = _env_room_defaults()
        self.room_overrides = {}
        self.load_room_overrides()

    def rel(self, p):
        """Resolve a path from config.json (always relative to base)."""
        if not p:
            return self.base
        if os.path.isabs(p):
            return p
        return os.path.normpath(os.path.join(self.base, p))

    def real_config(self):
        """Follow our own symlink so atomic rename() lands inside the bind mount."""
        try:
            return os.path.realpath(self.config_path)
        except OSError:
            return self.config_path

    # -- 방 규칙 기본값 (웹 패널 연동) ------------------------------------ #
    def load_room_overrides(self):
        """front.json 을 읽어 오버라이드만 남긴다(없거나 깨지면 무시)."""
        try:
            with io.open(self.front_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            self.room_overrides = {}
            return self.room_overrides
        room = data.get("room") if isinstance(data, dict) else None
        clean = {}
        if isinstance(room, dict):
            for key in ROOM_KEYS:
                if key not in room:
                    continue
                got = coerce_room_value(key, room[key])
                if got is not None and got != "":
                    clean[key] = got
        self.room_overrides = clean
        return clean

    def effective_room(self):
        """기본값 + 환경변수 + front.json 오버라이드(런타임 즉시 반영)."""
        from .RoomSpec import BASE_DEFAULTS
        merged = dict(BASE_DEFAULTS)
        merged.update(self.room_defaults)
        merged.update(self.room_overrides)
        return merged

    def save_room_overrides(self, room):
        """front.json 원자적 저장(+.bak-<시각>). 실패하면 OSError."""
        import time as _time
        clean = {}
        for key in ROOM_KEYS:
            if key not in room:
                continue
            got = coerce_room_value(key, room[key])
            if got is not None and got != "":
                clean[key] = got
        path = self.front_json
        dirname = os.path.dirname(path) or "."
        try:
            os.makedirs(dirname, exist_ok=True)
        except OSError:
            pass
        stamp = _time.strftime("%Y%m%d-%H%M%S")
        if os.path.exists(path):
            try:
                shutil.copy2(path, path + ".bak-" + stamp)
            except OSError:
                pass
        tmp = path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump({"room": clean}, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        self.room_overrides = clean
        return clean


def ensure_persist_link(st):
    """Point <CWD>/config.json at the persistent copy inside the bind mount.

    multirole reads ./config.json from its working directory. A single-file bind
    mount cannot be replaced atomically (rename() onto a mount point = EBUSY), so
    the real file lives in the mounted folder and /multirole/config.json is a
    symlink to it. Writes resolve the symlink (real_config) and rename inside the
    mounted directory, which is atomic and survives container recreation.

    Returns True when the link is in place.
    """
    if not getattr(st, "config_persist", ""):
        return False
    target = os.path.abspath(st.config_persist)
    link = os.path.abspath(st.config_path)
    if os.path.realpath(link) == os.path.realpath(target) and os.path.exists(target):
        return True
    if not os.path.exists(target):
        if not (os.path.isfile(link) and not os.path.islink(link)):
            return False
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(link, target)          # seed the persistent copy
        except OSError:
            return False
    try:
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link)
        os.symlink(target, link)
    except OSError:
        return False
    return True
