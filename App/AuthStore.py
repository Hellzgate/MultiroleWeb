# -*- coding: utf-8 -*-
"""관리자 계정 저장/검증 (패널 자체 계정).

`auth.json` (바인드 마운트 폴더) 예:
    { "version": 1, "id": "admin",
      "salt": "<hex>", "hash": "<pbkdf2-sha256 hex>", "iterations": 200000,
      "secret": "<hex 32B>", "createdAt": "2026-11-07T..." }

- 비밀번호는 **저장하지 않는다**(PBKDF2 해시만).
- 세션 쿠키는 `secret` 으로 HMAC 서명한 `<id>.<만료 epoch>.<서명>` 이라
  매 요청마다 해시를 비교하지 않는다.
- 실패 잠금: 같은 IP 에서 N회 실패하면 일정 시간 차단(메모리).
"""

import hashlib
import hmac
import io
import json
import os
import secrets
import time

ITERATIONS = 100_000
SESSION_TTL = 12 * 3600          # 12시간
MAX_FAILS = 5
LOCK_SECONDS = 60
COOKIE = "mr_session"

_fails = {}                      # ip -> [count, until_epoch]


def _now():
    return int(time.time())


def _pbkdf2_py(password, salt, iterations, dklen=32):
    """hashlib.pbkdf2_hmac 이 없는 환경(OpenSSL 미포함 파이썬)용 순수 구현."""
    import struct

    def prf(key, msg):
        return hmac.new(key, msg, hashlib.sha256).digest()

    blocks = (dklen + 31) // 32
    out = []
    for i in range(1, blocks + 1):
        u = prf(password, salt + struct.pack(">I", i))
        acc = bytearray(u)
        for _ in range(iterations - 1):
            u = prf(password, u)
            for j in range(32):
                acc[j] ^= u[j]
        out.append(bytes(acc))
    return b"".join(out)[:dklen]


def hash_password(password, salt_hex=None, iterations=ITERATIONS):
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    raw = password.encode("utf-8")
    try:
        digest = hashlib.pbkdf2_hmac("sha256", raw, salt, iterations)
    except AttributeError:          # 컨테이너 파이썬이 _hashlib 없이 빌드된 경우
        digest = _pbkdf2_py(raw, salt, iterations)
    return salt.hex(), digest.hex(), iterations


def verify_password(password, salt_hex, hash_hex, iterations):
    _, digest, _ = hash_password(password, salt_hex, iterations)
    return hmac.compare_digest(digest, hash_hex)


class AuthStore(object):
    def __init__(self, path):
        self.path = path
        self.data = None
        self._mtime = None
        self.load()

    # -- 저장/로드 -------------------------------------------------------- #
    def load(self):
        try:
            with io.open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            self.data = None
            return None
        if not isinstance(data, dict) or not data.get("hash"):
            self.data = None
            return None
        self.data = data
        try:
            self._mtime = os.stat(self.path).st_mtime
        except OSError:
            self._mtime = None
        return data

    def _maybe_reload(self):
        """다른 프로세스가 auth.json 을 만들거나 지웠을 때(예: --reset-auth) 다시 읽는다."""
        try:
            mtime = os.stat(self.path).st_mtime
        except OSError:
            if self.data is not None:
                self.data = None
                self._mtime = None
            return
        if self._mtime != mtime:
            self.load()

    def exists(self):
        self._maybe_reload()
        return self.data is not None

    def _save(self, data):
        dirname = os.path.dirname(self.path) or "."
        try:
            os.makedirs(dirname, exist_ok=True)
        except OSError:
            pass
        tmp = self.path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)
        self.data = data

    # -- 계정 ------------------------------------------------------------- #
    def create(self, admin_id, password):
        admin_id = (admin_id or "").strip()
        if not admin_id:
            return "아이디를 입력하세요"
        if len(password or "") < 4:
            return "비밀번호는 4자 이상으로 하세요"
        salt, digest, iters = hash_password(password)
        self._save({
            "version": 1,
            "id": admin_id,
            "salt": salt,
            "hash": digest,
            "iterations": iters,
            "secret": secrets.token_hex(32),
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        return None

    def check(self, admin_id, password):
        self._maybe_reload()
        d = self.data
        if not d:
            return False, "계정이 없습니다"
        if not hmac.compare_digest((admin_id or "").strip(), d.get("id", "")):
            return False, "아이디 또는 비밀번호가 다릅니다"
        if not verify_password(password or "", d["salt"], d["hash"], d.get("iterations", ITERATIONS)):
            return False, "아이디 또는 비밀번호가 다릅니다"
        return True, ""

    def change_password(self, old, new):
        ok, msg = self.check(self.data.get("id") if self.data else "", old)
        if not ok:
            return msg or "현재 비밀번호가 다릅니다"
        if len(new or "") < 4:
            return "새 비밀번호는 4자 이상으로 하세요"
        d = dict(self.data)
        salt, digest, iters = hash_password(new)
        d.update({"salt": salt, "hash": digest, "iterations": iters})
        self._save(d)
        return None

    def reset(self):
        try:
            os.remove(self.path)
        except OSError:
            pass
        self.data = None

    # -- 세션 쿠키 -------------------------------------------------------- #
    def issue(self):
        d = self.data
        if not d:
            return None
        exp = _now() + SESSION_TTL
        payload = "%s.%d" % (d.get("id", ""), exp)
        sig = hmac.new(bytes.fromhex(d["secret"]), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return "%s.%s" % (payload, sig)

    def verify_session(self, cookie_value):
        self._maybe_reload()
        d = self.data
        if not d or not cookie_value:
            return False
        parts = cookie_value.rsplit(".", 2)
        if len(parts) != 3:
            return False
        admin_id, exp_s, sig = parts
        try:
            exp = int(exp_s)
        except ValueError:
            return False
        if exp < _now():
            return False
        payload = "%s.%d" % (admin_id, exp)
        want = hmac.new(bytes.fromhex(d["secret"]), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, want):
            return False
        return hmac.compare_digest(admin_id, d.get("id", ""))

    # -- 실패 잠금 -------------------------------------------------------- #
    def locked(self, ip):
        info = _fails.get(ip)
        if not info:
            return 0
        if info[1] > _now():
            return info[1] - _now()
        return 0

    def note_fail(self, ip):
        info = _fails.get(ip, [0, 0])
        if info[1] > _now():
            return                      # 이미 잠긴 상태 → 연장/초기화하지 않는다
        count = info[0] + 1
        if count >= MAX_FAILS:
            _fails[ip] = [0, _now() + LOCK_SECONDS]
        else:
            _fails[ip] = [count, 0]

    def clear_fails(self, ip):
        _fails.pop(ip, None)
