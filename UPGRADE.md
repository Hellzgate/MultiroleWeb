# Multirole 업그레이드 절차 (우리 웹 패널 포함)

현재 기준: **Multirole v1.1.0** (2025-04-21) · Docker Hub `latest` == `v1.1.0` · **이후 릴리스 없음**(2026-11-07 확인).
우리 이미지: `multirole-web:1.1.0` — `FROM dyxel/multirole:v1.1.0` + python3 + `App/`·`Web/`.

---

## 0. 결론: **태그 한 줄 바꾸면 끝** (실측 5분 이내)

```dockerfile
FROM dyxel/multirole:v1.1.0      # ← v1.2.0 으로 교체
```

이미 tcmalloc/백로그/정적 파일 문제는 **버전에 의존하지 않게** 만들어 두었다(아래 "이미 대비된 것").

---

## 1. 업그레이드 순서 (내가 하는 일)

### ① 새 버전 확인
```bash
# GitHub 릴리스 / Docker Hub 태그
curl -s https://api.github.com/repos/DyXel/Multirole/releases/latest | grep tag_name
```
새 태그가 있으면 이미지 설명(release notes)에서 **설정 키 변경** 여부를 먼저 본다.

### ② 새 이미지의 "우리가 의존하는 부분" 검사 (배포 전, 읽기만)
```bash
docker pull dyxel/multirole:v1.2.0
docker run --rm --entrypoint sh dyxel/multirole:v1.2.0 -c '
  ls -l /multirole;                 # multirole / hornet / config.json / area-zero.sh 위치
  cat /etc/apk/world;               # tcmalloc-minimal@testing 여부
  ldd /multirole/multirole | grep -i tcmalloc || echo "no tcmalloc"
  grep -n "fileRegex\|coreType\|Port\|concurrencyHint" /multirole/config.json'
```
체크 포인트
| 항목 | 우리가 가정하는 값 | 바뀌면 |
|---|---|---|
| 실행 파일 위치 | `/multirole/multirole`, `./hornet` (cwd 기준) | compose 의 `MR_BIN` 수정 |
| 작업 폴더 | `/multirole` | `MR_BASE` 수정 |
| 코어 파일 | `libocgcore.so` (`.*libocgcore\.so`) | 호스트 `config.json` 의 `coreProvider.fileRegex` 수정 |
| 필수 설정 키 | `App/ConfigSchema.py` 의 `TOP_LEVEL` | **검증기가 저장을 막으므로** 키 추가 필요 |
| tcmalloc | 있으면 보존, 없으면 그냥 진행 | (자동) |
| python3 설치 | `apk add` (실패 시 `Dockerfile.pystage`) | Dockerfile 선택 |

### ③ 스키마 차이 반영 (키가 늘었을 때만)
- 새 이미지의 `/multirole/config.json` 과 우리 호스트 `config.json` 을 비교(diff).
- `App/ConfigSchema.py` 의 `TOP_LEVEL` + `KEY_DOCS` 에 새 키를 추가.
- **모르는 키가 늘었는데 우리 검증기를 안 고치면**: `.at()` 재현 검증은 **없는 키만** 막으므로 저장은 되지만,
  신규 키가 **UI 에 안 보인다**. → 반드시 추가.

### ④ 빌드 · 재배포 (다운타임 수 초)
```bash
cd /volume1/docker/multirole
sudo docker build -t multirole-web:<새버전> .
sudo docker tag  multirole-web:<새버전> multirole-web:1.0.0   # compose 가 참조하는 태그
sudo docker compose up -d --no-build --force-recreate
```
- **진행 중 듀얼이 있으면 먼저 확인** — 웹 UI [재시작] 은 접속 수를 보고 409 로 막아 준다.
- 데이터(`config.json`·`sync/`·`replays/`·`tmp/`)는 그대로.

### ⑤ 검증 (배포 직후)
```bash
curl -s http://127.0.0.1:8090/api/health          # {"ok": true, "version": "1.1.0"}
docker logs --tail 20 multirole-web               # Initialization finished successfully!
```
- 웹 4탭(설정/상태/로그/리플레이) 확인 + **EDOPro 로 1판**.
- `--selftest` 는 **이미지 안에서**도 돌릴 수 있다: `docker exec multirole-web python3 /app/webui.py --selftest` (가짜 자식 사용).

### ⑥ 문제가 있으면 즉시 롤백
```bash
/volume1/docker/multirole/_rollback.sh            # 원본 dyxel/multirole 로 복귀
# 또는 이전 태그로: docker tag multirole-web:<이전버전> multirole-web:1.0.0 && compose up -d --force-recreate
```

---

## 2. 이미 대비해 둔 것 (버전이 올라가도 그대로 동작)

| 과거 문제 | 대비 |
|---|---|
| `apk add` 가 world(tcmalloc@testing) 때문에 커밋 거부 | `--force-broken-world` + **버전 비의존** 사전 복사/복원(`cp -a /usr/lib/libtcmalloc*`) — 새 이미지에 tcmalloc 이 없어도 빌드 성공 |
| Alpine 레포 문제로 python3 설치 실패 | `Dockerfile.pystage` (python:3.12-alpine 의 CPython 복사, 둘 다 musl) |
| HEALTHCHECK 가 8080 고정 | `WEB_PORT` 환경변수를 읽음 |
| 자식 로그가 4KB 버퍼에 갇힘 | 자식에게 **pty** 부여 |
| 로컬 프록시가 동시 연결을 끊어 JS 일부 502 | `GET /` 가 CSS+JS 를 **인라인한 1응답** + backlog 256 + GET 재시도 |
| 단일 파일 바인드 마운트에서 원자적 저장 불가(EBUSY) | 폴더 마운트 + `config.json` **심볼릭 링크**(`MR_CONFIG_PERSIST`) |

---

## 3. 업그레이드 시 자주 걸리는 것

1. **`config.json` 신규 필수 키** → 우리 검증기가 "필수 키 누락"으로 **저장을 막는다**(의도된 안전장치).
   호스트 `config.json` 에 새 키를 추가하고 `ConfigSchema.TOP_LEVEL`/`KEY_DOCS` 도 갱신.
2. **코어 파일 이름 변경**(예: `ocgcore.so` → `libocgcore.so`) → `coreProvider.fileRegex` 수정.
   `.dll`(윈도우) 정규식을 리눅스에 쓰면 `Exec format error` 로 **즉사**(2026-11-06 실제 사고).
3. **경로 변경**(`/multirole` → 다른 곳) → `MR_BASE`/`MR_BIN` 수정.
4. **프로토콜/클라이언트 변경** → 웹 패널과 무관하지만 EDOPro 버전도 함께 맞춰야 할 수 있다.
5. **`latest` 태그 사용 금지(권장)** → 지금은 `v1.1.0` 고정. 재현성과 롤백을 위해 릴리스 태그를 쓴다.

---

## 4. 소요 시간 (실측 기준)

| 단계 | 시간 |
|---|---|
| 이미지 pull(17MB) + 검사 | ~20초 |
| 빌드(레이어 캐시 있음) | **12초**(2026-11-07 실측) / apk 포함 콜드 빌드 40~60초 |
| 재생성 + 기동 | 15~20초 |
| 검증(health·4탭) | ~30초 |
| **합계** | **약 1분** (캐시+설정 그대로일 때) / 스키마 수정 포함 5~10분 |
