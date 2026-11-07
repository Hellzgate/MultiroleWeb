#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multirole Web Control Panel — 진입점(얇게).

실제 코드는 App/ 패키지에 있다(파일 1개 = 책임 1개).

    python3 webui.py              # 컨테이너 CMD (PID 1 로 실행)
    python3 webui.py --selftest   # 도커 없이 자체 검사 (가짜 자식 프로세스 사용)

모듈 지도는 App/__init__.py 참고.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from App.Server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
