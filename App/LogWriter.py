# -*- coding: utf-8 -*-
"""로그 한 곳에서 받아 쓰기: 링 버퍼(웹 UI) + 회전 파일 + stdout(docker logs).

회전 규칙: multirole.log 가 MR_LOG_MAX 를 넘으면 .1 → .2 → … 로 밀고 새로 쓴다.
"""

import collections
import os
import threading

from .SysInfo import now_str


class LogWriter(object):
    def __init__(self, st):
        self.st = st
        self.lock = threading.RLock()
        self.ring = collections.deque(maxlen=st.ring_max)
        self.counter = 0
        self.echo = os.environ.get("MR_STDOUT_LOG", "1") != "0"
        self._ensure_dir()

    def _ensure_dir(self):
        try:
            os.makedirs(self.st.log_dir, exist_ok=True)
        except OSError:
            pass

    def _rotate_if_needed(self):
        try:
            if os.path.getsize(self.st.log_path) < self.st.log_max:
                return
        except OSError:
            return
        try:
            for i in range(self.st.log_keep - 1, 0, -1):
                src = "%s.%d" % (self.st.log_path, i)
                dst = "%s.%d" % (self.st.log_path, i + 1)
                if os.path.exists(src):
                    os.replace(src, dst)
            os.replace(self.st.log_path, self.st.log_path + ".1")
        except OSError:
            pass

    def write(self, text):
        line = "%s %s" % (now_str(), text.replace("\r", "").rstrip("\n"))
        if self.echo:
            try:
                print(line, flush=True)   # docker logs / Container Manager 로그 탭
            except Exception:
                pass
        with self.lock:
            self.counter += 1
            self.ring.append(line)
            need_rotate = False
            try:
                need_rotate = os.path.getsize(self.st.log_path) >= self.st.log_max
            except OSError:
                pass
        if need_rotate:
            self._rotate_if_needed()
        try:
            with open(self.st.log_path, "a", encoding="utf-8", errors="replace", newline="\n") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def tail(self, n=200):
        with self.lock:
            lines = list(self.ring)
        return lines[-n:]
