# Multirole Web — 시놀로지용 단일 이미지 (웹 조작 패널 포함)

> ## 🎮 그냥 게임하러 오셨나요?
> **[플레이어 안내서 `PLAYER-GUIDE.md`](PLAYER-GUIDE.md)** 를 보세요.
> 접속(포트 **7914**), 방 이름·비밀번호 규칙, **봇과 대전(`bot`)**, 금제·덱 규칙, 자주 나는 오류가 정리돼 있습니다.
>
> | 문서 | 대상 |
> |---|---|
> | [`PLAYER-GUIDE.md`](PLAYER-GUIDE.md) | **플레이어** — 접속·방 만들기·봇·오류 해결 |
> | [`MANUAL-room-rules.md`](MANUAL-room-rules.md) | 방 규칙 문법 · **봇 49종 목록** |
> | `README.md` (이 문서) · [`UPGRADE.md`](UPGRADE.md) | **운영자** — 설치·설정·업그레이드 |

`dyxel/multirole:v1.1.0` 위에 **웹 관리 패널**을 얹은 이미지입니다.
공식 이미지의 `area-zero.sh`(감독 루프)를 우리 파이썬 슈퍼바이저가 대체합니다.

> **현재 버전 v1.3.7** — 변경 내역은 [`CHANGELOG.md`](CHANGELOG.md)
> v1.3 핵심: **머큐리 프론트(7914)** 로 방 이름 기반 클라이언트 연결 · **비밀번호 칸 = 방 이름·규칙** ·
> **금지/제한 목록 선택** · **서버 안 봇 대전(`bot` / `b:<덱>`)**

