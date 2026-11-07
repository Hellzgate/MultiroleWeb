## v1.3.3 — 2026-11-07

### 문서
- **`PLAYER-GUIDE.md` 신규** — 관리자가 아닌 **플레이어용** 안내서
  (접속 7914 · 방 이름/비밀번호/규칙 · 봇 대전 · 금제와 덱 규칙 · 매너 · 오류 9종 · 문의)
- README 최상단에 **역할별 문서 안내**(플레이어 / 방 규칙·봇 목록 / 운영자) 추가
- 방 규칙 상세(`MANUAL-room-rules.md`)는 그대로 — 봇 49종 목록·문법 담당

## v1.3.2 — 2026-11-07

### 새 기능
- **봇 방(`bot` / `b:<덱>`)은 `덱 확인하지 않기` 가 자동으로 켜짐** (`MR_BOT_NOCHECK`, 기본 ON)
  - 봇 덱에 서버 카드 DB 에 없는 카드가 섞여 있어도 준비/시작이 막히지 않는다
  - **일반 방은 영향 없음** (전역 기본값 그대로 = 검사함)

### 실측
- ``bot`` 방 → 7922 `no_check: true` · 프론트 로그 `봇 방 → 덱 확인하지 않기 ON`
- ``plain`` 방 → `no_check: false` (기본값 유지)
- `--selftest` 79/79 PASS

# 변경 기록 (Multirole Web Control Panel)

## v1.3.1 — 2026-11-07

### 수정
- **리플레이 목록 = 최신순**: 파일명 내림차순이라 `999 → 99 → 989 …` 로 섞이던 것을
  **수정 시각(`st_mtime`) 내림차순**으로 변경 (같은 시각이면 파일명 내림차순). 목록 200개 제한 유지.
- 봇 컨테이너 문서 보강: `mono:6.12` = Debian buster(EOL) → `archive.debian.org` 전환, `python3`(full) 필요,
  덱 이름 대소문자 유지, WindBot JOIN 은 50바이트라 **프론트 경유 필수** (Bot/Dockerfile 주석 + README)

### 실측
- `/api/replays` 상위: `2202(15:02:12) → 2201(14:56:02) → 2200(00:08:47)` = 최신순 확인
- `--selftest` 79/79 PASS
## v1.3.0 — 2026-11-07

### 새 기능 — **서버 안에서 봇과 대전** (`bot` / `b`)
- `Bot/botd.py` + `Bot/Dockerfile`: **Mono 6.12 + WindBot** 컨테이너(`multirole-bot`). 방 번호로 입장, 방이 사라지면 자동 종료.
- 프론트: 비밀번호 칸이 ``bot`` / ``b`` / ``b:<덱이름>`` 이면 그 방에 봇을 자동 투입 (`App/MercuryFront.py`, `MR_BOT_URL`)
- 봇 카드 DB 는 서버의 `sync/databases/*.cdb` **15개를 `DbPaths` 로 그대로** 사용(병합 파일 불필요)
- 패널 `/api/bot` + 상태줄 `봇 N/2 실행 중 (덱 53개)`
- 메뉴얼 `MANUAL-room-rules.md` **§9 봇과 대전하기** — **부를 수 있는 봇 49종 표** 포함
- 환경변수: `MR_BOT_URL` · `MR_BOT_MAX`(기본 2) · `MR_BOT_DECK` · `MR_BOT_NAME`

### 수정
- **리플레이 목록 = 최신순**(수정 시각 desc). 예전에는 파일명 내림차순이라 `999 → 99 → 989` 처럼 섞였다

### 실측
- Mono 6.12 에서 WindBot 기동 · 15 cdb 로드 · 레이즈문 실행기 · 대사 정상, **CPU 0.24% / RAM 39MB**
- ``bot`` → 2초 내 `Raisemoon` 입장 · ``b:SunGodTimeWizard`` → `SunGodTimeWizard` 입장 · 방 종료 후 **자동 종료 확인**
- 자체검사 79/79 PASS
## v1.2.0 — 2026-11-07

