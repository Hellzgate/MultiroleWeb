## v1.7.0 — 2026-11-07

### 새 기능 — 접속 IP 확인 (실IP + 멀티롤 별칭)
- **실제 IP** 를 프론트가 알고 있으므로 방 목록에 그대로 표시:
  `GET /api/rooms` → `rooms[].ips` · 설정 탭 「접속 IP」 열
- **멀티롤에도 클라이언트별 주소**를 보여준다 — 업스트림 소켓을 `127.0.a.b` **별칭**에 바인딩
  (`MercuryFront.pseudo_ip()`, 실IP 해시 → **같은 사람은 항상 같은 별칭**, 충돌 시 선형 재할당)
  - 7914 단일화로 멀티롤이 모든 접속을 `127.0.0.1` 로 보던 문제 해결 → **방장 kick 의 IP 차단이 개인별로 동작**
  - 별칭은 `127.0.1.x ~ 127.0.254.x` 만 사용(`127.0.0.1` 회피), 바인딩 실패 시 일반 연결로 폴백
- **접속 이력 로그** `App/AccessLog.py` → `logs/access.log` (JSONL, 20MB × 10개 · 30일)
  ```json
  {"ts":"2026-11-07T20:08:22","ev":"connect","ip":"114.200.216.10","pseudo":"127.0.188.35"}
  {"ts":"2026-11-07T20:08:22","ev":"create","ip":"114.200.216.10","pseudo":"127.0.188.35","room":1,"name":"..."}
  {"ts":"2026-11-07T20:08:23","ev":"close","ip":"114.200.216.10","pseudo":"127.0.188.35","room":1,"why":"closed"}
  ```
  이벤트: `connect` · `join` · `create` · `close` · `kick` · 조회 `GET /api/access?tail=100&ip=&room=`
- 설정 탭 「지금 열려 있는 방」 아래 **📋 접속 이력**(최근 100건, 실IP/별칭/방/이름/사유) 표시

### 실측 (운영 서버)
```
프론트가 본 피어      127.0.0.1:47644        (테스트는 컨테이너 내부에서 접속)
멀티롤이 본 피어      ::ffff:127.0.188.35    ← 별칭 IP (127.0.0.1 아님)
access.log            connect/create/close 3줄, ip=127.0.0.1 pseudo=127.0.188.35
--selftest            118/118 (access.roundtrip/filter/rotate, front.pseudo, http.access)
```

## v1.6.0 — 2026-11-07

### 새 기능 — 유령 방 자동 정리 (`App/GhostRooms.py`)
- **문제**: 사람이 끊겨도 **봇은 방이 목록에 있는 한 계속 대기**한다. Multirole 은 사용자가 **0명**일 때만 방을 닫으므로,
  `[봇 혼자 남은 방]` 이 영원히 남았다(방을 닫으려면 재시작뿐).
- **해결**: 10초마다 로비를 훑어 **사람 세션이 0인 봇 방**을 찾아
  ① 남은 세션을 끊고(kick) ② 봇을 중지(stop) → 사용자 0 → Multirole 이 방을 닫는다.
  - 프론트가 방 번호별 세션 수를 추적(`MercuryFront.session_counts()` / `kick_room()`)
  - `classify()` 는 순수 함수 → `--selftest` 로 검증
  - 유예시간 기본 **90초**(`MR_GHOST_TIMEOUT`), 자동 정리 스위치 `MR_GHOST_AUTO`(기본 1)
  - 프론트를 거치지 않은(직결) 방은 **건드리지 않는다**(사람일 수 있으므로) → `unknown`