> ### 공개 저장소 안내
> 이 저장소는 **Multirole 본체를 실행하는 래퍼(별도 프로세스)** 입니다. Multirole 본체는
> [DyXel/Multirole](https://github.com/DyXel/Multirole)(**AGPL-3.0**)이고 이미지로만 사용합니다.
> 개인 NAS 접속 정보(주소·계정·포트·키)는 저장소에서 **제외**했습니다
> (로컬 `NAS-ACCESS.md` 는 `.gitignore` 처리). 예시 주소는 `<서버 주소>` 로 표기합니다.



```
[브라우저] ──HTTP 8080──► [webui.py (PID 1)]
                             │ ① config.json 읽기/검증/원자적 쓰기(+.bak)
                             │ ② 자식 프로세스 재시작 (SIGTERM → 재기동)
                             │ ③ 로그 tail (파일 + 메모리 링버퍼)
                             │ ④ 웹훅 프록시 (리포 즉시 갱신)
                             ▼
                        [multirole + hornet]
```

## 0. 먼저 알아둘 것 (정직한 한계)

| 항목 | 동작 |
|---|---|
| 설정 보기 | ✅ 전부 (`config.json` 전체를 폼으로 자동 렌더) |
| 설정 수정 | ⚠️ **저장 → 재시작**해야 반영. multirole 이 `config.json` 을 **기동 시 1회만** 읽고 reload 경로가 없음 |
| 재시작 다운타임 | 수 초 (코어·리포 스캔 포함). **진행 중인 방은 끊김** — UI 가 접속 수를 보고 경고 |
| 데이터(lua·cdb·금제·libocgcore.so) | ✅ **즉시** — [갱신] 버튼 = 웹훅 → git pull |
| 방/유저 목록 | ⚠️ **접속 수만** (`/proc/net/tcp` 의 7911/7922 ESTABLISHED). 방 목록 API 는 서버에 없음 |

> 진짜 무중단 핫리로드는 Multirole **포크**가 필요합니다(포트·스레드는 어차피 재시작).
> 이 이미지는 **포크 없이** 얻을 수 있는 최선입니다.

## 1. 요구사항

- 시놀로지 **x86_64 모델** (DS220+/DS920+/DS923+/DS1520+/DS1621+ …)
  - ARM 모델(DS223/DS223j/DS423 등)은 **불가**: 공식 이미지가 `linux/amd64` 전용
- **Container Manager** (DSM 7.2) 또는 SSH 의 `docker` / `docker compose`
- 메모리 2GB 이상 권장, 방 3~5개면 `concurrencyHint` 4~8

## 2. 파일

| 파일 | 용도 |
|---|---|
| `Dockerfile` | 기본 (apk 로 python3 설치) |
| `Dockerfile.pystage` | **대체용** — `apk add` 가 실패할 때 |
| `webui.py` | 슈퍼바이저 + 웹 API (파이썬 표준 라이브러리만) |
| `index.html` | 웹 UI (단일 파일, 다크 테마) |
| `docker-compose.yml` | 포트/볼륨/환경변수 |
| `config.sample.json` | 공식 이미지의 기본 설정 사본 |

## 3. 설치 (시놀로지)

```bash
# 1) 폴더
sudo mkdir -p /volume1/docker/multirole/data/{sync,replays,room-logs,logs,tmp}
cd /volume1/docker/multirole

# 2) 이 폴더의 파일 업로드 (Dockerfile, Dockerfile.pystage, webui.py, index.html,
#    docker-compose.yml, config.sample.json)

# 3) ★ config.json 은 반드시 "파일" 로 먼저 만들어 둔다
sudo cp config.sample.json data/config.json
sudo chown -R 1026:100 data           # DSM 사용자(uid 1026) 기준 예시

# 4) webhookToken 4개 교체 (기본값 <change_this> 는 위험)
sudo nano data/config.json

# 5) 빌드 + 기동
sudo docker compose up -d --build

# 6) 로그 확인
sudo docker logs -f multirole
```

정상 기동 시 로그에 이 순서로 찍힙니다.

```
[webui] v1.0.0 starting (base=/multirole, bin=./multirole)
[webui] multirole started (pid 7)
[webui] listening on http://0.0.0.0:8080
... multirole 자신의 로그 (git clone, lobby listening …)
```

### ★ config.json 마운트 주의
`./data/config.json:/multirole/config.json` 는 **파일 바인드**입니다.
호스트에 그 파일이 **없으면 도커가 같은 이름의 디렉터리를 만들어** 버리고, multirole 은
`config.json` 을 읽지 못해 즉시 종료 → 슈퍼바이저가 무한 재시작합니다.
**반드시 3) 단계를 먼저** 하세요.

### apk 실패 시
빌드 중 아래처럼 나오면 `Dockerfile.pystage` 로 바꿉니다.

```
ERROR: unable to select packages / UNTRUSTED signature / temporary error
```

```bash
sudo sed -i 's/^      dockerfile: Dockerfile/      dockerfile: Dockerfile.pystage/' docker-compose.yml
sudo docker compose up -d --build
```

`Dockerfile.pystage` 는 `python:3.12-alpine` 의 CPython 을 **musl 호환**으로 복사합니다
(멀티role 이미지에 이미 있는 libssl3 를 그대로 사용).

## 4. 포트

| 포트 | 용도 | 외부 노출 |
|---|---|---|
| 7911 | 룸 호스팅 (플레이어 접속) | **필요** |
| 7922 | 로비 (방 목록) | **필요** |
| 8080 | 웹 관리 화면 | **비권장** — DSM 역방향 프록시 + HTTPS 뒤에 두세요 |
| 34343 / 62672 / 49382 / 43632 | 리포별 웹훅 | 불필요 (웹 UI 가 내부에서 호출) |

`EXPOSE` 는 7911/7922(상속) + 8080 입니다. 웹훅 포트는 **호스트로 게시하지 마세요**
(외부에서 리포 pull 을 강제 = 원격 코드 실행 경계).

## 5. 웹 UI

`http://<NAS-IP>:8080` → `WEB_TOKEN` 입력.

