# -*- coding: utf-8 -*-
"""방 이름 / 비밀번호 / 규칙 파서 (머큐리 프론트용).

LAN 클라이언트(EDOPro · MDPro4)는 `CTOS_JoinGame` 에 **40바이트 필드 하나**만 보낸다
(방 이름 필드가 따로 없다). 그래서 그 필드를 다음 문법으로 해석한다.

    <방이름>[#<비밀번호>][#<옵션,옵션,…>]

    mtg                      → 방 'mtg'
    mtg#1234                 → 방 'mtg' + 비밀번호 1234
    mtg#1234#l=4000,t=300    → 방 'mtg' + 비밀번호 1234 + 시작 LP 4000 · 300초  (19자 제한!)
    #lp=4000                 → 기본방('lobby') + LP 4000 (이름 없이 옵션만)

    옵션(쉼표 구분, k=v)
      lp=4000        시작 LP            (100~40000)
      hand=5         시작 패            (1~10)
      draw=1         턴당 드로우        (1~10)
      time=300       제한 시간(초)      (30~6000)
      best=3        3판 2선승           (1|3)
      main=40-60     메인 덱 장수 범위   (단일 숫자면 최소값)
      extra=0-15     엑스트라 범위
      side=0-15      사이드 범위
      mr=3           마스터 룰          (0~5, 0=표시 안 함)
      mode=ocg|tcg   허용 카드
      tag=1          태그 듀얼(2:2)

규칙 기본값은 환경변수(`MR_ROOM_*`) 또는 웹 패널(`front.json`)에서 바꿀 수 있다.
"""

import struct

# 기본값 — Settings.room_defaults 가 이 값을 덮어쓴다(웹 패널/환경변수).
BASE_DEFAULTS = {
    "default_room": "lobby",
    "lp": 8000,
    "hand": 5,
    "draw": 1,
    "time": 180,
    "best": 1,
    "mr": 5,          # 5 = Master Rules (2020) = 최신
    "mode": "ocg",
    "main_min": 40,
    "main_max": 60,
    "extra_min": 0,
    "extra_max": 15,
    "side_min": 0,
    "side_max": 15,
    "tag": 0,
    # 금지/제한 목록 선택자("<파일>|<섹션>"), 빈 값 = 사용 안 함(N/A)
    "banlist": "",
    # 0 = 서버가 덱을 검사(기본), 1 = 검사 안 함(서버 DB에 없는 커스텀 카드용)
    "nocheck": 0,
}

# 이름 별칭 — 자주 쓰는 "공개방" 표현은 기본방으로 모은다.
NAME_ALIASES = {
    "public": None,
    "open": None,
    "공개": None,
    "로비": None,
    "lobby": None,
    "default": None,
}

MODE_CODES = {"ocg": 0, "tcg": 1, "both": 2, "pre": 3, "any": 4}
MODE_LABELS = {
    0: "OCG",
    1: "TCG",
    2: "OCG+TCG",
    3: "OCG+TCG+프리릴리즈",
    4: "사용자 정의",
}

# 마스터 룰 플래그 (ygopro ocgapi_constants.h 의 DUEL_MODE_MR1..MR5 를 그대로 옮긴 값)
#   MR1 0xD0700 = OCG_OBSOLETE_IGNITION|1ST_TURN_DRAW|1_FACEUP_FIELD|SPSUMMON_ONCE_OLD_NEGATE|RETURN_TO_DECK_TRIGGERS|CANNOT_SUMMON_OATH_OLD
#   MR2 0xD0600 = 위에서 OCG_OBSOLETE_IGNITION 제외
#   MR3 0xD1800 = PZONE|SEPARATE_PZONE|…
#   MR4 0xD2800 = PZONE|EMZONE|…
#   MR5 0x2E800 = PZONE|EMZONE|FSX_MMZONE|TRAP_MONSTERS_NOT_USE_ZONE|TRIGGER_ONLY_IN_LOCATION  ← 최신(2020)
MR_FLAGS = {1: 0x0D0700, 2: 0x0D0600, 3: 0x0D1800, 4: 0x0D2800, 5: 0x02E800}
MR_LABELS = {0: "표시 안 함", 1: "MR1", 2: "MR2", 3: "MR3", 4: "MR4", 5: "MR5 (2020, 최신)"}
MAX_NAME_CHARS = 19          # pass 필드는 UTF-16 20단위(40B) → 널 1개 빼고 19자
MAX_PASS_CHARS = 19          # 비밀번호 칸 전체(이름+비번+옵션)도 19자까지

