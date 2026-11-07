# -*- coding: utf-8 -*-
"""--selftest : 도커 없이 설정/슈퍼바이저/HTTP 를 실제로 검사한다.

가짜 자식 프로세스(python -c)를 띄워 다음을 확인한다.
  · config 로드/검증(포트 중복·필수 키·sink 타입·토큰 경고)
  · 원자적 저장 · 백업 · 탭 들여쓰기 · 실패 시 원본 유지
  · 심볼릭 링크 영속화(바인드 마운트 흉내)
  · 슈퍼바이저 기동/로그/중지/재시작/해시
  · 상태 수집(HEAD·provider 파일 수·리플레이·포트)
  · HTTP 401 · /api/ping · GET/PUT config · 422 · 로그 · 리플레이 다운로드(경로 탈출 차단) · start/stop/restart
"""

import json
import os
import socket as pysocket
import struct
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

from .Context import CTX
from .DuelProxy import DuelProxy
from .HttpApi import Handler, PanelServer
from .Server import App
from .Settings import Settings, ensure_persist_link
from .ConfigStore import ConfigError, load_config, save_config
from .ConfigSchema import validate
from .Status import collect_ping, collect_status


def _sample_config():
    return {
        "concurrencyHint": -1,
        "lobbyListingPort": 7922,
        "lobbyMaxConnections": 4,
        "roomHostingPort": 7911,
        "repos": [
            {
                "name": "scripts",
                "remote": "https://example.invalid/CardScripts",
                "path": "./sync/scripts/",
                "webhookPort": 34343,
                "webhookToken": "tok",
            }
        ],
        "banlistProvider": {"observedRepos": ["scripts"], "fileRegex": ".*\\.lflist\\.conf"},
        "coreProvider": {
            "observedRepos": ["scripts"],
            "fileRegex": ".*libocgcore\\.so",
            "tmpPath": "./tmp/",
            "coreType": "hornet",
            "loadPerRoom": True,
        },
        "dataProvider": {"observedRepos": ["scripts"], "fileRegex": ".*\\.cdb"},
        "logHandler": {
            "serviceSinks": {"multirole": {"type": "stdout", "properties": {}}},
            "ecSinks": {"core": {"type": "stderr", "properties": {}}},
            "roomLogging": {"enabled": False, "path": "./room-logs/"},
        },
        "replayManager": {"save": True, "path": "./replays/"},
        "scriptProvider": {"observedRepos": ["scripts"], "fileRegex": ".*\\.lua"},
    }


def _make_fixture(tmp):
    os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
    git = os.path.join(tmp, "sync", "scripts", ".git")
    os.makedirs(os.path.join(git, "refs", "heads"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "replays"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "tmp"), exist_ok=True)
    with open(os.path.join(tmp, "replays", "test.yrpX"), "wb") as f:
        f.write(b"\x00" * 128)
    with open(os.path.join(git, "HEAD"), "w") as f:
        f.write("ref: refs/heads/master\n")
    with open(os.path.join(git, "refs", "heads", "master"), "w") as f:
        f.write("deadbeefcafe1234567890\n")
    for name in ("c123.lua", "c456.lua"):
        with open(os.path.join(tmp, "sync", "scripts", name), "w") as f:
            f.write("-- lua\n")


