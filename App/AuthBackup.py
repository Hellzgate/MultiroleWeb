# -*- coding: utf-8 -*-
"""패널 계정(auth.json) 자동 백업 — NAS 안에서 회전 보관.

`auth.json` 에는 PBKDF2 해시와 **세션 서명 키(secret)** 가 들어 있다.
잃으면 계정을 새로 만들어야 하고, 유출되면 로그인 없이 쿠키를 위조할 수 있다.

  - 저장 위치: `MR_AUTH_BACKUP_DIR` (기본 `<persist dir>/_auth-backups`, 0700)
  - 파일: `auth-YYYYmmdd-HHmmss.json` (0600, 원자적 쓰기, JSON 검증 후에만 교체)
  - 보관: 최근 N개(기본 30) — 오래된 것부터 삭제
  - 주기: `MR_AUTH_BACKUP_HOURS`(기본 24시간) + 비밀번호 변경 시 즉시
"""

import io
import json
import os
import threading
import time


class AuthBackup(object):
    def __init__(self, st):
        self.st = st
        self.src = getattr(st, "auth_path", "")
        base = os.path.dirname(self.src) or "."
        self.dir = os.environ.get("MR_AUTH_BACKUP_DIR") or os.path.join(base, "_auth-backups")
        self.keep = int(os.environ.get("MR_AUTH_BACKUP_KEEP", "30"))
        try:
            self.interval = float(os.environ.get("MR_AUTH_BACKUP_HOURS", "24")) * 3600.0
        except ValueError:
            self.interval = 24 * 3600.0
        self._stop = False
        self._last = 0.0
        self._ledger = []              # 최근 백업 기록(최대 20)

    # -- core -------------------------------------------------------------- #
    def list(self):
        items = []
        try:
            names = os.listdir(self.dir)
        except OSError:
            return items
        for name in names:
            if not (name.startswith("auth-") and name.endswith(".json")):
                continue
            full = os.path.join(self.dir, name)
            try:
                stt = os.stat(full)
            except OSError:
                continue
            items.append({"name": name, "bytes": stt.st_size,
                          "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stt.st_mtime))})
        items.sort(key=lambda x: x["name"], reverse=True)
        return items

    def backup(self, why="auto"):
        """지금 백업. 반환: {"ok":bool, "name":..., "error":...}"""
        try:
            with io.open(self.src, "r", encoding="utf-8") as f:
                text = f.read()
            data = json.loads(text)
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": "auth.json 읽기 실패: %s" % exc}
        if not data.get("hash") or not data.get("secret"):
            return {"ok": False, "error": "auth.json 형식이 아닙니다"}

        try:
            os.makedirs(self.dir, exist_ok=True)
            try:
                os.chmod(self.dir, 0o700)
            except OSError:
                pass
        except OSError as exc:
            return {"ok": False, "error": "백업 폴더 생성 실패: %s" % exc}

        name = "auth-%s.json" % time.strftime("%Y%m%d-%H%M%S")
        full = os.path.join(self.dir, name)
        tmp = full + ".tmp"
        try:
            with io.open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, full)
        except OSError as exc:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return {"ok": False, "error": "쓰기 실패: %s" % exc}

        self._prune()
        self._last = time.time()
        self._ledger.append({"at": time.strftime("%H:%M:%S"), "name": name, "why": why})
        del self._ledger[:-20]
        return {"ok": True, "name": name, "dir": self.dir}

    def _prune(self):
        items = self.list()
        for it in items[self.keep:]:
            try:
                os.remove(os.path.join(self.dir, it["name"]))
            except OSError:
                pass

    # -- 주기 실행 --------------------------------------------------------- #
    def status(self):
        return {"dir": self.dir, "keep": self.keep,
                "hours": round(self.interval / 3600.0, 1),
                "last": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._last)) if self._last else None,
                "items": self.list()[:10], "total": len(self.list()),
                "recent": list(self._ledger)[-5:]}

    def run(self):
        # 시작 직후 1회(계정이 있으면) → 이후 interval 마다
        while not self._stop:
            try:
                if os.path.isfile(self.src) and (time.time() - self._last) >= self.interval:
                    self.backup("auto")
            except Exception:                  # noqa: BLE001
                pass
            for _ in range(60):
                if self._stop:
                    break
                time.sleep(1.0)

    def stop(self):
        self._stop = True
