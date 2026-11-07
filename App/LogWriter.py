# -*- coding: utf-8 -*-
"""로그 한 곳에서 받아 쓰기: 링 버퍼(웹 UI) + 회전 파일 + stdout(docker logs).

v1.7.2 — **디스크 IO 를 네트워크 스레드에서 분리**했다.
  관측: 클라이언트가 CREATE_GAME 을 수십 번 재전송하면 프론트 펌프가 그때마다 로그를
  남기고, `write()` 가 **매 줄 open/close** 를 하면서 NAS 볼륨에서 수 초간 멈췄다.
  그 사이 서버→클라 프레임도 밀려 **방 화면이 얼어붙은 것처럼** 보였다(버튼 무반응).
  → write() 는 **큐에 넣기만** 하고, 실제 파일 IO 는 전용 스레드가 한다(큐가 차면 버린다).
"""

import collections
import os
import queue
import threading

from .SysInfo import now_str

QUEUE_MAX = 5000


class LogWriter(object):
    def __init__(self, st):
        self.st = st
        self.lock = threading.RLock()
        self.ring = collections.deque(maxlen=st.ring_max)
        self.counter = 0
        self.dropped = 0
        self.echo = os.environ.get("MR_STDOUT_LOG", "1") != "0"
        self._q = queue.Queue(maxsize=QUEUE_MAX)
        self._fh = None
        self._stop = False
        self._ensure_dir()
        self._thread = threading.Thread(target=self._run, daemon=True, name="log-writer")
        self._thread.start()

    def _ensure_dir(self):
        try:
            os.makedirs(self.st.log_dir, exist_ok=True)
        except OSError:
            pass

    # -- 파일 IO (전용 스레드) --------------------------------------------- #
    def _open(self):
        if self._fh is None:
            self._fh = open(self.st.log_path, "a", encoding="utf-8", errors="replace", newline="\n")
        return self._fh

    def _close(self):
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    def _rotate_if_needed(self):
        try:
            if os.path.getsize(self.st.log_path) < self.st.log_max:
                return
        except OSError:
            return
        self._close()
        try:
            for i in range(self.st.log_keep - 1, 0, -1):
                src = "%s.%d" % (self.st.log_path, i)
                dst = "%s.%d" % (self.st.log_path, i + 1)
                if os.path.exists(src):
                    os.replace(src, dst)
            os.replace(self.st.log_path, self.st.log_path + ".1")
        except OSError:
            pass

    def _run(self):
        while True:
            try:
                line = self._q.get(timeout=1.0)
            except queue.Empty:
                if self._stop:
                    break
                continue
            if line is None:
                break
            try:
                self._rotate_if_needed()
                f = self._open()
                f.write(line + "\n")
                f.flush()
            except OSError:
                self._close()
            if self.echo:
                try:
                    print(line, flush=True)     # docker logs / Container Manager
                except Exception:               # noqa: BLE001
                    pass
        self._close()

    # -- 공개 API ---------------------------------------------------------- #
    def write(self, text):
        line = "%s %s" % (now_str(), text.replace("\r", "").rstrip("\n"))
        with self.lock:
            self.counter += 1
            self.ring.append(line)
        try:
            self._q.put_nowait(line)
        except queue.Full:
            with self.lock:
                self.dropped += 1

    def tail(self, n=200):
        with self.lock:
            lines = list(self.ring)
        return lines[-n:]