INT_RANGES = {
    "lp": (100, 40000),
    "hand": (1, 10),
    "draw": (1, 10),
    "time": (30, 6000),
    "best": (1, 3),
    "mr": (0, 5),
    "tag": (0, 1),
}

KEY_ALIASES = {
    "startlp": "lp", "start_lp": "lp", "lifepoints": "lp",
    "start": "hand", "handsize": "hand", "start_hand": "hand",
    "drawcount": "draw", "draw_count": "draw",
    "timelimit": "time", "limit": "time",
    "bestof": "best", "best_of": "best",
    "masterrule": "mr", "master_rule": "mr",
    "duelrule": "mr",
    "team": "tag",
    "defaultroom": "default_room", "room": "default_room",
    # 짧은 키 — 비밀번호 칸이 19자뿐이라 길이를 아끼려고 둔다
    "l": "lp", "h": "hand", "d": "draw", "t": "time", "b": "best",
    "m": "main", "x": "extra", "s": "side", "r": "mr", "g": "tag",
}

# '=' 없이 쓰는 토큰
BARE_TOKENS = {"ocg": ("mode", "ocg"), "tcg": ("mode", "tcg"), "tag": ("tag", 1)}


def utf16_fixed(text, slot_bytes):
    """고정 크기 UTF-16LE 필드(널 패딩). 40B = 20단위."""
    raw = text.encode("utf-16-le")[: max(0, slot_bytes - 2)]
    return raw + b"\x00" * (slot_bytes - len(raw))


def frame(msg_type, body):
    """길이 필드 = body + 1 (Multirole GetLength() == sizeof(struct))."""
    return struct.pack("<H", len(body) + 1) + bytes([msg_type]) + body


def normalize_name(text, base):
    """표시/매칭용 방 이름 정규화.

    - 제어문자 제거, 공백/연속 공백 → '_'
    - 비었거나 별칭(public/공개/lobby …)이면 기본방 이름
    - 19자 제한(프로토콜 필드 크기)
    """
    fallback = (base.get("default_room") or "lobby").strip() or "lobby"
    raw = "".join(ch for ch in (text or "") if ch.isprintable()).strip()
    if not raw:
        return fallback
    if raw.lower() in NAME_ALIASES:
        return fallback
    cleaned = "_".join(raw.split())
    if not cleaned:
        return fallback
    return cleaned[:MAX_NAME_CHARS]


def _to_int(text, lo, hi, current):
    try:
        value = int(str(text).strip())
    except (TypeError, ValueError):
        return None
    if value < lo or value > hi:
        value = max(lo, min(hi, value))
    return value


def _pair(text, key, opts):
    """main=40-60 / main=50 / main=40,60 형태를 (min,max) 로."""
    lo_key, hi_key = key + "_min", key + "_max"
    raw = str(text).strip().replace(":", "-").replace(",", "-")
    if "-" in raw:
        left, _, right = raw.partition("-")
        if left.strip().isdigit():
            opts[lo_key] = max(0, min(60, int(left)))
        if right.strip().isdigit():
            opts[hi_key] = max(0, min(60, int(right)))
        return
    if raw.isdigit():
        opts[lo_key] = max(0, min(60, int(raw)))