| 탭 | 내용 |
|---|---|
| **설정** | `config.json` 전체 폼 (키별 한국어 설명, 리포 추가/삭제). `[저장]` `[저장 후 재시작]` `[파일 다시 읽기]` `[원본 JSON]` |
| **상태** | 프로세스(PID·가동·재시작 횟수·종료 코드), 설정(해시·**반영 대기**), 접속 수/포트 LISTEN, 리포별 HEAD·마지막 fetch·[갱신], provider 파일 수, 리플레이 수·최근 파일·용량, tmp 코어 |
| **로그** | 자식 프로세스 stdout/stderr tail (2초 자동), 파일 경로 표시 |
| **리플레이** | `replays/*.yrpX` 목록 + 브라우저 다운로드 |
| **봇** | 실행 중 봇(방·덱·PID·가동·로그) + **방 선택 → 덱 검색(53개) → [투입]**, [전체 중지] |
| **카드** | cdb 검색(ID·이름·효과) + **갱신 반영 확인**(sync 후 자동 스냅샷 비교) |

헤더: 실행 상태 · PID · 가동 시간 · 접속 수 · **[시작] [중지] [재시작]**

- 저장만 하면 `설정 변경됨 · 재시작 필요` 배지가 뜹니다(파일과 실행 중 해시 비교).
- 재시작 시 접속이 있으면 **경고 후 확인**을 받습니다.
- 설정에 오류가 있으면 **재시작을 거부**합니다(부팅 실패 방지).

## 6. API (스크립트/자동화용)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/health` | `{"ok":true}` — 인증 없음 (HEALTHCHECK) |
| GET | `/api/ping` | 가벼운 상태(프로세스·접속·반영 대기) |
| GET | `/api/status` | 전체 상태 (리포/데이터/리플레이/코어) |
| GET | `/api/config` | 설정 + 문서 + 검증 결과 |
| PUT | `/api/config` | 검증 → `.tmp` → fsync → 원자적 교체 + `config.json.bak-<시각>` (최근 20개 보존) |
| POST | `/api/restart[?force=1]` | `force` 없이 접속이 있으면 **409** + 접속 수 |
| POST | `/api/start` · `/api/stop` | 자식 프로세스 제어 |
| GET | `/api/logs?tail=300` | 링버퍼(최대 2000줄) |
| POST | `/api/sync` `{"name":"scripts"}` | 해당 리포 웹훅으로 토큰 POST (git pull) |
| GET | `/api/replays` · `/api/replay?name=` | 목록 / 다운로드(경로 탈출 차단) |
| GET | `/api/bots` | 봇 탭 데이터 — `running` · `decks` · `rooms` · `default`(botd + 로비 병합) |
| GET | `/api/access?tail=100&ip=&room=` | 접속 이력(JSONL) — 실IP · 멀티롤 별칭 · 방 · 사유 |
| POST | `/api/bot/start` `{"roomId":2,"deck":"raisemoon"}` · `/api/bot/stop` · `/api/bot/stopall` | 봇 투입/중지 |

인증: `WEB_TOKEN` 을 설정하면 쿠키(`mr_auth`) 또는 `X-MR-Token` 헤더가 필요합니다.
**비우면 인증 없음** — NAS 를 다른 사람이 쓰는 환경에서는 반드시 설정하세요.

### 셀프테스트 (배포 검증)

```sh
# 호스트(Windows) 에서
python webui.py --selftest

# 배포한 컨테이너에서 (v1.8.1+, 라이브 설정을 건드리지 않는다)
docker exec multirole-web python3 /dyxel/multirole/webui.py --selftest
```
- 설정/HTTP/프론트/유령정리/접근로그/계정백업까지 **124개 검사**
- `selftest.live-config-untouched` 가 **라이브 config.json 이 그대로인지** 확인한다

## 7. 보안 체크리스트

