# -*- coding: utf-8 -*-
"""Multirole Web Control Panel — 애플리케이션 패키지.

에디터(WindBotAIEditor)의 Services/ 처럼 **파일 1개 = 책임 1개**로 나눈다.
모듈 사이의 의존 방향은 아래 순서(위 → 아래)만 허용한다.

    Context        전역 앱 참조(순환 import 방지)
    Settings       환경변수 · 경로 · config 심볼릭 링크
    SysInfo        파일/포트/소켓/git 유틸 (부작용 없음)
    LogWriter      로그 파일 회전 + 링 버퍼 + stdout
    Supervisor     multirole 자식 프로세스(pty) 관리 · 자동 재시작
    ConfigSchema   config.json 스키마 · 검증 · 키 설명
    ConfigStore    config.json 읽기/원자적 저장/백업
    Status         상태 수집 (/api/ping, /api/status)
    Auth           토큰 인증 + 로그인 페이지
    HttpApi        HTTP 라우팅(정적 파일 포함)
    Server         부트스트랩(main)
    SelfTest       --selftest (도커 불필요)

파일 이름은 C# 프로젝트와 같은 PascalCase 를 쓴다(한눈에 대응되도록).
"""

import os

VERSION = "1.3.3"

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(PACKAGE_DIR)
WEB_DIR = os.path.join(APP_ROOT, "Web")
