# -*- coding: utf-8 -*-
"""금지/제한 목록(lflist) 스캔 + 해시 계산.

Multirole 은 `HostInfo.banlistHash` 로 방의 금지/제한 목록을 정한다.
그 해시는 EDOPro 와 **같은 알고리즘**으로 파일에서 계산한다:

    0x7DFCEE6A 에서 시작해, 각 카드 줄마다
    hash ^= ((code << 18) | (code >> 14)) ^ ((code << (27+count)) | (code >> (5-count)))

(출처: Multirole `src/Multirole/YGOPro/BanlistParser.hpp` 의 `Detail::Salt`)

`!` 로 시작하는 줄은 새 섹션(목록 이름)의 시작이다. 섹션마다 별도 해시가 생긴다.
파일 예: `sync/banlists/OCG.lflist.conf` → `!2023.10 OCG` + 카드 줄들
"""

import io
import os

BANLIST_HASH_MAGIC = 0x7DFCEE6A
_CACHE = {}          # path -> (mtime, size, [entries])
_DIGITS = "0123456789"


def _salt(h, code, count):
    h ^= (((code << 18) | (code >> 14)) & 0xFFFFFFFF)
    sh = 27 + count
    rh = 5 - count
    h ^= (((code << (sh & 31)) | (code >> (rh & 31))) & 0xFFFFFFFF)
    return h & 0xFFFFFFFF


def parse_sections(path):
    """lflist 파일 → [{section, hash, cards}] (해시가 매직값 그대로인 섹션은 제외)."""
    sections = []
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return sections

    def flush(name, h, cards):
        if h != BANLIST_HASH_MAGIC and cards:
            sections.append({"section": name or os.path.basename(path),
                             "hash": h, "cards": cards})

    name = ""
    h = BANLIST_HASH_MAGIC
    cards = 0
    for line in lines:
        if not line:
            continue
        if line[0] == "!":
            flush(name, h, cards)
            name = line[1:].strip()
            h = BANLIST_HASH_MAGIC
            cards = 0
            continue
        if line[0] not in _DIGITS:
            continue
        sep = line.find(" ")
        if sep <= 0:
            continue
        try:
            code = int(line[:sep])
        except ValueError:
            continue
        start = sep
        while start < len(line) and line[start] not in "-0123456789":
            start += 1
        end = start
        while end < len(line) and line[end] in "-0123456789":
            end += 1
        try:
            count = int(line[start:end])
        except ValueError:
            continue
        if code == 0:
            continue
        h = _salt(h, code, count)
        cards += 1
    flush(name, h, cards)
    return sections


def candidate_dirs(st):
    dirs = []
    env = (os.environ.get("MR_BANLIST_DIR") or "").strip()
    if env:
        dirs.append(env)
    base = getattr(st, "base", "/multirole")
    dirs.append(os.path.join(base, "sync", "banlists"))
    repos = os.path.join(base, "repositories")
    try:
        names = sorted(os.listdir(repos))
    except OSError:
        names = []
    for name in names:
        root = os.path.join(repos, name)
        # EDOPro 는 `repositories/<repo>/lflist.conf` 또는 `.../lflists/` 를 읽는다(game.cpp:2760)
        if os.path.isdir(root):
            dirs.append(root)
        for sub in ("lflists", "LFLists", "banlists"):
            p = os.path.join(root, sub)
            if os.path.isdir(p):
                dirs.append(p)
    return dirs


def scan(st):
    """파일 목록 + 섹션/해시. (mtime,size) 로 캐시."""
    entries = []
    for folder in candidate_dirs(st):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            if not name.lower().endswith((".conf", ".lflist")):
                continue
            path = os.path.join(folder, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            key = (stat.st_mtime, stat.st_size)
            hit = _CACHE.get(path)
            if hit and hit[0] == key:
                sections = hit[1]
            else:
                sections = parse_sections(path)
                _CACHE[path] = (key, sections)
            for sec in sections:
                entries.append({
                    "file": name,
                    "path": path,
                    "section": sec["section"],
                    "hash": sec["hash"],
                    "cards": sec["cards"],
                    "selector": selector_of(name, sec["section"]),
                })
    return entries


def selector_of(file_name, section):
    return "%s|%s" % (file_name, section)


def split_selector(text):
    if not text:
        return "", ""
    file_name, _, section = text.partition("|")
    return file_name.strip(), section.strip()


def resolve(st, text):
    """선택자('파일|섹션' 또는 섹션 이름 또는 파일 이름) → 해시. 못 찾으면 0."""
    if not text:
        return 0
    text = str(text).strip()
    if text.isdigit():
        return int(text)
    file_name, section = split_selector(text)
    entries = scan(st)
    if file_name:
        for e in entries:
            if e["file"].lower() == file_name.lower() and e["section"].lower() == section.lower():
                return e["hash"]
        # 섹션 이름이 없거나 바뀐 경우 파일의 첫 섹션
        for e in entries:
            if e["file"].lower() == file_name.lower():
                return e["hash"]
        return 0
    for e in entries:
        if e["section"].lower() == text.lower() or e["file"].lower() == text.lower():
            return e["hash"]
    # 부분 일치(예: n=2026.10) — 섹션/파일 이름에 포함되면 그 금제
    low = text.lower()
    for e in entries:
        if low in e["section"].lower() or low in e["file"].lower():
            return e["hash"]
    return 0


def label(entry):
    return "%s — %s" % (entry["section"], entry["file"])
