# -*- coding: utf-8 -*-
"""부작용 없는 시스템 조회 유틸 (파일 해시 · 포트 · 접속 수 · git HEAD · 파일 개수)."""

import hashlib
import os
import re
import socket
import time

# /proc/net/tcp{,6} 한 줄: "sl local rem st ..."
_PORT_RE = re.compile(
    r"^\s*\d+:\s*([0-9A-Fa-f]{8}):([0-9A-Fa-f]{4})\s+([0-9A-Fa-f]{8}):([0-9A-Fa-f]{4})\s+([0-9A-Fa-f]{2})"
)


def now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def mtime_str(path):
    try:
        return time_str(os.path.getmtime(path))
    except OSError:
        return None


def time_str(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except (OSError, ValueError, OverflowError):
        return None


def file_sha256(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.1f %s" % (n, unit)) if unit != "B" else ("%d B" % n)
        n /= 1024.0
    return "?"


def client_counts(ports):
    """ESTABLISHED TCP sessions per local port, from /proc/net/tcp{,6} (Linux only)."""
    out = {}
    files = ["/proc/net/tcp", "/proc/net/tcp6"]
    if not any(os.path.exists(p) for p in files):
        return None
    for port in ports:
        out[str(port)] = 0
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                next(f, None)
                for line in f:
                    m = _PORT_RE.match(line)
                    if not m:
                        continue
                    lport = int(m.group(2), 16)
                    state = m.group(5)
                    if state == "01" and lport in out:
                        out[str(lport)] += 1
        except OSError:
            continue
    return out


def port_open(port, host="127.0.0.1", timeout=0.4):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def git_head(repo_path):
    """git CLI 없이 .git/HEAD(+refs) 를 읽어 짧은 커밋 해시를 구한다."""
    gd = os.path.join(repo_path, ".git")
    if not os.path.isdir(gd):
        return None
    head_file = os.path.join(gd, "HEAD")
    try:
        with open(head_file, "r", encoding="utf-8", errors="replace") as f:
            head = f.read().strip()
    except OSError:
        return None
    if head.startswith("ref:"):
        ref = head[4:].strip()
        candidate = os.path.join(gd, *ref.split("/"))
        if os.path.exists(candidate):
            try:
                with open(candidate, "r", encoding="utf-8", errors="replace") as f:
                    return f.read().strip()[:12]
            except OSError:
                pass
        packed = os.path.join(gd, "packed-refs")
        try:
            with open(packed, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.strip().endswith(ref):
                        return line.split()[0][:12]
        except OSError:
            return None
        return None
    return head[:12]


def count_matching(root, regex, cap=200000):
    """root 아래에서 파일 **이름**이 regex 와 맞는 개수(.git 은 제외)."""
    rx = re.compile(regex)
    total = 0
    if not os.path.isdir(root):
        return 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            if rx.search(fn):
                total += 1
                if total >= cap:
                    return total
    return total
