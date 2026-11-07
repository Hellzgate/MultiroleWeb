#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multirole Web Control Panel — 진입점(얇게).

실제 코드는 App/ 패키지에 있다(파일 1개 = 책임 1개).

    python3 webui.py              # 컨테이너 CMD (PID 1 로 실행)
    python3 webui.py --selftest   # 도커 없이 자체 검사 (가짜 자식 프로세스 사용)
    python3 webui.py --reset-auth # 관리자 계정 초기화(다음 접속에 '계정 만들기' 표시)

모듈 지도는 App/__init__.py 참고.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from App.Server import main  # noqa: E402


def reset_auth():
    from App.AuthStore import AuthStore
    from App.Settings import Settings

    st = Settings()
    store = AuthStore(st.auth_path)
    existed = store.exists()
    store.reset()
    print("auth file: %s" % st.auth_path)
    print("reset: %s" % ("done" if existed else "no account was configured"))
    print("다음 접속에서 '관리자 계정 만들기' 화면이 표시됩니다.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--reset-auth":
        sys.exit(reset_auth())
    sys.exit(main(sys.argv[1:]))