def _parse_options(segment, opts, warnings):
    for token in segment.replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            bare = BARE_TOKENS.get(token.lower())
            if bare:
                opts[bare[0]] = bare[1]
            else:
                warnings.append("옵션 형식 아님(무시): %s" % token)
            continue
        key, _, value = token.partition("=")
        key = key.strip().lower()
        key = KEY_ALIASES.get(key, key)
        value = value.strip()
        if key in ("main", "extra", "side"):
            _pair(value, key, opts)
            continue
        if key == "mode":
            mode = value.lower()
            if mode in MODE_CODES:
                opts["mode"] = mode
            elif mode in ("all", "custom", "커스텀", "사용자정의"):
                opts["mode"] = "any"
            else:
                warnings.append("알 수 없는 mode=%s (ocg/tcg/both/pre/any)" % value)
            continue
        if key == "default_room":
            opts["default_room"] = normalize_name(value, {"default_room": "lobby"})
            continue
        if key in INT_RANGES:
            lo, hi = INT_RANGES[key]
            got = _to_int(value, lo, hi, None)
            if got is None:
                warnings.append("숫자가 아님(무시): %s=%s" % (key, value))
            else:
                opts[key] = got
            continue
        warnings.append("알 수 없는 옵션(무시): %s" % key)


def parse(text, base=None):
    """비밀번호 칸 문자열 → 방 사양.

    반환 dict
        name      방 이름(정규화)
        password  비밀번호('' 가능)
        opts      기본값 위에 덮어쓴 규칙
        notes     서버 목록에 표시할 설명(이름 + 비기본 규칙 요약)
        warnings  무시된 옵션 안내
    """
    base = dict(BASE_DEFAULTS, **(base or {}))
    text = (text or "").strip()
    warnings = []
    if len(text) > MAX_PASS_CHARS:
        warnings.append("비밀번호 칸은 %d자까지입니다(%d자 잘림) — 옵션은 웹 패널 기본값 권장"
                        % (MAX_PASS_CHARS, len(text)))
        text = text[:MAX_PASS_CHARS]
    parts = text.split("#")
    name_raw = parts[0] if parts else ""
    password = ""
    opts = {}

    for seg in parts[1:]:
        seg = seg.strip()
        if not seg:
            continue
        if ("=" in seg) or ("," in seg) or (";" in seg):
            _parse_options(seg, opts, warnings)
        elif not password:
            password = seg
        else:
            _parse_options(seg, opts, warnings)

    for key, value in list(opts.items()):
        if key == "default_room" and not name_raw.strip():
            base["default_room"] = value
    name = normalize_name(name_raw, base)

    merged = dict(base)
    merged.update({k: v for k, v in opts.items() if k != "default_room"})
    return {
        "name": name,
        "password": password,
        "opts": merged,
        "base": {k: base[k] for k in BASE_DEFAULTS if k in base},
        "notes": describe(name, merged, base),
        "warnings": warnings,
    }


def describe(name, opts, base):
    """서버 방 목록(7922 roomnotes)에 쓸 설명 — 기본값과 다른 것만 붙인다."""
    tail = []
    if opts.get("lp") != base.get("lp"):
        tail.append("LP%s" % opts.get("lp"))
    if opts.get("hand") != base.get("hand"):
        tail.append("패%s" % opts.get("hand"))
    if opts.get("draw") != base.get("draw"):
        tail.append("드로우%s" % opts.get("draw"))
    if opts.get("time") != base.get("time"):
        tail.append("%s초" % opts.get("time"))
    if opts.get("best") != base.get("best"):
        tail.append("%s판" % opts.get("best"))
    if (opts.get("main_min"), opts.get("main_max")) != (base.get("main_min"), base.get("main_max")):
        tail.append("덱%s-%s" % (opts.get("main_min"), opts.get("main_max")))
    if (opts.get("extra_min"), opts.get("extra_max")) != (base.get("extra_min"), base.get("extra_max")):
        tail.append("엑%s-%s" % (opts.get("extra_min"), opts.get("extra_max")))
    if (opts.get("side_min"), opts.get("side_max")) != (base.get("side_min"), base.get("side_max")):
        tail.append("사이드%s-%s" % (opts.get("side_min"), opts.get("side_max")))
    if opts.get("mr") != base.get("mr"):
        tail.append(MR_LABELS.get(opts.get("mr"), "MR%s" % opts.get("mr")))
    if opts.get("mode") != base.get("mode"):
        tail.append(MODE_LABELS.get(MODE_CODES.get(opts.get("mode"), 0), str(opts.get("mode"))))
    if opts.get("tag") != base.get("tag"):
        tail.append("태그")
    text = name if not tail else "%s (%s)" % (name, " · ".join(tail))
    raw = text.encode("utf-8")[:199]
    return raw.decode("utf-8", "ignore")