- [ ] `WEB_TOKEN` 변경 (기본값 그대로 두지 않기)
- [ ] `repos[].webhookToken` 4개 모두 교체 (`<change_this>` 금지)
- [ ] 8080 은 DSM 역방향 프록시(HTTPS) + 접근 제어 뒤로
- [ ] 웹훅 4포트는 **호스트 게시 금지**
- [ ] `remote` URL 은 신뢰하는 저장소만 (lua·네이티브 코어가 그대로 실행됨)
- [ ] `logHandler` 의 `discordWebhook` URL 을 쓰면 그 URL 도 비밀값

## 8. 문제 해결

| 증상 | 원인 / 조치 |
|---|---|
| `config.json` 을 못 읽고 무한 재시작 | 호스트에 `data/config.json` 파일이 없어 **디렉터리로 생성됨** → 컨테이너 중지, 디렉터리 삭제 후 `config.sample.json` 복사 |
| 웹은 뜨는데 multirole 이 계속 죽음 | 로그 탭에서 원인 확인 (대개 설정 오류 — `validate` 가 잡지 못한 형식/경로) |
| 빌드 실패 (apk) | `Dockerfile.pystage` 사용 |
| 설정을 바꿨는데 그대로 | **재시작 필요** — 배지 확인 후 [재시작] |
| 재시작 후 방이 사라짐 | 설계상 불가피(SIGTERM → 재기동). 접속이 없을 때 적용 권장 |
| 파일이 root 소유라 File Station 에서 수정 불가 | `sudo chown -R 1026:100 /volume1/docker/multirole/data` |
| 웹에서 8099/8080 접속 불가 | DSM 방화벽에서 8080 허용, `docker ps` 로 포트 매핑 확인 |
| 리플레이가 안 보임 | `replayManager.save=true`, `path` 확인 |
| 웹 화면이 비어 있고 콘솔에 **502** | PC 의 로컬 HTTP 프록시(**AdGuard 등**)가 동시 연결을 끊는 경우입니다. 서버는 정상(300회 병렬 요청 실패 0 실측). NAS 주소를 예외/허용 목록에 추가하거나 HTTP 필터링을 끄면 사라집니다. 페이지는 1회 응답으로 인라인되므로 **새로고침 1~2회**면 정상 표시됩니다 |
| 로그에 `ConnectionAbortedError` | 클라이언트가 먼저 끊은 것 — 서버는 조용히 무시합니다(정상) |

## 9. 검증 (도커 없이)

```bash
python3 webui.py --selftest
```

가짜 자식 프로세스로 다음을 실제로 검사합니다(현재 **45/45 PASS**).

- 설정 로드/검증(포트 중복·필수 키·sink 타입·토큰 경고) · 원자적 저장/백업/탭 들여쓰기
- 슈퍼바이저 기동/로그 수집/**중지/재시작**/running-hash
- 상태 수집(HEAD·provider 파일 수·리플레이·포트)
- HTTP: 401 인증, `/api/ping`, GET/PUT config, 검증 실패 422, 로그, 리플레이 다운로드,
  **경로 탈출 차단**, start/stop/restart

## 10. 모듈 지도 (파일 1개 = 책임 1개)

에디터(`WindBotAIEditor/Services/*.cs`)와 같은 방식으로 잘게 나눴습니다.
의존 방향은 **위 → 아래 한 방향**(`App/__init__.py` 에 문서화).

### 서버 (Python)

