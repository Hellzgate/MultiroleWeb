# -*- coding: utf-8 -*-
"""상태 수집.

collect_ping   : 헤더가 5초마다 부르는 **가벼운** 응답(디렉터리 순회 없음)
collect_status : 상태 탭용 **전체** 응답(리포 HEAD · provider 파일 수 · 리플레이 · 코어 · 포트)
"""

import os

from . import VERSION
from .ConfigSchema import is_int
from .ConfigStore import ConfigError, load_config
from .GitSync import SyncState
from .SysInfo import (
    client_counts,
    count_matching,
    file_sha256,
    git_head,
    mtime_str,
    now_str,
    port_open,
    time_str,
)

PROVIDER_ORDER = ("scriptProvider", "dataProvider", "banlistProvider", "coreProvider")


def _process_block(sup):
    running = sup.is_running()
    return {
        "running": running,
        "pid": sup.proc.pid if running else None,
        "uptime": sup.uptime(),
        "restarts": sup.restarts,
        "lastExit": sup.last_exit,
        "want": sup.want,
    }


def _ports_of(cfg):
    if not isinstance(cfg, dict):
        return []
    return [p for p in (cfg.get("lobbyListingPort"), cfg.get("roomHostingPort")) if is_int(p)]


def collect_ping(st, sup):
    """Cheap subset for the 5s header poll (no directory walks)."""
    cfg = None
    try:
        cfg = load_config(st)
    except ConfigError:
        pass
    ports = _ports_of(cfg)
    cur_hash = file_sha256(st.real_config())
    running = sup.is_running()
    return {
        "now": now_str(),
        "process": _process_block(sup),
        "config": {
            "sha256": cur_hash[:16],
            "pendingRestart": bool(running and sup.running_hash and sup.running_hash != cur_hash),
        },
        "clients": client_counts(ports) if ports else None,
    }


def _collect_repos(st, cfg):
    repos = []
    for r in cfg.get("repos") or []:
        if not isinstance(r, dict):
            continue
        p = st.rel(r.get("path"))
        fetch_head = os.path.join(p, ".git", "FETCH_HEAD")
        repos.append(
            {
                "name": r.get("name"),
                "path": p,
                "exists": os.path.isdir(p),
                "head": git_head(p),
                "fetched": mtime_str(fetch_head) if os.path.exists(fetch_head) else None,
            }
        )
    return repos


def _collect_providers(cfg, repos):
    by_name = dict((x["name"], x) for x in repos)
    providers = []
    for name in PROVIDER_ORDER:
        prov = cfg.get(name) or {}
        if not isinstance(prov, dict):
            continue
        roots = []
        for obs in prov.get("observedRepos") or []:
            rp = by_name.get(obs)
            if rp:
                roots.append(rp["path"])
        regex = prov.get("fileRegex") or "$^"
        total = 0
        for root in roots:
            total += count_matching(root, regex)
        providers.append({"name": name, "files": total, "repos": list(prov.get("observedRepos") or [])})
    return providers


def _collect_replays(st, cfg):
    rp = st.rel((cfg.get("replayManager") or {}).get("path"))
    result = {"count": 0, "latest": None, "latestTime": None, "bytes": 0, "dir": rp}
    if not os.path.isdir(rp):
        return result
    latest = None
    n = 0
    total = 0
    try:
        names = os.listdir(rp)
    except OSError:
        return result
    for fn in names:
        if not fn.lower().endswith(".yrpx"):
            continue
        full = os.path.join(rp, fn)
        try:
            mt = os.path.getmtime(full)
            sz = os.path.getsize(full)
        except OSError:
            continue
        n += 1
        total += sz
        if latest is None or mt > latest[1]:
            latest = (fn, mt)
    result.update(
        {
            "count": n,
            "bytes": total,
            "latest": latest[0] if latest else None,
            "latestTime": time_str(latest[1]) if latest else None,
        }
    )
    return result


def _collect_cores(st, cfg):
    tmp_dir = st.rel((cfg.get("coreProvider") or {}).get("tmpPath"))
    files = []
    if os.path.isdir(tmp_dir):
        try:
            files = sorted(os.listdir(tmp_dir))[:20]
        except OSError:
            pass
    return {"files": files}, tmp_dir


def collect_status(st, sup):
    cfg = None
    cfg_err = None
    try:
        cfg = load_config(st)
    except ConfigError as exc:
        cfg_err = exc.errors[0]

    running = sup.is_running()
    cur_hash = file_sha256(st.real_config())

    repos, providers = [], []
    replays = {"count": 0, "latest": None, "latestTime": None, "bytes": 0}
    cores, tmp_dir = {"files": []}, None
    if isinstance(cfg, dict):
        repos = _collect_repos(st, cfg)
        providers = _collect_providers(cfg, repos)
        replays = _collect_replays(st, cfg)
        cores, tmp_dir = _collect_cores(st, cfg)

    # 리포별 '마지막 갱신 결과'(sync.json) — 실패 사유·커밋 목록까지 표에 보여준다
    sync_state = None
    try:
        sync_state = SyncState(st.sync_state_path)
    except Exception:                                   # noqa: BLE001
        sync_state = None
    for repo in repos:
        repo["lastSync"] = sync_state.get(repo.get("name")) if sync_state else None

    ports = _ports_of(cfg)
    return {
        "version": VERSION,
        "now": now_str(),
        "process": _process_block(sup),
        "config": {
            "path": st.real_config(),
            "mtime": mtime_str(st.real_config()),
            "sha256": cur_hash[:16],
            "pendingRestart": bool(running and sup.running_hash and sup.running_hash != cur_hash),
            "error": cfg_err,
        },
        "clients": client_counts(ports) if ports else None,
        "ports": [{"port": p, "open": port_open(p)} for p in ports],
        "repos": repos,
        "sync": {
            "lastAll": sync_state.last_all() if sync_state else None,
            "path": st.sync_state_path,
        },
        "providers": providers,
        "replays": replays,
        "cores": cores,
        "paths": {"base": st.base, "log": st.log_path, "tmp": tmp_dir},
    }
