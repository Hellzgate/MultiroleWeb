# -*- coding: utf-8 -*-
"""config.json 스키마 · 검증 · 키 설명.

검증 기준은 Multirole `Instance.cpp` 의 `.at()` 접근을 그대로 옮긴 것이다.
키가 없거나 타입이 틀리면 **서버가 기동에 실패**하므로, 저장 단계에서 막는다.
"""

import re

TOP_LEVEL = {
    "concurrencyHint": int,
    "lobbyListingPort": int,
    "lobbyMaxConnections": int,
    "roomHostingPort": int,
    "repos": list,
    "banlistProvider": dict,
    "coreProvider": dict,
    "dataProvider": dict,
    "logHandler": dict,
    "replayManager": dict,
    "scriptProvider": dict,
}

SINK_TYPES = ("stdout", "stderr", "file", "discordWebhook", "null")
CORE_TYPES = ("shared", "hornet")

PROVIDERS = ("banlistProvider", "coreProvider", "dataProvider", "scriptProvider")

KEY_DOCS = {
    "concurrencyHint": "워커 스레드 수. -1 = 자동(논리 코어 x2). 방 3~5개면 4~8 권장.",
    "lobbyListingPort": "로비(방 목록) TCP 포트. 클라이언트가 이 포트로 방 목록을 본다.",
    "lobbyMaxConnections": "로비 동시 접속 상한.",
    "roomHostingPort": "룸 호스팅 TCP 포트. 플레이어가 실제로 접속하는 포트.",
    "repos": "자동 갱신할 git 저장소. name 은 아래 provider 의 observedRepos 값과 일치해야 한다.",
    "name": "리포 식별자 (scripts / databases / banlists / bin).",
    "remote": "git 원격 URL. 이 리포의 코드/데이터가 그대로 실행된다(신뢰 경계).",
    "path": "로컬 체크아웃 경로(컨테이너 기준 상대/절대).",
    "webhookPort": "이 리포 전용 웹훅 포트. 외부에 열 필요 없음(웹 UI 가 내부 호출).",
    "webhookToken": "웹훅 인증 토큰. 기본값 '<change_this>' 는 반드시 교체.",
    "coreProvider": "ocgcore 로딩 방식. fileRegex 로 코어 파일을 고른다.",
    "fileRegex": "정규식. 리눅스는 '\\.so' (libocgcore.so), Windows 만 '.dll'.",
    "tmpPath": "코어 사본을 두는 경로(loadPerRoom=true 일 때).",
    "coreType": "shared = 서버 프로세스에 직접 로드, hornet = 방마다 자식 프로세스(안전).",
    "loadPerRoom": "true 면 방마다 코어 사본을 만들어 격리한다.",
    "observedRepos": "이 provider 가 감시할 리포 이름들.",
    "dataProvider": "카드 DB(cdb) 공급자.",
    "scriptProvider": "Lua 카드 스크립트 공급자.",
    "banlistProvider": "금제(lflist.conf) 공급자.",
    "logHandler": "로그 출력 설정(서비스별 sink, 코어 오류 sink, 방 채팅 로그).",
    "serviceSinks": "서비스 로그를 어디로 보낼지 서비스별로 지정.",
    "ecSinks": "코어(ocgcore) 오류 출력을 어디로 보낼지 지정.",
    "type": "stdout / stderr / file / discordWebhook / null.",
    "properties": "sink 별 속성. file 은 {\"path\": \"...\"}, discordWebhook 은 {\"url\": \"...\"}.",
    "roomLogging": "방 채팅 로그 저장 여부와 경로.",
    "enabled": "켜기/끄기.",
    "replayManager": "리플레이(.yrpX) 저장 설정.",
    "save": "리플레이 저장 여부.",
}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _validate_providers(cfg, errors, warnings):
    for name in PROVIDERS:
        p = cfg.get(name)
        if not isinstance(p, dict):
            continue
        if "observedRepos" not in p or not isinstance(p["observedRepos"], list):
            errors.append("%s.observedRepos 는 배열이어야 합니다." % name)
        if not isinstance(p.get("fileRegex"), str):
            errors.append("%s.fileRegex 는 문자열이어야 합니다." % name)
        else:
            try:
                re.compile(p["fileRegex"])
            except re.error as exc:
                errors.append("%s.fileRegex 정규식 오류: %s" % (name, exc))


def _validate_core(cfg, errors):
    core = cfg.get("coreProvider") or {}
    if not isinstance(core, dict):
        return
    if not isinstance(core.get("tmpPath"), str):
        errors.append("coreProvider.tmpPath 는 문자열이어야 합니다.")
    if core.get("coreType") not in CORE_TYPES:
        errors.append("coreProvider.coreType 는 shared 또는 hornet 이어야 합니다.")
    if not isinstance(core.get("loadPerRoom"), bool):
        errors.append("coreProvider.loadPerRoom 은 true/false 여야 합니다.")