| 파일 | 책임 |
|---|---|
| `webui.py` | 진입점(얇음) — `sys.path` + `App.Server.main()` 호출만 |
| `App/__init__.py` | `VERSION`, 경로, 의존 방향 문서 |
| `App/Context.py` | 전역 앱 참조(순환 import 방지) |
| `App/Settings.py` | 환경변수 → 속성, `real_config()`, **config 심볼릭 링크** |
| `App/SysInfo.py` | 해시 · 포트 · 접속 수(`/proc/net/tcp`) · git HEAD · 파일 수 (**부작용 없음**) |
| `App/LogWriter.py` | 링 버퍼 + 회전 파일 + stdout(docker logs) |
| `App/Supervisor.py` | 자식 프로세스(**pty**) · 자동 재시작 루프 · SIGTERM/유예/KILL |
| `App/ConfigSchema.py` | `Instance.cpp` 의 `.at()` 을 옮긴 스키마 검증 + 키 설명 |
| `App/ConfigStore.py` | 읽기 / 검증 / **원자적 저장** / `.bak` 백업 |
| `App/Status.py` | `/api/ping`(가벼움) · `/api/status`(리포·provider·리플레이·코어·포트) |
| `App/Auth.py` | 토큰/쿠키 검사, 로그인 페이지 |
| `App/HttpApi.py` | 라우팅 · 정적 파일(화이트리스트) · **인라인 번들** · `PanelServer`(backlog 256) |
| `App/Server.py` | 부트스트랩(시그널 → 기동 → serve_forever) |
| `App/SelfTest.py` | `--selftest` (가짜 자식으로 **54개 검사**, 도커 불필요) |

### 화면 (JS/CSS)

| 파일 | 책임 |
|---|---|
| `Web/index.html` | 마크업만 |
| `Web/app.css` | 다크 테마 스타일 |
| `Web/js/Util.js` | `$` · `esc` · `dur` · `size` · 경로 get/set · 배너 · 확인 모달 |
| `Web/js/Api.js` | fetch 래퍼 (+ GET 2회 재시도) |
| `Web/js/State.js` | 화면 전역 상태(MODEL/DOCS/TAB...) |
| `Web/js/Header.js` | 상단 배지·시작/중지/재시작 (5초 폴링) |
| `Web/js/ConfigForm.js` | 설정 폼 자동 렌더 · 저장 · 재시작 · 원본 JSON |
| `Web/js/StatusPanel.js` | 상태 카드 + 리포/ provider 표 + [갱신] |
| `Web/js/LogPanel.js` | 로그 tail(2초) |
| `Web/js/ReplayPanel.js` | 리플레이 목록/다운로드 |
| `Web/js/App.js` | 탭 전환 + 부트스트랩 |

> **소스는 분리, 브라우저에는 1회 전송**: `GET /` 가 `app.css` + `js/*.js` 를 HTML 에
> 인라인해 **한 응답**으로 보냅니다(동시 연결에서 간헐 502 가 나는 로컬 프록시 회피).
> 분리된 원본이 필요하면 `GET /?raw=1`, 개별 파일은 `/app.css`·`/js/*.js` 로도 접근 가능합니다.

## 11. 참고 문서

- `D:\rea-out\multirole\REPORT.md` — 아키텍처·프로토콜·보안
- `D:\rea-out\multirole\WEB-UI-FEASIBILITY.md` — 설정 전체 목록과 재시작 필요 여부
- `D:\rea-out\multirole\SYNOLOGY-WEB-PLAN.md` — 배포 계획(3가지 패턴 비교)

### 서버 대전 모드에서 `duelport 7914` 를 써도 되나?

**됩니다** (v1.4.3 기준). 프론트가 방 번호를 그대로 서버에 넘기므로 목록 지연과 무관합니다.

| 기능 | 7911 직결 | 7914(프론트) |
|---|---|---|
| 방 만들기 / 목록에서 입장 | ✅ | ✅ |
| 비밀번호 방 | ✅ | ✅ (v1.3.5+) |
| 방금 만든 방에 즉시 입장 | ✅ | ✅ (v1.4.3+) |
| 잘못된 번호 입장 | 서버 오류 | 서버 오류(새 방 안 만듦) |
| 관전(자리 찼을 때) | ✅ | ✅ |
| **봇 자동 호출(Notes=`bot`)** | ❌ | ✅ |
| LAN 모드 방 이름 입장 | ❌ | ✅ |