- **수동 정리**: `POST /api/rooms/close {"roomId":N}` · 설정 탭 방 목록에 **[방 닫기]** + `유령` 배지
- ⚠ **오탐 방지**: 사람 세션을 **한 번도 못 본 방**은 대상에서 제외한다(직결 7911 사용자를 봇만 남은 방으로 오판 금지).
- ℹ **소스 확인**: Multirole 은 `Waiting.cpp` 의 `ConnectionLost` 에서 **방장(host)이 끊기면 방을 즉시 닫는다**
  (`return State::Closing{}`). 그래서 '봇만 남은 방'은 **프론트 세션이 끝났는데도 방이 살아 있는 비정상 상태**에서만 생긴다.
  → 주 방어선은 keepalive/watchdog 이고, 이 정리는 **보조 안전망 + 수동 버튼**이다.
- `GET /api/rooms` 에 `humans`(사람 세션 수) · `bot`(덱) · `ghost`(자동 정리 대상) 추가

### 운영 방침 — 접속은 **7914 하나로**
- 유령 방 보호(keepalive·watchdog·정리)는 **프론트를 거치는 경로에서만** 동작한다.
- `duelport 7911` 직결은 multirole 이 소켓을 직접 들고 있어 외부에서 끊을 수 없다 → **7914 로 통일**.
- 부작용: multirole 이 보는 접속 IP 가 `127.0.0.1` 이 된다(방장 kick 시 그 방에서 IP 차단 가능, 방이 닫히면 해제).

### 검증
- `--selftest` **113/113** (추가: `ghost.classify` · `ghost.no-human-seen` · `ghost.after-timeout` · `ghost.human-present` · `ghost.close-room` · `http.rooms-ghost`)
- **실서버 E2E**: 합성 클라이언트(7914 JOIN 'ghosttest') → 방 생성(id=1) → 봇 `raisemoon` 2초 만에 입장(users 2명)
  → 클라이언트 FIN 종료 → **5초 뒤 방·봇 모두 사라짐**(방장 이탈 = 방 즉시 폐쇄, 봇도 자동 종료).

## v1.5.4 — 2026-11-07

### 새 기능 — 「봇」 탭에 **봇 부르는 법** 안내 붙임 (사용자 요청)
- 「봇」 탭 맨 아래에 **메뉴얼 §9 를 그대로** 옮긴 카드 추가
  - 입력 표: `bot` / `b` · `b:<덱>` · `bot#1234` · `b:ABC#1234` (LAN = 비밀번호 칸, 서버모드 = `Notes` 칸)
  - **덱 · 봇 이름 · 난이도 · 부르는 법** 표 — 목록은 서버(`botd /decks`)에서 오고, 이름/난이도는 매뉴얼 값
  - 표 전용 **검색**(덱·봇 이름) · `N / 53개` 표시
  - 주의: 최대 2마리, 방 사라지면 10초 내 종료, 봇 방은 덱 검사 자동 OFF, 없는 덱은 봇만 안 옴
- 표는 **동적**이다 — 덱을 추가/삭제하면 자동 반영(매뉴얼에 없는 덱은 `— (매뉴얼에 없음)`).

### 수정 — 공백 있는 덱 이름도 `b:` 로 부를 수 있게
- `b:Rank V` / `b:Toadally Awesome` 처럼 **공백이 있는 덱**은 정규식(`[A-Za-z0-9_-]+`)에 걸리지 않아 자동 호출이 안 됐다.
- 프론트가 봇 덱 목록(60초 캐시)과 대조해 한 번 더 인식하고, **대소문자만 달라도 실제 덱 이름으로 맞춘다**.
- `b:abc` → `ABC`, `b:TimeThief` → `Timethief` 처럼 동작.

### 문서
- `MANUAL-room-rules.md` §9: 제목 `49종` → **`서버에 있는 덱 기준 · 53개`**, `Lucky`(덱 파일 없음) 제외,
  NAS 에만 있던 5개(`CyberDragon`·`Gravekeeper`·`Lightsworn`·`[HealingJAM]`·`[ImaginaryArk]`) 추가,
  표기 정정(`Mathmech`·`Timethief`), 공백/대소문자 안내 추가.

