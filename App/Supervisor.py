# -*- coding: utf-8 -*-
"""multirole 자식 프로세스 관리 (area-zero.sh 대체).

* 시작/정상 종료(SIGTERM → 유예 → KILL)/재시작
* 죽으면 MR_RESTART_DELAY 초 뒤 자동 재기동 (원본 감독 스크립트와 동일한 동작)
* 자식에게 **pty** 를 주어 stdout 을 line-buffered 로 만든다
  (파이프면 4KiB 블록 버퍼에 마지막 로그가 갇혀 "멈춘 것처럼" 보인다)
"""

import os
import signal
import subprocess
import threading
import time

from .LogWriter import LogWriter
from .SysInfo import file_sha256


class Supervisor(object):
    def __init__(self, st):
        self.st = st
        self.logs = LogWriter(st)
        self.lock = threading.RLock()
        self.proc = None
        self.started_at = None
        self.restarts = 0
        self.last_exit = None
        self.want = True
        self.stopping = False
        self.running_hash = ""

    # -- 로그 위임 -------------------------------------------------------- #
    def log(self, text):
        self.logs.write(text)

    def tail(self, n=200):
        return self.logs.tail(n)

    @property
    def counter(self):
        return self.logs.counter

    @property
    def echo(self):
        return self.logs.echo

    @echo.setter
    def echo(self, value):
        self.logs.echo = bool(value)

    # -- spawn ------------------------------------------------------------ #
    def _spawn(self, cmd):
        """자식을 띄우고 (process, stdout_stream) 을 돌려준다."""
        env = os.environ.copy()
        env.setdefault("TERM", "dumb")
        try:
            import pty  # POSIX only

            master, slave = pty.openpty()
        except Exception:
            proc = subprocess.Popen(
                cmd,
                cwd=self.st.base,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                env=env,
            )
            return proc, proc.stdout
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=self.st.base,
                stdin=subprocess.DEVNULL,
                stdout=slave,
                stderr=slave,
                bufsize=0,
                close_fds=True,
                env=env,
            )
        finally:
            try:
                os.close(slave)
            except OSError:
                pass
        return proc, os.fdopen(master, "rb", buffering=0)

    def _pump(self, proc, stream):
        buf = b""
        while True:
            try:
                chunk = stream.read(4096)
            except (ValueError, OSError):
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                self.log(raw.decode("utf-8", "replace"))
        if buf:
            self.log(buf.decode("utf-8", "replace"))
        try:
            stream.close()
        except Exception:
            pass

    # -- lifecycle -------------------------------------------------------- #
    def is_running(self):
        p = self.proc
        return bool(p is not None and p.poll() is None)

    def start(self):
        with self.lock:
            if self.is_running():
                return True
            self.stopping = False
            self.want = True
            cmd = [self.st.bin] + list(self.st.args)
            try:
                self.proc, stream = self._spawn(cmd)
            except OSError as exc:
                self.proc = None
                self.last_exit = -1
                self.log("[webui] failed to start %r: %s" % (cmd, exc))
                return False
            self.started_at = time.time()
            self.running_hash = file_sha256(self.st.real_config())
            self.log("[webui] multirole started (pid %d)" % self.proc.pid)
            t = threading.Thread(target=self._pump, args=(self.proc, stream), daemon=True)
            t.start()
            return True

    def stop(self, graceful=True):
        with self.lock:
            p = self.proc
        if p is None or p.poll() is not None:
            return True
        clean = True
        if graceful:
            self.log("[webui] SIGTERM -> pid %d" % p.pid)
            try:
                p.send_signal(signal.SIGTERM)
            except OSError:
                pass
            try:
                p.wait(timeout=self.st.stop_grace)
            except subprocess.TimeoutExpired:
                clean = False
                self.log("[webui] grace period expired, killing")
        if not clean or not graceful:
            try:
                p.kill()
                p.wait(timeout=5)
            except Exception:
                pass
        self.log("[webui] multirole stopped (code %s)" % p.returncode)
        return clean

    def restart(self, graceful=True):
        self.want = True
        self.stop(graceful=graceful)
        time.sleep(0.3)
        return self.start()

    def shutdown(self):
        self.stopping = True
        self.want = False
        self.stop(graceful=True)

    def loop(self):
        """area-zero.sh equivalent: keep the child alive."""
        while not self.stopping:
            p = self.proc
            if self.want and (p is None or p.poll() is not None):
                if p is not None:
                    self.last_exit = p.returncode
                    self.restarts += 1
                    self.log(
                        "[webui] child exited (code %s); restarting in %.0fs"
                        % (p.returncode, self.st.restart_delay)
                    )
                    deadline = time.time() + self.st.restart_delay
                    while time.time() < deadline and not self.stopping and self.want:
                        time.sleep(0.1)
                if self.want and not self.stopping:
                    self.start()
            time.sleep(0.25)

    # -- views ------------------------------------------------------------ #
    def uptime(self):
        if not self.is_running() or not self.started_at:
            return 0
        return int(time.time() - self.started_at)