권장: **`duelport 7914` 하나로 통일** (v1.6.0+).
- 프론트를 거치면 **keepalive + CLOSE_WAIT 감시 + 유령 방 정리**가 적용됩니다. 7911 직결은 이 보호를 못 받습니다
  (multirole 이 소켓을 직접 들고 있어 외부에서 끊을 수 없음).
- 대신 multirole 입장에서 접속 IP 가 `127.0.0.1` 로 보입니다(방장 kick 시 그 방에서 IP 차단이 걸릴 수 있음 — 방이 닫히면 해제).
- 7911 은 **내부용**이 됩니다. 외부에 열려 있으면 DSM 방화벽에서 막아도 됩니다(프론트는 localhost 로 접속).

### 접속 IP 확인 (v1.7.0+)

- **실제 IP** — 프론트가 기록: 설정 탭 「접속 IP」 열 · `GET /api/rooms` 의 `ips`
- **멀티롤이 보는 주소** — 업스트림을 `127.0.a.b` **별칭**에 바인딩(실IP 해시, 고정).
  7914 단일화로 전원이 `127.0.0.1` 로 보여 **방장 kick 이 방 전체를 막던 문제**를 없앤다.
- **이력** — `logs/access.log`(JSONL, 20MB × 10 · 30일) · 설정 탭 「📋 접속 이력」 · `GET /api/access`
- 한계: 같은 공유기(NAT) 뒤 두 명은 실IP가 같다(별칭도 같음). 이때는 로그의 **포트**로 구분한다.
  멀티롤 자체 로그(`roomLogging`)에는 **별칭**만 찍힌다.

### HTTPS — DSM 역방향 프록시 (v1.8.2+)

권장 구성(인증서 재사용, 포트만 추가):
```
DSM 제어판 → 로그인 포털 → 고급 → 역방향 프록시 → 생성
  원본: HTTPS / sw20103.synology.me / 8443
  대상: HTTP  / 127.0.0.1 / 8090
  인증서: 제어판 → 보안 → 인증서 → 설정 → 'multirole-web' 에 sw20103.synology.me 지정
공유기: 외부 TCP 8443 → 192.168.0.4:8443
접속  : https://sw20103.synology.me:8443
```
- 앱은 `X-Forwarded-Proto: https` 를 보고 **쿠키에 `Secure`** 를 붙이고, `X-Forwarded-For` 로 **실제 IP** 를 기록합니다.
- HTTP 직접 접속(`http://192.168.0.4:8090`)도 계속 동작합니다(쿠키에 Secure 를 붙이면 로그인 루프가 되기 때문).
- 원하면 `WEB_BIND=127.0.0.1` 로 바꿔 **8090 직접 접속을 차단**할 수 있습니다(프록시만 통과, 기존 북마크는 막힘).

### 카드 탭 — cdb 검색 / 갱신 확인 (v1.9.0+)

`databases` 저장소를 갱신한 뒤 **카드가 실제로 반영됐는지** 확인하는 화면입니다.

- 검색: **카드 ID · 이름 · 효과 문구** → 결과에 **출처 cdb 파일 + 파일 갱신 시각**
- 상세: 종류/속성/종족/ATK/DEF/설명/`str1~5`
- 갱신 확인: `/api/sync` 성공 시 **자동 스냅샷** → 이전 상태와 비교해 **추가/변경/삭제** 목록 표시
- API: `GET /api/cards?q=` · `GET /api/cards/<id>` · `GET /api/cards/changes` · `POST /api/cards/snapshot`
- 같은 ID 가 여러 cdb 에 있으면 **뒤 파일(unofficial/prerelease/커스텀)이 우선**이며 출처를 함께 보여줍니다.

### 계정 백업 (v1.8.0+)