def build_create_game(spec, handshake, client_ver, core_ver, banlist_hash=0):
    """방 사양 → CTOS_CREATE_GAME (348B body)."""
    opts = spec["opts"]
    hi = bytearray(68)
    struct.pack_into("<I", hi, 0, banlist_hash & 0xFFFFFFFF)   # lflist(banlist hash) - 0 = N/A
    hi[4] = MODE_CODES.get(opts.get("mode"), 0)           # rule(OCG/TCG)
    hi[5] = 0                                             # mode
    hi[6] = opts.get("mr", 0)                             # duel_rule
    hi[7] = 1 if opts.get("nocheck", 0) else 0            # no_check_deck_content
    hi[8] = 0                                             # no_shuffle_deck
    struct.pack_into("<I", hi, 12, opts.get("lp", 8000))
    hi[16] = opts.get("hand", 5)
    hi[17] = opts.get("draw", 1)
    struct.pack_into("<H", hi, 18, opts.get("time", 180))
    flags = MR_FLAGS.get(opts.get("mr", 0), 0)
    struct.pack_into("<I", hi, 20, (flags >> 32) & 0xFFFFFFFF)   # duel_flag_high
    struct.pack_into("<I", hi, 24, handshake)
    hi[28], hi[29], hi[30], hi[31] = client_ver[0], client_ver[1], core_ver[0], core_ver[1]
    teams = 2 if opts.get("tag") else 1
    struct.pack_into("<i", hi, 32, teams)                 # team1
    struct.pack_into("<i", hi, 36, teams)                 # team2
    struct.pack_into("<i", hi, 40, opts.get("best", 1))   # best_of
    struct.pack_into("<I", hi, 44, flags & 0xFFFFFFFF)   # duel_flag_low (MR 플래그)
    struct.pack_into("<i", hi, 48, 0)                     # forbiddentypes
    struct.pack_into("<H", hi, 52, 0)                     # extra_rules
    struct.pack_into("<HH", hi, 54, opts.get("main_min", 40), opts.get("main_max", 60))
    struct.pack_into("<HH", hi, 58, opts.get("extra_min", 0), opts.get("extra_max", 15))
    struct.pack_into("<HH", hi, 62, opts.get("side_min", 0), opts.get("side_max", 15))
    body = (bytes(hi) + utf16_fixed(spec["name"], 40) + utf16_fixed(spec["password"], 40)
            + spec["notes"].encode("utf-8")[:199].ljust(200, b"\x00"))
    return frame(0x11, body)


def build_join(room_id, password, client_ver, core_ver):
    """Multirole JOIN_GAME (52B): version2(2) | pad(2) | id(4) | pass(40) | ClientVersion(4)."""
    body = (struct.pack("<H", 0) + b"\x00\x00" + struct.pack("<I", room_id)
            + utf16_fixed(password or "", 40)
            + bytes([client_ver[0], client_ver[1], core_ver[0], core_ver[1]]))
    return frame(0x12, body)
