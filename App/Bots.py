# -*- coding: utf-8 -*-
"""봇 목록 화면 데이터 — botd(/status, /decks) + 로비 방 목록을 **하나**로 합친다.

패널 「봇」 탭이 그대로 그리는 구조:
    running : 실행 중 봇(방 번호·덱·이름·PID·가동시간·로그)
    decks   : 봇 덱 목록(이름·실행 수) — 53개라 화면에서 검색한다
    rooms   : 지금 열려 있는 방(번호·이름·인원·진행 여부·봇 유무)
    default : 기본 덱/이름(MR_BOT_DECK, MR_BOT_NAME)

이 모듈은 IO 를 하지 않는다(호출자가 status/decks/rooms 를 넘긴다) → --selftest 로 검증 가능.
"""


# 패널 「봇」 탭의 안내표 — MANUAL-room-rules.md §9 의 (덱, 봇 이름, 난이도).
# 서버에 있는 덱 목록은 botd 가 알려주므로, 여기 있는 것은 **이름/난이도 표시용**이다.
# 새 덱을 넣었는데 이름이 `—` 로 보이면 여기에 한 줄 추가한다.
KNOWN = {
    "[HealingJAM]": ("(실행기 없음 · 일반 엔진)", "—"),
    "[ImaginaryArk]": ("(실행기 없음 · 일반 엔진)", "—"),
    "ABC": ("ABC-드래곤 버스터", "어려움"),
    "Altergeist": ("얼터가이스트", "어려움"),
    "Blackwing": ("[AI] Blackwing (port)", "보통-"),
    "Blue-Eyes": ("푸른 눈의 백룡", "보통"),
    "BlueEyesMaxDragon": ("푸른 눈의 카오스 MAX 드래곤", "보통"),
    "Brave": ("용사 하리파이버", "어려움"),
    "Burn": ("풀 번", "쉬움"),
    "ChainBurn": ("체인 번", "쉬움"),
    "CyberDragon": ("사이버 드래곤", "—"),
    "DarkMagician": ("블랙 매지션", "어려움"),
    "Dogmatika": ("드래그마", "어려움"),
    "Dragun": ("붉은 눈의 드라군", "어려움"),
    "Dragunity": ("드래그니티", "보통"),
    "Evilswarm": ("[AI] Evilswarm (port)", "보통-"),
    "FamiliarPossessed": ("빙의장착", "쉬움"),
    "Frog": ("개구리", "보통-"),
    "Gravekeeper": ("묘지기의", "—"),
    "Graydle": ("[AI] Graydle (port)", "보통-"),
    "GrenMajuThunderBoarder": ("인스펙트 보더 메타비트", "쉬움"),
    "Horus": ("호루스의 흑염룡", "보통-"),
    "Kashtira": ("크샤트리라", "어려움"),
    "Level VIII": ("스크랩 싱크로", "보통"),
    "Lightsworn": ("라이트로드", "—"),
    "LightswornShaddoldinosour": ("공룡 섀도르 라이트로드", "어려움"),
    "Mathmech": ("참기", "보통"),
    "MokeyMokey": ("일반 몬스터 투성이", "보통-"),
    "MokeyMokeyKing": ("일반 몬스터 투성이 II", "보통-"),
    "Nekroz": ("[AI] Nekroz (port)", "보통-"),
    "NekrozRules": ("[AI] Nekroz (편집 가능)", "보통"),
    "OldSchool": ("[AI] OldSchool (port)", "보통"),
    "Orcust": ("오르페골", "어려움"),
    "Phantasm": ("환황룡 메타비트", "쉬움"),
    "PureWinds": ("WW(윈드 위치) 가스타", "보통-"),
    "Qliphort": ("클리포트", "쉬움"),
    "Rainbow": ("레스큐 래빗", "보통"),
    "raisemoon": ("AI_raiseMoon", "어려움"),
    "Rank V": ("랭크 5", "보통"),
    "Salamangreat": ("샐러맨그레이트", "어려움"),
    "SkyStriker": ("섬도희", "어려움"),
    "ST1732": ("AI#ST1732 (사이버스족 굿 스터프)", "보통"),
    "SunGodTimeWizard": ("AI_SunGodTimeWizard", "어려움"),
    "Swordsoul": ("천위 상검", "어려움"),
    "Tearlaments": ("티아라멘츠", "어려움"),
    "ThunderDragon": ("Thunder Dragon", "보통"),
    "Timethief": ("크로노다이버", "보통"),
    "Toadally Awesome": ("떡 깨구리", "보통"),
    "Trickstar": ("트릭스터", "어려움"),
    "Witchcraft": ("위치크래프트 잔디깎기축", "어려움"),
    "Yosenju": ("요선수", "쉬움"),
    "Zexal Weapons": ("ZW(제알 웨폰)", "보통"),
    "Zoodiac": ("십이수", "어려움"),
}