`auth.json` 은 잃으면 계정을 새로 만들어야 하고(세션 서명 키 포함), 유출되면 쿠키 위조가 가능합니다.

| 위치 | 방법 | 보관 |
|---|---|---|
| **NAS (자동)** | 컨테이너가 24시간마다 + **비밀번호 변경 시** `_auth-backups/` 에 저장 (0700/0600) | 최근 **30개** |
| **PC (자동)** | 예약 작업 `MultiroleAuthBackup` → `tools/pull-auth.ps1` (매일 22:00, 내용 같으면 SKIP) | 최근 30개 · 90일 |
| **릴리스** | `tools/backup.ps1 -AuthFile …` (ZIP 밖에 보관) | 릴리스마다 |

- 수동: 패널 설정 탭 **[지금 백업]** 또는 `POST /api/auth/backup` · 목록 `GET /api/auth/backups`
- 복원: `docker exec multirole-web python3 /app/webui.py --restore-auth /dyxel/multirole/_auth-backups/auth-....json`
  → 현재 파일은 `.bak-<시각>` 으로 보관되고, **재시작 후** 적용됩니다
- ⚠ 폴더를 공유/클라우드 동기화에 올리지 마세요(평문 비밀값). 필요하면 암호화 후 동기화.

### 로그인 — 패널 관리자 계정 (v1.4.3+)

- **패널 전용 계정**입니다(DSM 계정과 별개, 같은 아이디를 써도 무관).
- **첫 접속**하면 `패널 관리자 계정 만들기` 화면이 뜹니다. 아이디·비밀번호를 정하면 이후 그 계정으로 로그인합니다.
- 비밀번호는 **PBKDF2-SHA256(100k)** 해시로만 저장됩니다(`auth.json`, 평문 없음).
- 세션 쿠키 `mr_session`(12시간, HttpOnly) · **실패 5회 → 60초 잠금**
- 헤더의 **[비밀번호] / [로그아웃]** 버튼으로 변경·종료
- **비상용 토큰 로그인**은 접이식 “토큰으로 들어가기”로 남아 있습니다 (`MR_AUTH=both` 기본).
- 초기화: `docker exec multirole-web python3 /app/webui.py --reset-auth` → 다음 접속에 계정 만들기 화면
- `MR_AUTH` = `both`(기본) · `account`(토큰 비활성) · `token`(구방식)
- ⚠ `auth.json` 은 **저장소·릴리스에 올리지 않습니다**(`.gitignore`). 로컬 백업에만 보관하세요. HTTPS 권장.

### 백업 (운영자)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\backup.ps1 -AuthFile <auth.json 경로>
```
- `_backups\<버전>\` 에 소스 ZIP(구조 유지) + 문서 + `SHA256.txt`
- **`auth.json` 은 ZIP 밖에만** 저장합니다(로컬 백업 전용, git·릴리스 제외)
- `auth.json` 받는 법: `docker exec multirole-web cat /dyxel/multirole/auth.json > auth.json` (root 권한)

### 저장소 갱신 — **[전체 갱신]** (v1.4.3+)

상태 탭 → **[전체 갱신]** 을 누르면 `config.json` 의 모든 리포를 순서대로 `git fetch + reset` 합니다(웹훅).
갱신은 **즉시 반영**되며 재시작이 필요 없습니다. 결과는 상태 탭에 리포별로 표시됩니다.

- **변경됨** — 이전 HEAD → 새 HEAD, **커밋 메시지**와 **바뀐 파일** 목록
- **변경 없음** — 이미 최신
- **실패** — 사유(웹훅 오류·multirole 자식 로그)를 빨간 배너와 결과 카드에 표시, 패널 로그에도 기록

> 이미지에 `git` 이 포함되어 있습니다(커밋/파일 목록용, 59.7MB → 72.1MB).
> 리포 **추가**(`repos` 항목)나 포트·동시성 변경은 여전히 **재시작**이 필요합니다.