def selftest():
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    tmp = tempfile.mkdtemp(prefix="mrweb-selftest-")
    _make_fixture(tmp)
    sample = _sample_config()
    cfg_path = os.path.join(tmp, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(sample, f, indent="\t")

    st = Settings(base=tmp)
    st.bin = sys.executable
    st.args = [
        "-c",
        "import time,sys\nprint('selftest-child-ready', flush=True)\nwhile True: time.sleep(0.5)",
    ]
    st.token = "secret-token"
    st.restart_delay = 0.5

    app = App(st)
    CTX.bind(app)
    app.sup.echo = False          # 검사 결과 출력을 깔끔하게

    # -- config ---------------------------------------------------------- #
    cfg = load_config(st)
    check("config.load", cfg["roomHostingPort"] == 7911)
    errors, _w = validate(cfg)
    check("config.validate.ok", not errors, "; ".join(errors))

    bad = json.loads(json.dumps(cfg))
    bad["repos"][0]["webhookPort"] = 7922
    errors, _ = validate(bad)
    check("config.validate.port-clash", bool(errors), str(errors[:2]))

    # -- 관리자 계정 (AuthStore) ------------------------------------------ #
    from .AuthStore import AuthStore

    as_path = os.path.join(tmp, "auth.json")
    store = AuthStore(as_path)
    check("auth.empty", not store.exists())
    check("auth.create", store.create("admin", "pw1234") is None and store.exists()
          and store.data.get("id") == "admin" and "pw1234" not in json.dumps(store.data))
    ok1, _ = store.check("admin", "pw1234")
    ok2, _ = store.check("admin", "wrong")
    check("auth.check", ok1 and not ok2)
    sess = store.issue()
    check("auth.session", store.verify_session(sess) and not store.verify_session("a.b.c"))
    check("auth.password-change",
          store.change_password("pw1234", "newpass") is None
          and store.check("admin", "newpass")[0]
          and not store.check("admin", "pw1234")[0])
    for _ in range(5):
        store.note_fail("1.2.3.4")
    check("auth.lockout", store.locked("1.2.3.4") > 0)
    store.clear_fails("1.2.3.4")
    check("auth.unlock", store.locked("1.2.3.4") == 0)
    store.reset()
    check("auth.reset", not store.exists())

    # -- 방 이름/규칙 파서 (RoomSpec) ------------------------------------- #
    from . import RoomSpec

    base = st.effective_room()
    spec = RoomSpec.parse("MTG", base)
    check("room.name", spec["name"] == "MTG" and spec["password"] == "", spec["name"])

    spec = RoomSpec.parse("mtg#1234", base)
    check("room.password", spec["name"] == "mtg" and spec["password"] == "1234")

    spec = RoomSpec.parse("m#1#l=4000,t=300", base)
    check("room.options",
          spec["opts"]["lp"] == 4000 and spec["opts"]["time"] == 300 and not spec["warnings"],
          str(spec["opts"]))

    spec = RoomSpec.parse("#lp=4000", base)
    check("room.option-only", spec["name"] == base["default_room"] and spec["opts"]["lp"] == 4000)

    spec = RoomSpec.parse("공개", base)
    check("room.alias", spec["name"] == base["default_room"])

    spec = RoomSpec.parse("a b  c", base)
    check("room.spaces", spec["name"] == "a_b_c", spec["name"])

    spec = RoomSpec.parse("x" * 30, base)
    check("room.truncate", len(spec["name"]) == RoomSpec.MAX_NAME_CHARS)

    spec = RoomSpec.parse("m#1#m=50-55", base)
    check("room.range", spec["opts"]["main_min"] == 50 and spec["opts"]["main_max"] == 55,
          str(spec["opts"]))

    spec = RoomSpec.parse("m#1#zz=1", base)
    check("room.bad-option", any("zz" in w for w in spec["warnings"]), str(spec["warnings"]))

    spec = RoomSpec.parse("mtg#lp=4000", base)
    check("room.notes", "LP4000" in spec["notes"] and spec["notes"].startswith("mtg"), spec["notes"])

    spec = RoomSpec.parse("mtg#1#l=4000,t=300", base)
    check("room.short-keys",
          spec["opts"]["lp"] == 4000 and spec["opts"]["time"] == 300 and not spec["warnings"],
          str(spec["warnings"]))

    spec = RoomSpec.parse("m#1#r=4", base)
    pkt = RoomSpec.build_create_game(spec, 4043399681, (41, 0), (11, 0))
    check("room.mr-flags",
          struct.unpack("<I", pkt[3 + 44:3 + 48])[0] == RoomSpec.MR_FLAGS[4] != 0
          and pkt[3 + 6] == 4, hex(RoomSpec.MR_FLAGS[4]))

    spec = RoomSpec.parse("m#1#mode=any", base)
    check("room.mode-any", spec["opts"]["mode"] == "any" and not spec["warnings"], str(spec["warnings"]))

    create = RoomSpec.build_create_game(spec, 4043399681, (41, 0), (11, 0))
    join = RoomSpec.build_join(7, "pw", (41, 0), (11, 0))
    check("room.packets",
          len(create) == 351 and len(join) == 55
          and struct.unpack("<H", create[:2])[0] == 349
          and struct.unpack("<H", join[:2])[0] == 53,
          "create=%d join=%d" % (len(create), len(join)))

    # 예전 버그 재현 방지: <select> 가 보내는 문자열("3")도 저장돼야 한다
    st.save_room_overrides({"best": "3", "mr": "4", "lp": "5000", "banlist": "OCG.lflist.conf|2023.10 OCG"})
    eff2 = st.effective_room()
    check("room.coerce", eff2["best"] == 3 and eff2["mr"] == 4 and eff2["lp"] == 5000
          and eff2["banlist"].startswith("OCG"), str(st.room_overrides))
    st.save_room_overrides({})

    # 금지/제한 목록 해시 (Multirole BanlistParser 와 같은 알고리즘)
    from . import Banlists
    sample = os.path.join(tmp, "sample.lflist.conf")
    with open(sample, "w", encoding="utf-8") as fh:
        fh.write("!2023.10 OCG\n49033797 0\n14558127 1\n23434538 2\n")
    secs = Banlists.parse_sections(sample)
    expect = Banlists.BANLIST_HASH_MAGIC
    for code, cnt in ((49033797, 0), (14558127, 1), (23434538, 2)):
        expect = Banlists._salt(expect, code, cnt)
    check("room.banlist-hash",
          len(secs) == 1 and secs[0]["hash"] == expect and secs[0]["cards"] == 3,
          str(secs))

    saved = st.save_room_overrides({"lp": 4000, "default_room": "pub"})
    eff = st.effective_room()
    st.load_room_overrides()
    check("room.persist",
          saved.get("lp") == 4000 and eff["lp"] == 4000 and eff["default_room"] == "pub"
          and st.effective_room()["lp"] == 4000 and os.path.isfile(st.front_json))
    st.save_room_overrides({})

    bad2 = json.loads(json.dumps(cfg))
    del bad2["lobbyMaxConnections"]
    errors, _ = validate(bad2)
    check("config.validate.missing-key", any("lobbyMaxConnections" in e for e in errors))

    bad3 = json.loads(json.dumps(cfg))
    bad3["coreProvider"]["coreType"] = "bogus"
    errors, _ = validate(bad3)
    check("config.validate.core-type", bool(errors))

    bad4 = json.loads(json.dumps(cfg))
    bad4["logHandler"]["serviceSinks"]["multirole"] = {"type": "file", "properties": {}}
    errors, _ = validate(bad4)
    check("config.validate.file-sink", any("properties.path" in e for e in errors))

    warn_cfg = json.loads(json.dumps(cfg))
    warn_cfg["repos"][0]["webhookToken"] = "<change_this>"
    _e, w = validate(warn_cfg)
    check("config.validate.token-warning", any("change_this" in x for x in w), str(w))

    changed = json.loads(json.dumps(cfg))
    changed["concurrencyHint"] = 4
    save_config(st, changed)
    check("config.save.applied", load_config(st)["concurrencyHint"] == 4)
    baks = [f for f in os.listdir(tmp) if f.startswith("config.json.bak-")]
    check("config.save.backup", len(baks) == 1, str(baks))
    check("config.save.tmp-gone", not os.path.exists(cfg_path + ".tmp"))
    with open(cfg_path, "r", encoding="utf-8") as f:
        check("config.save.tab-indent", "\n\t\"concurrencyHint\"" in f.read())

    try:
        save_config(st, {"concurrencyHint": 1})
        check("config.save.rejects-invalid", False)
    except ConfigError:
        check("config.save.rejects-invalid", True)
    check("config.save.keeps-original", load_config(st)["concurrencyHint"] == 4)

    # -- 영속화 심볼릭 링크 ------------------------------------------------ #
    persist_dir = os.path.join(tmp, "mounted")
    os.makedirs(persist_dir, exist_ok=True)
    st.config_persist = os.path.join(persist_dir, "config.json")
    ok = ensure_persist_link(st)
    check(
        "persist.link-created",
        ok and os.path.islink(st.config_path)
        and os.path.realpath(st.config_path) == os.path.realpath(st.config_persist),
        "link=%s real=%s" % (os.path.islink(st.config_path), st.real_config()),
    )
    c3 = load_config(st)
    c3["concurrencyHint"] = 9
    save_config(st, c3)
    with open(st.config_persist, "r", encoding="utf-8") as f:
        check("persist.write-through", json.load(f)["concurrencyHint"] == 9)
    check("persist.link-kept", os.path.islink(st.config_path))
    check("persist.backup-in-mount", any(x.startswith("config.json.bak-") for x in os.listdir(persist_dir)))
    st.config_persist = ""

    # -- supervisor ------------------------------------------------------ #
    ok = app.sup.start()
    time.sleep(1.2)
    check("supervisor.start", ok and app.sup.is_running(), "pid=%s" % (app.sup.proc.pid if app.sup.proc else None))
    check("supervisor.log-pumped", any("selftest-child-ready" in l for l in app.sup.tail(50)))
    check("supervisor.log-file", os.path.exists(st.log_path) and os.path.getsize(st.log_path) > 0)
    check("supervisor.running-hash", bool(app.sup.running_hash))

    app.sup.stop(graceful=True)
    time.sleep(0.4)
    check("supervisor.stop", not app.sup.is_running())

    app.sup.want = True
    app.sup.start()
    time.sleep(0.8)
    check("supervisor.restart", app.sup.is_running())
    check("supervisor.uptime", app.sup.uptime() >= 0)

    c2 = load_config(st)
    c2["concurrencyHint"] = 8
    save_config(st, c2)

    # -- status ---------------------------------------------------------- #
    stt = collect_status(st, app.sup)
    check("status.process", stt["process"]["running"] is True)
    check("status.config.pending", stt["config"]["pendingRestart"] is True, str(stt["config"]))
    ping = collect_ping(st, app.sup)
    check("ping.light", ping["process"]["running"] is True and "repos" not in ping, str(list(ping.keys())))
    check("status.repos.head", stt["repos"][0]["head"] == "deadbeefcafe", str(stt["repos"][0]))
    check(
        "status.providers.scripts",
        any(p["name"] == "scriptProvider" and p["files"] == 2 for p in stt["providers"]),
        str(stt["providers"]),
    )
    check("status.replays", stt["replays"]["count"] == 1 and stt["replays"]["latest"] == "test.yrpX")
    check("status.ports.listening", isinstance(stt["ports"], list) and len(stt["ports"]) == 2)

    # -- duel proxy (0x17 제거) ------------------------------------------- #
    received = []
    fake = pysocket.socket(pysocket.AF_INET, pysocket.SOCK_STREAM)
    fake.setsockopt(pysocket.SOL_SOCKET, pysocket.SO_REUSEADDR, 1)
    fake.bind(("127.0.0.1", 0))
    fake.listen(4)
    fake_port = fake.getsockname()[1]

    def fake_accept():
        try:
            conn, _addr = fake.accept()
            while True:
                d = conn.recv(4096)
                if not d:
                    break
                received.append(d)
                conn.sendall(b"HELLO")
            conn.close()
        except OSError:
            pass

    threading.Thread(target=fake_accept, daemon=True).start()

    st.proxy_target_host = "127.0.0.1"
    st.proxy_target_port = fake_port
    proxy = DuelProxy(st, app.sup.log)
    started = proxy.start(port=0)
    check("proxy.start", started and proxy.port > 0, "port=%s" % proxy.port)

    def frame(t, body):
        # Multirole 규약: 길이 필드 = body+1, 실제 바이트 = 필드+2
        return struct.pack("<H", len(body) + 1) + bytes([t]) + body

    cli = pysocket.create_connection(("127.0.0.1", proxy.port), timeout=5)
    cli.sendall(frame(0x17, b"\x00\x00\x00\x00"))                      # 버려져야 함
    cli.sendall(frame(0x10, "Hellz".encode("utf-16-le") + b"\x00\x00"))  # 통과해야 함
    time.sleep(0.5)
    cli.settimeout(2)
    got = b""
    try:
        got = cli.recv(64)
    except OSError:
        pass
    cli.close()
    proxy.stop()
    try:
        fake.close()
    except OSError:
        pass
    upstream = b"".join(received)
    check("proxy.drop-0x17", proxy.dropped == 1, "dropped=%d" % proxy.dropped)
    check("proxy.pass-only-player-info", len(upstream) == 15 and upstream[2] == 0x10, upstream.hex())
    check("proxy.relay-back", got == b"HELLO", got[:16])
    # -- http ------------------------------------------------------------ #
    httpd = PanelServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
    base = "http://127.0.0.1:%d" % port

    def call(method, path, body=None, token="secret-token"):
        data = None
        hdrs = {}
        if token:
            hdrs["Cookie"] = "mr_auth=" + token
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        for attempt in (1, 2, 3):
            req = urllib.request.Request(base + path, data=data, headers=hdrs, method=method)
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()
            except Exception as exc:  # Windows 에서 간혹 나는 RST 대비
                if attempt == 3:
                    return -1, repr(exc).encode()
                time.sleep(0.3)

    code, body = call("GET", "/api/health", token=None)
    check("http.health", code == 200 and b'"ok"' in body)

    code, _ = call("GET", "/api/status", token=None)
    check("http.auth-required", code == 401)

    code, body = call("GET", "/api/ping")
    check("http.ping", code == 200 and b'"running"' in body and b'"repos"' not in body)

    code, body = call("GET", "/api/config")
    check("http.get-config", code == 200 and b"webhookToken" in body)
    check("http.docs", b"concurrencyHint" in body and "자동".encode("utf-8") in body)

    code, body = call("GET", "/")
    check("http.index", code == 200 and b"<html" in body.lower())
    check("http.index-inlined", b'<script src="/js/' not in body and b"MR.state" in body, str(len(body)))
    code, body = call("GET", "/?raw=1")
    check("http.index-raw", code == 200 and b'<script src="/js/Util.js"' in body)
    code, body = call("GET", "/app.css")
    check("http.static-css", code == 200 and b"{" in body)
    code, body = call("GET", "/js/App.js")
    check("http.static-js", code == 200 and b"MR" in body)
    code, _ = call("GET", "/js/../../webui.py")
    check("http.static-traversal", code in (404, 400))

    code, body = call("PUT", "/api/config", changed)
    check("http.put-config", code == 200 and b'"ok"' in body, body[:120].decode("utf-8", "replace"))

    bad = json.loads(json.dumps(changed))
    bad["repos"][0]["webhookPort"] = 0
    code, body = call("PUT", "/api/config", bad)
    check("http.put-invalid", code == 422 and b"webhookPort" in body)

    code, body = call("GET", "/api/logs?tail=10")
    check("http.logs", code == 200 and b"selftest-child-ready" in body)

    code, body = call("GET", "/api/replays")
    check("http.replays", code == 200 and b"test.yrpX" in body)

    code, body = call("GET", "/api/replay?name=../config.json")
    check("http.replay-traversal-blocked", code == 404)

    code, body = call("GET", "/api/replay?name=test.yrpX")
    check("http.replay-download", code == 200 and len(body) == 128)

    code, body = call("GET", "/api/front")
    check("http.front-get", code == 200 and b'"default_room"' in body and b'"docs"' in body)

    code, body = call("PUT", "/api/front", {"room": {"lp": 5000, "default_room": "zzz"}})
    check("http.front-put", code == 200 and b'"ok"' in body, body[:160].decode("utf-8", "replace"))

    code, body = call("GET", "/api/front")
    check("http.front-applied", b'"lp": 5000' in body or b'"lp":5000' in body)

    code, body = call("PUT", "/api/front", {"nope": 1})
    check("http.front-invalid", code == 400)

    code, body = call("POST", "/api/sync", {"name": "nope"})
    check("http.sync-unknown", code == 404)

    code, _ = call("POST", "/api/start")
    check("http.start", code == 200)
    code, _ = call("POST", "/api/stop")
    check("http.stop", code == 200)
    time.sleep(1.0)
    check("http.stop-effective", not app.sup.is_running())
    code, _ = call("POST", "/api/restart")
    check("http.restart", code == 200)
    time.sleep(1.5)
    check("http.restart-effective", app.sup.is_running())

    httpd.shutdown()
    app.sup.shutdown()

    # -- report ---------------------------------------------------------- #
    from . import VERSION

    print("Multirole Web UI selftest (v%s) — modular build" % VERSION)
    print("-" * 62)
    failed = 0
    for name, passed, detail in checks:
        if not passed:
            failed += 1
        print("  %-32s %s%s" % (name, "PASS" if passed else "FAIL", ("  " + detail) if (detail and not passed) else ""))
    print("-" * 62)
    total = len(checks)
    print("  %d/%d PASS%s" % (total - failed, total, "" if failed == 0 else "  <-- FAILURES"))
    print("  temp: %s" % tmp)
    return 0 if failed == 0 else 1