### 검증
- `--selftest` **107/107 PASS** (추가: `bots.catalog` · `front.bot-trigger`)
- `/api/bots` → `catalog 53개 · known 53 · 공백 4개(Level VIII, Rank V, Toadally Awesome, Zexal Weapons)`

## v1.5.2 — 2026-11-07

### 다듬기 — 로그인 문구 (동작 변화 없음)
- 로그인 화면: `NAS 관리자 계정으로 로그인하세요.` → **`패널 관리자 계정으로 로그인하세요.`**
  - DSM 계정으로 오해할 수 있었다. 실제로는 `auth.json` 의 **패널 전용 계정**(id 는 만든 사람이 정함)이다.
- 계정 만들기 화면 제목도 `패널 관리자 계정 만들기` 로, 안내문에서 DSM 비교 문구는 **넣지 않는다**(사용자 요청).
- README 로그인 절도 같은 표현으로 정리.

## v1.5.0 — 2026-11-07

### 새 기능 — 「봇」 탭 (봇 목록 · 덱 검색 · 방에 투입/중지)
- 새 탭 **봇** — 설정 탭에 흩어져 있던 "방마다 덱 입력 + 투입" 을 한 화면으로 모았다.
  - **실행 중** 표: 방 번호 · 덱 · 봇 이름 · PID · 가동시간 · 상태 · 로그 파일 + [중지]
  - **새 봇 투입**: 방 목록(번호·이름·인원·진행 여부·이미 봇이 있으면 표시) → **덱 이름 검색**(53개) → [투입]
    - 봇은 입장 → 덱 선택 → 준비(Ready)까지 자동, 기본 이름은 `MR_BOT_NAME`(기본 덱) 또는 덱 이름
    - 목록에서 **더블클릭**으로도 투입
  - [전체 중지] — 확인 모달 후 `botd /stopall`
  - 네비의 **봇 N** 배지 = 실행 중 개수
- API: `GET /api/bots` (botd `/status` + `/decks` + 로비 7922 목록을 **한 번에** 병합) · `POST /api/bot/stopall`

### 수정 — 로비에 남던 **유령 방** (세션 소켓 누수)
- 증상: 클라이언트를 닫았는데 방이 계속 목록에 남고 봇도 대기(`users=ComicLO,<봇>`, 사람은 이미 없음).
- 원인(실측): 프론트의 클라이언트 소켓이 **CLOSE_WAIT**(상대는 FIN, 우리는 close 안 함)인데
  7911 업스트림은 **ESTABLISHED** 로 살아 있어 Multirole 이 사용자를 계속 유지했다.
  - 펌프 스레드가 `OSError` 가 아닌 예외(프레임 파싱 등)로 죽으면 `_close()` 를 **건너뛰는** 구조였다.
  - half-open(전원/네트워크 끊김)은 커널 기본(약 2시간)까지 남는다.
- 수정 (`MercuryFront.py` · `DuelProxy.py`)
  - **keepalive** — `SO_KEEPALIVE` + `TCP_KEEPIDLE 60` / `KEEPINTVL 15` / `KEEPCNT 4` (≈105초 내 정리)
  - **어떤 예외든 close** — `except Exception` + `_handle` 의 `finally`
  - **CLOSE_WAIT 감시** — 5초마다 `/proc/net/tcp` 로 소켓 상태를 보고 10초 이상 방치면 강제 종료(`stale socket → 강제 종료`)
- 검증: 접속→FIN 시 `connected / client closed / closed` 로그 + `TIME_WAIT` 만 남음(CLOSE_WAIT·ESTAB 0)
  · 재시작 후 **방 0개** · 봇 자동 종료(`bots: []`)

### 검증
- `--selftest` **105/105 PASS** (추가: `bots.view` · `http.bots` · `http.static-bot-panel` · `front.keepalive` · `front.close-always` · `front.watchdog` · `proxy.keepalive` · `front.conn-state`)

## v1.4.3 — 2026-11-07