### 새 기능 — 머큐리 프론트 (LAN 클라이언트 → Multirole 방)
- `App/MercuryFront.py` (포트 `7914`): LAN 클라이언트(EDOPro LAN · MDPro4 등)의
  `JOIN_GAME` 한 개를 받아 **방 이름 → 방 번호**로 번역하고, 없으면 방을 **대신 개설**한다.
  - `0x17`(EXTERNAL_ADDRESS) 등 불필요 프레임 제거, `PLAYER_INFO` 만 보내는 클라이언트는
    2초 뒤 기본 방으로 입장(`MR_FRONT_AUTOCREATE`, `MR_FRONT_AUTOROOM`)
  - 방 번호 해석은 `7922 /api/getrooms` 를 **실시간 정본**으로 사용(죽은 번호 재사용 금지)
- `App/RoomSpec.py`: 비밀번호 칸 문법 `이름[#비번][#옵션]` + 방 규칙 빌더
  - 옵션: `l` LP · `h` 패 · `d` 드로우 · `t` 초 · `b` 판수 · `m` 메인 · `x` 엑스트라 ·
    `s` 사이드 · `r` MR · `g` 태그 (`ocg`/`tcg` 토큰). **비밀번호 칸은 19자 제한**
  - 이름 자동 규칙: 정규화(공백→`_`, 19자), `public`/`공개`/`lobby` → 기본 방,
    목록 설명에 비기본 규칙 요약 자동 표기
- `App/Banlists.py`: 금지/제한 목록 스캔 + **해시 계산**(Multirole/EDOPro 와 동일 알고리즘)
  - 패널 드롭다운에서 목록 선택 → 방 생성 시 `HostInfo.banlistHash` 로 전달
  - `/api/lflists.zip` 으로 목록 파일 내려받기(목록이 없는 PC용)

### 새 기능 — 웹 패널
- 「LAN 방 기본값」 카드: LP·패·드로우·시간·판수·MR·덱 장수·허용 카드(5종)·태그·금지목록·덱 검사
  → **재시작 없이 즉시** 적용(`front.json` 원자적 저장 + `.bak`)
- `GET/PUT /api/front`, `GET /api/lflists.zip`
- 📖 초보자용 도움말(접기/펼치기) + `MANUAL-room-rules.md`

### 수정
- **프레임 파서**: 본문 0바이트 패킷(`CTOS_HS_READY` = `01 00 22`)을 쓰레기로 버리던 문제
  (`stored < 2` → `stored < 1`) — `준비` 가 서버에 도달하지 않던 원인
- **소켓 타임아웃**: `create_connection(timeout=15)` 의 15초가 `recv` 에 남아
  **15초 침묵 시 연결이 끊기던** 문제 (`settimeout(None)`)
- **웹 폼 값 저장**: `<select>` 문자열("3")이 저장 단계에서 버려져 매치(BO3)가 단판으로
  만들어지던 문제(`Settings.coerce_room_value`) + 저장 시 전체 값 전송
- **방 중복 개설**: 목록 설명에 규칙 요약이 붙으면서 이름 매칭이 깨지던 문제(이름 부분으로 매칭)
- **잘못된 비밀번호**로 방을 새로 만들던 동작 → 방이 없을 때만 생성
- 마스터 룰 기본값 **MR5(2020, 최신)**, 실제 `DUEL_MODE_MR*` 플래그 전송
  (0 = "표시 안 함"이었고 최신 룰을 보장하지 않았다)
- 허용 카드 **5종**(OCG / TCG / OCG+TCG / +프리릴리즈 / 사용자 정의)
- **덱 확인하지 않기 기본 OFF** — 서버가 덱 장수·금제를 실제로 검사
  (커스텀 카드는 서버 DB/스크립트에 이미 포함됨을 확인)

### 검증
- `--selftest` **79/79 PASS** (방 사양 파서 · 해시 · 저장 정규화 · HTTP 신규 라우트 포함)
- 실기기: EDOPro LAN(`7914`)에서 방 생성 → 준비 → READY 도달, MDPro4 합성 클라이언트 2개 동시 입장
- 방 JSON 실측: `best_of=3`, `duel_flag=0x2E800(MR5)`, `banlist_hash=0x8B6AECDA`, `no_check=false`

## v1.1.0 — 2026-11-07
- 모듈화(App/ 13개 · Web/ 11개), 설정/상태/로그/리플레이 UI, `--selftest` 58/58
- CSS/JS 를 `GET /` 에 인라인(로컬 프록시가 정적 파일 일부를 502 로 끊는 문제 회피)

## v1.0.0 — 2026-11-06
- NAS(DS220+) 최초 배포: 멀티롤 슈퍼바이저(자동 재시작·pty 로그), 설정 원자적 저장,
  상태/로그/리플레이 조회, 토큰 인증