def _validate_log_handler(cfg, errors):
    lh = cfg.get("logHandler") or {}
    if not isinstance(lh, dict):
        return
    for group in ("serviceSinks", "ecSinks"):
        sinks = lh.get(group)
        if not isinstance(sinks, dict):
            errors.append("logHandler.%s 는 객체여야 합니다." % group)
            continue
        for sname, sink in sinks.items():
            if not isinstance(sink, dict):
                errors.append("logHandler.%s.%s 는 객체여야 합니다." % (group, sname))
                continue
            if sink.get("type") not in SINK_TYPES:
                errors.append(
                    "logHandler.%s.%s.type 은 %s 중 하나여야 합니다."
                    % (group, sname, "/".join(SINK_TYPES))
                )
            if not isinstance(sink.get("properties"), dict):
                errors.append("logHandler.%s.%s.properties 는 객체여야 합니다." % (group, sname))
            elif sink.get("type") == "file" and not sink.get("properties", {}).get("path"):
                errors.append("logHandler.%s.%s 는 file sink 인데 properties.path 가 없습니다." % (group, sname))
    rl = lh.get("roomLogging")
    if not isinstance(rl, dict):
        errors.append("logHandler.roomLogging 는 객체여야 합니다.")
    else:
        if not isinstance(rl.get("enabled"), bool):
            errors.append("logHandler.roomLogging.enabled 는 true/false 여야 합니다.")
        if not isinstance(rl.get("path"), str):
            errors.append("logHandler.roomLogging.path 는 문자열이어야 합니다.")


def _validate_replay(cfg, errors):
    rm = cfg.get("replayManager") or {}
    if not isinstance(rm, dict):
        return
    if not isinstance(rm.get("save"), bool):
        errors.append("replayManager.save 는 true/false 여야 합니다.")
    if not isinstance(rm.get("path"), str):
        errors.append("replayManager.path 는 문자열이어야 합니다.")


def _validate_repos(cfg, errors, warnings):
    repos = cfg.get("repos")
    if not isinstance(repos, list):
        return
    seen_names, seen_ports = set(), set()
    for i, r in enumerate(repos):
        tag = "repos[%d]" % i
        if not isinstance(r, dict):
            errors.append("%s 는 객체여야 합니다." % tag)
            continue
        for key in ("name", "remote", "path", "webhookToken"):
            if not isinstance(r.get(key), str) or not r.get(key):
                errors.append("%s.%s 는 비어있지 않은 문자열이어야 합니다." % (tag, key))
        if not is_int(r.get("webhookPort")) or not (1 <= r.get("webhookPort", 0) <= 65535):
            errors.append("%s.webhookPort 는 1~65535 정수여야 합니다." % tag)
        nm = r.get("name")
        if isinstance(nm, str):
            if nm in seen_names:
                errors.append("리포 이름 중복: %s" % nm)
            seen_names.add(nm)
        wp = r.get("webhookPort")
        if is_int(wp):
            if wp in seen_ports:
                errors.append("웹훅 포트 중복: %d" % wp)
            seen_ports.add(wp)
            if wp in (cfg.get("lobbyListingPort"), cfg.get("roomHostingPort")):
                errors.append("웹훅 포트 %d 가 로비/룸 포트와 겹칩니다." % wp)
        if r.get("webhookToken") == "<change_this>":
            warnings.append("repos[%d].webhookToken 이 기본값 <change_this> 입니다 — 교체 권장." % i)


def _validate_cross(cfg, errors, warnings):
    repos = cfg.get("repos")
    if isinstance(repos, list):
        names = set(r.get("name") for r in repos if isinstance(r, dict))
        for name in PROVIDERS:
            p = cfg.get(name)
            if isinstance(p, dict) and isinstance(p.get("observedRepos"), list):
                for obs in p["observedRepos"]:
                    if obs not in names:
                        warnings.append("%s.observedRepos 의 '%s' 리포가 정의되어 있지 않습니다." % (name, obs))

    if cfg.get("lobbyListingPort") == cfg.get("roomHostingPort"):
        errors.append("lobbyListingPort 와 roomHostingPort 가 같습니다.")

    ch = cfg.get("concurrencyHint")
    if is_int(ch):
        if ch == 0:
            warnings.append("concurrencyHint=0 은 자동(코어x2)으로 해석됩니다.")
        elif ch > 64:
            warnings.append("concurrencyHint=%d 는 과도할 수 있습니다(NAS CPU 확인)." % ch)


def validate(cfg):
    """(errors, warnings) 를 돌려준다. errors 가 있으면 저장/재시작 금지."""
    errors = []
    warnings = []

    if not isinstance(cfg, dict):
        return ["최상위가 JSON 객체가 아닙니다."], []

    for key, typ in TOP_LEVEL.items():
        if key not in cfg:
            errors.append("필수 키 누락: %s" % key)
        elif typ is int and not is_int(cfg[key]):
            errors.append("%s 는 정수여야 합니다." % key)
        elif typ is list and not isinstance(cfg[key], list):
            errors.append("%s 는 배열이어야 합니다." % key)
        elif typ is dict and not isinstance(cfg[key], dict):
            errors.append("%s 는 객체여야 합니다." % key)

    for key in ("lobbyListingPort", "roomHostingPort", "lobbyMaxConnections"):
        if is_int(cfg.get(key)):
            if key != "lobbyMaxConnections" and not (1 <= cfg[key] <= 65535):
                errors.append("%s 는 1~65535 범위여야 합니다." % key)
            if key == "lobbyMaxConnections" and cfg[key] < 1:
                errors.append("lobbyMaxConnections 는 1 이상이어야 합니다.")

    _validate_providers(cfg, errors, warnings)
    _validate_core(cfg, errors)
    _validate_log_handler(cfg, errors)
    _validate_replay(cfg, errors)
    _validate_repos(cfg, errors, warnings)
    _validate_cross(cfg, errors, warnings)

    return errors, warnings