### 다듬기 — 갱신 결과 화면/로그 정리 (동작 변화 없음)
- **로그는 실패할 때만** 표시 — 정상·무변경 리포는 `Webhook triggered.` / `Finished updating.` 를 감춘다(화면이 짧아짐)
- 결과 카드의 숫자도 의미 있게 — 변경된 리포만 `N 커밋 · M 파일`, 무변경은 `이미 최신 · 5.8초`
- **로그 순서/중복 정리**
  - 갱신 구간이 **줄 중간**에서 시작하면 앞 조각을 버린다(자식이 늦게 flush 해 `Finished updating.` 이 `Webhook triggered.` **앞에** 보이던 문제)
  - 첫 `Webhook triggered.` 이전 줄은 이전 갱신 잔여분이라 버리고, 같은 메시지는 한 번만 남긴다

### 실측
- `--selftest` **97/97 PASS** (로그 경계·순서·중복 검사 2건 추가) · 렌더 단위검사 13/13

## v1.4.2 — 2026-11-07

### 새 기능 — 저장소 **전체 갱신** + 갱신 결과/실패 로그 표시
- 상태 탭에 **[전체 갱신]** 버튼 → `POST /api/sync`(이름 없이) = **모든 리포를 순서대로** 갱신
  - 리포별 [갱신] 버튼은 그대로(이름 지정)
  - 응답: `{ ok, all, summary{total,changed,failed,durationMs,at}, results[ {name, ok, changed, from, to, head, commitCount, commits[], fileCount, files[], durationMs, error, log[]} ] }`
- **무엇이 갱신되었는지** 표시
  - 갱신은 `웹훅(= git fetch + reset)` 이므로 **전/후 HEAD 비교**로 변경 여부 판정(같으면 "변경 없음")
  - 바뀌면 이전→새 해시, **커밋 목록(메시지)** 과 **변경 파일 목록**(`git log` / `git diff --name-status`)
  - 결과 카드에 리포별로 표시(커밋 20개·파일 8개까지, 나머지는 "외 N개")
- **실패도 로그로**
  - 웹훅은 오류여도 200 을 돌려주므로, multirole 자식 로그의 갱신 구간(`[Service:GitRepository] [Level:Error] …`)을 읽어 사유 표시
  - 실패는 빨간 배너 + 결과 카드(빨간 테두리) + 패널 로그(`sync 'scripts' FAILED: …`)에 남김
- 리포 표에 **마지막 갱신 시각/결과** 열 추가(`sync.json` 에 저장 → 패널 재시작 후에도 유지)
- `GET /api/status` 에 `repos[].lastSync` · `sync.lastAll` 추가

### 함정 (실측)

- multirole 웹훅은 요청의 **첫 256바이트**에서만 토큰을 찾는다(`Webhook::Connection::DoReadHeader`).
  본문(`token=...`)만 보내면 헤더/본문이 다른 TCP 세그먼트로 갈 때 **간헐적으로 "Webhook payload does not have a token"** → 갱신 실패.
  → 토큰을 **URL 경로에도** 넣고(`POST /<token>`), 그래도 토큰 오류면 **1회 재시도**한다.
- 웹훅은 오류여도 **HTTP 200** 을 돌려준다 → 실패 판정은 자식 로그(`[Service:GitRepository] [Level:Error]`)로만 가능.
- `repos` 에 `file://` 이 아닌 경로를 쓰면 컨테이너에 **마운트된 경로**여야 한다(`/multirole/sync/...` 만 보임).

### 이미지
- `apk add git` — 커밋/파일 목록을 정확히 얻기 위해 **git CLI** 를 포함(이미지 59.7MB → **72.1MB**)
  - 없으면 HEAD 변화와 파일 mtime 추정만 가능하므로 커밋 메시지를 못 보여준다.

### 실측
- `--selftest` **95/95 PASS** (sync 8건 추가: HEAD 읽기·상태 저장·로그 파싱·mtime·실패 보고·HTTP 전체 갱신·상태 반영)