def uptime_text(sec):
    sec = int(sec or 0)
    if sec < 60:
        return "%d초" % sec
    m, s = divmod(sec, 60)
    if m < 60:
        return "%d분 %d초" % (m, s)
    h, m = divmod(m, 60)
    if h < 24:
        return "%d시간 %d분" % (h, m)
    d, h = divmod(h, 24)
    return "%d일 %d시간" % (d, h)


def catalog(decks):
    """덱 목록 → 안내표 행(덱 · 봇 이름 · 난이도 · 부르는 법)."""
    lookup = dict((k.lower(), v) for k, v in KNOWN.items())   # 표기 차이(TimeThief/Timethief) 흡수
    out = []
    for d in sorted(set(x for x in (decks or []) if x), key=lambda x: x.lower()):
        name, diff = lookup.get(d.lower(), ("", ""))
        out.append({
            "deck": d,
            "name": name or "—",
            "difficulty": diff or "—",
            "call": "b:" + d,
            "space": " " in d,          # 공백이 있는 덱은 `b:` 자동 호출에 별도 처리 필요
            "known": d.lower() in lookup,
        })
    return out


def build_view(default_deck, default_name, enabled, status=None, decks=None,
               rooms=None, error=None):
    status = status or {}
    running = []
    used = {}
    for it in status.get("bots") or []:
        deck = it.get("deck") or ""
        used[deck] = used.get(deck, 0) + 1
        sec = int(it.get("uptime") or 0)
        running.append({
            "room": it.get("room"),
            "deck": deck,
            "name": it.get("name") or deck,
            "pid": it.get("pid"),
            "alive": bool(it.get("alive")),
            "uptime": sec,
            "uptimeText": uptime_text(sec),
            "log": it.get("log") or "",
        })
    running.sort(key=lambda x: (x["room"] if isinstance(x["room"], int) else 0))

    busy = set(r["room"] for r in running)
    room_rows = []
    for r in rooms or []:
        rid = r.get("id")
        deck = next((x["deck"] for x in running if x["room"] == rid), "")
        room_rows.append({
            "id": rid,
            "notes": r.get("notes") or "",
            "users": r.get("users") or [],
            "started": bool(r.get("started")),
            "bot": deck,
            "free": rid not in busy,
        })

    names = sorted(set(d for d in (decks or []) if d))
    deck_rows = [{"name": n, "running": used.get(n, 0)} for n in names]
    for n in sorted(used):                      # 목록에 없는 덱(파일이 지워짐)도 실행 중이면 표시
        if n not in names:
            deck_rows.append({"name": n, "running": used[n], "missing": True})

    return {
        "enabled": bool(enabled),
        "error": error,
        "windbot": bool(status.get("windbot")),
        "max": int(status.get("max") or 0),
        "default": {"deck": default_deck or "", "name": default_name or ""},
        "running": running,
        "catalog": catalog(decks),
        "decks": deck_rows,
        "rooms": room_rows,
    }
