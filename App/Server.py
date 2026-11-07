# -*- coding: utf-8 -*-
"""부트스트랩: 설정 → 앱 구성 → 자식 기동 → HTTP 서버 → 종료 처리."""

import io
import json
import os
import signal
import sys
import threading
import time

from . import VERSION
from .AccessLog import AccessLog
from .AuthBackup import AuthBackup
from .AuthStore import AuthStore
from .Context import CTX
from .DuelProxy import DuelProxy
from .GhostRooms import GhostReaper
from .MercuryFront import MercuryFront
from .HttpApi import Handler, PanelServer
from .Settings import Settings, ensure_persist_link
from .Supervisor import Supervisor


class App(object):
    """패널 하나 = Settings + Supervisor (테스트에서도 이 단위로 만든다)."""

    def __init__(self, st):
        self.st = st
        self.sup = Supervisor(st)
        self.auth = AuthStore(st.auth_path)
        self.proxy = DuelProxy(st, self.sup.log)
        # 기록용: 외부 서버로 그대로 흘려보내며 양방향 프레임을 로그로 남긴다
        self.proxy2 = DuelProxy(st, self.sup.log, label="relay", drop_types=set(),
                                target=st.proxy2_target)
        self.access = AccessLog(st)
        self.authbackup = AuthBackup(st)
        self.front = MercuryFront(st, self.sup.log)
        self.front.access = self.access
        self.ghost = None


def build_app(st):
    app = App(st)
    CTX.bind(app)
    return app


def main(argv):
    if "--restore-auth" in argv:
        import shutil
        st = Settings()
        try:
            src = argv[argv.index("--restore-auth") + 1]
        except IndexError:
            print("사용법: webui.py --restore-auth <auth-....json>")
            return 2
        if not os.path.isfile(src):
            print("파일 없음: %s" % src)
            return 2
        try:
            with io.open(src, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data.get("hash") or not data.get("secret"):
                print("auth.json 형식이 아닙니다")
                return 2
        except (OSError, ValueError) as exc:
            print("읽기 실패: %s" % exc)
            return 2
        if os.path.isfile(st.auth_path):
            shutil.copy2(st.auth_path, st.auth_path + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(src, st.auth_path)
        try:
            os.chmod(st.auth_path, 0o600)
        except OSError:
            pass
        print("복원 완료: %s → %s" % (src, st.auth_path))
        print("패널을 재시작해야 적용됩니다.")
        return 0

    if "--selftest" in argv:
        from .SelfTest import selftest

        return selftest()

    st = Settings()
    app = build_app(st)
    app.sup.log("[webui] v%s starting (base=%s, bin=%s)" % (VERSION, st.base, st.bin))

    if st.config_persist:
        linked = ensure_persist_link(st)
        app.sup.log(
            "[webui] config: %s -> %s (%s)"
            % (st.config_path, st.real_config(), "linked" if linked else "FAILED")
        )
    if not os.path.exists(st.real_config()):
        app.sup.log("[webui] WARNING: %s not found - multirole will fail to boot" % st.real_config())
    if not st.token:
        app.sup.log("[webui] WARNING: WEB_TOKEN is empty -> no authentication")

    def on_term(signum, frame):
        app.sup.log("[webui] signal %s -> shutting down" % signum)
        if getattr(app, "authbackup", None):
            try:
                app.authbackup.stop()
            except Exception:
                pass
        if getattr(app, "ghost", None):
            try:
                app.ghost.stop()
            except Exception:
                pass
        for p in (getattr(app, "proxy", None), getattr(app, "proxy2", None), getattr(app, "front", None)):
            try:
                if p:
                    p.stop()
            except Exception:
                pass
        app.sup.shutdown()
        os._exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, on_term)
        except (ValueError, OSError):
            pass

    app.sup.start()
    threading.Thread(target=app.sup.loop, daemon=True).start()
    if st.proxy_port > 0:
        try:
            app.proxy.start()
        except OSError as exc:
            app.sup.log("[proxy] 시작 실패: %s" % exc)
    if st.proxy2_port > 0 and st.proxy2_target:
        try:
            app.proxy2.start(port=st.proxy2_port)
        except OSError as exc:
            app.sup.log("[relay] 시작 실패: %s" % exc)
    if st.front_port > 0:
        try:
            app.front.start()
        except OSError as exc:
            app.sup.log("[front] 시작 실패: %s" % exc)

    app.ghost = GhostReaper(st, app, app.sup.log)
    app.ghost.start()
    threading.Thread(target=app.authbackup.run, daemon=True, name="auth-backup").start()

    httpd = PanelServer((st.bind, st.port), Handler)
    app.sup.log("[webui] listening on http://%s:%d" % (st.bind, st.port))
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.sup.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