## v1.4.1 — 2026-11-07

### 추가
- **`tools/backup.ps1`** — 백업을 스크립트로 고정
  - 소스 ZIP 은 **폴더 구조 유지**(`ZipFile.CreateFromDirectory`) · 제외: `_web_token.txt` / `front.json` / `auth.json` / `NAS-ACCESS.md`
  - 문서(README·CHANGELOG·MANUAL·PLAYER-GUIDE·UPGRADE) 함께 복사
  - **`auth.json` 은 ZIP 밖**(`_backups\<ver>\auth.json`)에만 보관 — 로컬 백업 전용, git·릴리스 제외
  - `SHA256.txt` 자동 생성
- 사용: `powershell -File .\tools\backup.ps1 [-Version 1.4.1] [-AuthFile <auth.json 경로>]`

### 실측
- v1.4.0 백업 재생성: ZIP 58 엔트리(116,535B) · `auth.json` 308B(ZIP 미포함) · SHA256 8항목
- `--selftest` 87/87 PASS

## v1.4.0 — 2026-11-07

### 새 기능 — **관리자 계정 로그인** (웹 토큰 대신)
- **첫 접속**에 “관리자 계정 만들기”(아이디·비밀번호·확인) → 이후 그 계정으로 로그인
  - 비밀번호는 **PBKDF2-SHA256(200k)** 해시로만 저장(`auth.json`), 평문 저장 없음
  - 세션 쿠키 `mr_session` = `아이디.만료.HMAC` (12시간, HttpOnly) → 매 요청 해시 비교 없음
  - **실패 5회 → 60초 잠금**(IP 단위), 로그에 실패 기록
  - 헤더에 **[로그아웃] · [비밀번호]** 버튼
- **비상용 WEB_TOKEN 유지** — 로그인 화면의 “토큰으로 들어가기”(접이식). `MR_AUTH=both|account|token`(기본 both)
- **복구**: `python3 webui.py --reset-auth` (또는 `auth.json` 삭제) → 다음 접속에 계정 만들기 화면
- API: `GET /api/account` · `POST /api/setup` · `POST /api/login`(계정/토큰) · `POST /api/logout` · `POST /api/password`

### 보관 규칙
- `auth.json` 은 **저장소에 올리지 않는다**(`.gitignore`) — 로컬 백업에만 보관.
- 릴리스 ZIP 에도 넣지 않는다(해시·세션 서명키 노출 방지).

### 실측
- `--selftest` **87/87 PASS** (계정 생성·검증·세션·비번 변경·잠금·초기화 7건 추가)

## v1.3.8 — 2026-11-07

### 수정 (서버 대전 모드 + `duelport 7914`)
- **방금 만든 방에 즉시 입장 실패**: 서버모드 입장은 방 번호를 보내는데, 프론트가 7922 목록(2초 지연)에서
  번호를 확인하려다 실패해 **새 방을 만들던** 문제 → **클라이언트가 준 방 번호를 그대로 신뢰**하도록 변경.
- **잘못된 번호로 입장할 때 방 생성 금지**: 서버모드 입장이 실패(`ROOM_NOT_FOUND`)하면
  기존에는 기본 이름으로 방을 새로 만들었으나, 이제 **만들지 않고** 클라이언트에 오류를 그대로 전달.

### 실측
- 7911 로 방 생성 → **0.3초 뒤** 7914 로 그 번호 입장 → `JOIN·ENTER` 성공(같은 방, 사용자 2명)
- 잘못된 번호(`999`) → `안내 + ERR(0x9000000)`, **새 방 생성 없음**
- `--selftest` 79/79 PASS

## v1.3.7 — 2026-11-07

