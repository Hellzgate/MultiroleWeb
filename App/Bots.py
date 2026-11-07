# -*- coding: utf-8 -*-
"""봇 목록 화면 데이터 — botd(/status, /decks) + 로비 방 목록을 **하나**로 합친다.

패널 「봇」 탭이 그대로 그리는 구조:
    running : 실행 중 봇(방 번호·덱·이름·PID·가동시간·로그)
    decks   : 봇 덱 목록(이름·실행 수) — 53개라 화면에서 검색한다
    rooms   : 지금 열려 있는 방(번호·이름·인원·진행 여부·봇 유무)
    default : 기본 덱/이름(MR_BOT_DECK, MR_BOT_NAME)

이 모듈은 IO 를 하지 않는다(호출자가 status/decks/rooms 를 넘긴다) → --selftest 로 검증 가능.
"""


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
        "decks": deck_rows,
        "rooms": room_rows,
    }