### 새 기능
- **패널 「지금 열려 있는 방 — 봇 즉시 투입」**: 웹 패널에서 현재 방 목록(번호·Notes·인원·상태)을 보고
  **덱 이름을 적어 [봇 투입]** / [중지] 할 수 있다.
  - **서버 대전 모드로 7911 에 직접 만든 방**처럼 프론트를 거치지 않은 방에도 봇을 붙일 수 있다
- API: `GET /api/rooms` · `POST /api/bot/start {roomId, deck}` · `POST /api/bot/stop {roomId}`
- 봇 이름: 기본 덱이면 `MR_BOT_NAME`, 다른 덱이면 **덱 이름**으로 표시

### 실측
- 7911 직결 방(`Notes='b:Tearlaments'`) → `/api/bot/start` → **+2초** `users=['SrvBoss','Raisemoon']`
- `--selftest` 79/79 PASS

## v1.3.6 — 2026-11-07

### 새 기능
- **서버 대전 모드에서도 봇 호출**: 방 만들기 창의 **`Notes`(설명)** (또는 `Host Name`)에 `bot` / `b:<덱>` 을 적으면
  그 방에 WindBot 이 입장한다. `Notes` 가 비면 호출되지 않는다(방 이름이 없으므로).
  - 프론트가 `CREATE_GAME` 을 통과시킬 때 Notes 를 읽어 트리거하고, `dontCheckDeckContent` 도 1 로 맞춘다(봇 방 규칙).
- 문서: `PLAYER-GUIDE.md` §5 에 **모드별 입력 위치 표**, `MANUAL-room-rules.md` §9, 패널 도움말 ⑥ 갱신

### 실측
- 서버모드 생성(`Notes='bot'`) → +2초 `users=['SrvHost','Raisemoon']`, `no_check=True`
- LAN 모드(`bot`) 기존 동작 유지 · `--selftest` 79/79 PASS

## v1.3.5 — 2026-11-07

### 수정 (서버 대전 모드로 `duelport 7914` 를 쓸 때)
- **비밀번호 방 입장 실패**: 서버모드 JOIN 은 `pass` 필드가 **비밀번호**인데, 프론트가 이를 "방 이름"으로 해석해
  빈 비밀번호로 재전송 → `잘못된 비밀번호`. 이제 **방 번호가 확인되면 pass 를 비밀번호로 그대로 전달**한다.
- **방 이름(Notes) 학습**: 프론트를 거치는 `CREATE_GAME`(서버모드)의 `notes` 를 읽어 **이름→번호 매핑에 등록**
  → LAN 관전자가 Notes 값으로 그 방에 들어올 수 있다.

### 실측
- 프론트(7914)로 비번방 생성(`srvpass#1234`) → 올바른 비번 `JOIN·ENTER` / 틀린 비번 `ERR(0x01000000)`
- 7922: `notes='srvpass' needpass=True users=['Host4','GoodPass']`
- `--selftest` 79/79 PASS

## v1.3.4 — 2026-11-07

### 새 기능
- **방 번호로 입장**: 비밀번호 칸에 **숫자만** 적으면 그 **방 번호**로 입장(이름 매칭 실패 시 폴백).
  서버 대전 모드로 만든 방의 `Notes` 가 비어 이름이 없을 때 유용하다.

### 문서
- `PLAYER-GUIDE.md` **§5-1 관전하기** 추가
  - 서버 대전 모드 방은 목록에 보이는 이름이 **`Notes`(설명)** 값 → 관전자는 그 값을 입력
  - `Notes` 를 비우면 이름 없는 방이 되므로 **방 만들 때 Notes 에 이름을 적도록** 안내
  - 비밀번호 방은 `이름#비번`, 이름을 모르면 **방 번호(숫자)**

### 실측
- 서버모드처럼 `name='servername' / notes='myroom'` 으로 생성 → 7922 `roomname=''`, `roomnotes='myroom'`
- 7914 에서 `myroom` 입력 → 입장(사용자 2명) · `1`(방 번호) 입력 → 입장
- `--selftest` 79/79 PASS

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
