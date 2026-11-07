# -*- coding: utf-8 -*-
"""저장소(git) 갱신 + 결과 요약.

갱신 방법
    각 리포의 `webhookPort` 로 POST(`token=...`) → multirole `GitRepo::Callback` 이
    `git fetch` + `git reset --hard FETCH_HEAD` 를 **동기로** 수행한 뒤 응답한다.
    (Endpoint/Webhook.cpp: `Callback(...)` 다음에 `DoWrite()` — 즉 응답을 받으면 이미 반영됨)

무엇이 바뀌었는지
    · 이전 HEAD → 새 HEAD (**전/후 해시 비교**, 같으면 "변경 없음")
    · git CLI 가 있으면 **커밋 목록**(`git log old..new`)과 **파일 목록**(`git diff --name-status`)
    · git 이 없으면 파일 mtime 으로 추정(`files_by_mtime`)

실패 로그
    multirole 자식의 로그(`[Service:GitRepository] [Level:Error] ...`)를 갱신 전 오프셋부터
    읽어 그 구간의 줄을 결과에 담는다. (웹훅은 오류여도 200 을 돌려주기 때문에 로그로 판정)
"""

import io
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

GIT_LOG_SERVICE = "Service:GitRepository"


# --------------------------------------------------------------------------- #
# git 읽기 (CLI 없이도 HEAD 는 읽는다)
# --------------------------------------------------------------------------- #
def read_head(repo_path):
    """`.git/HEAD` 를 해석해 전체 40자 커밋 해시를 돌려준다(없으면 None)."""
    git_dir = os.path.join(repo_path, ".git")
    if os.path.isfile(git_dir):                       # worktree: "gitdir: <path>"
        try:
            with io.open(git_dir, "r", encoding="utf-8", errors="replace") as f:
                line = f.read().strip()
            if line.startswith("gitdir:"):
                git_dir = os.path.normpath(os.path.join(repo_path, line[7:].strip()))
        except OSError:
            return None
    head_file = os.path.join(git_dir, "HEAD")
    try:
        with io.open(head_file, "r", encoding="utf-8", errors="replace") as f:
            head = f.read().strip()
    except OSError:
        return None
    if not head:
        return None
    if head.startswith("ref:"):
        ref = head[4:].strip()
        try:
            with io.open(os.path.join(git_dir, ref), "r", encoding="utf-8") as f:
                value = f.read().strip()
            if len(value) >= 7:
                return value
        except OSError:
            pass
        # packed-refs (clone 직후에는 refs 가 여기에만 있다)
        try:
            with io.open(os.path.join(git_dir, "packed-refs"), "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("^"):
                        continue
                    parts = line.split(None, 1)
                    if len(parts) == 2 and parts[1] == ref:
                        return parts[0]
        except OSError:
            return None
        return None
    return head if len(head) >= 7 else None


def git_available():
    try:
        return subprocess.call(["git", "--version"], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL) == 0
    except (OSError, ValueError):
        return False


def _git(repo_path, *args, **kwargs):
    """git -C <path> ... 실행 → (exit, stdout)."""
    timeout = kwargs.get("timeout", 20)
    cmd = ["git", "-C", repo_path, "-c", "safe.directory=*", "-c", "core.quotepath=false",
           "--no-pager"] + list(args)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (OSError, ValueError):
        return 127, ""
    try:
        out, _err = proc.communicate(timeout=timeout)
    except Exception:                                  # noqa: BLE001 - timeout 등
        try:
            proc.kill()
        except OSError:
            pass
        return 124, ""
    return proc.returncode, (out or b"").decode("utf-8", "replace")


def commits_between(repo_path, old, new, limit=20):
    """`old..new` 커밋 목록 [{hash, subject}] + 전체 개수."""
    if not old or not new or old == new:
        return [], 0
    code, out = _git(repo_path, "log", "--no-decorate", "--pretty=format:%h%x09%s",
                     "%s..%s" % (old, new), "-n", str(limit))
    if code != 0:
        return [], 0
    items = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        items.append({"hash": parts[0].strip(), "subject": parts[1].strip() if len(parts) > 1 else ""})
    code2, out2 = _git(repo_path, "rev-list", "--count", "%s..%s" % (old, new))
    total = 0
    if code2 == 0:
        try:
            total = int(out2.strip() or "0")
        except ValueError:
            total = len(items)
    return items, total or len(items)


def files_between(repo_path, old, new, limit=40):
    """`git diff --name-status old new` → [{status, path}] + 전체 개수."""
    if not old or not new or old == new:
        return [], 0
    code, out = _git(repo_path, "diff", "--name-status", old, new, timeout=40)
    if code != 0:
        return [], 0
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0][:1] or "?"
        path = parts[-1]
        rows.append({"status": status, "path": path})
    return rows[:limit], len(rows)


def files_by_mtime(repo_path, since_ts, limit=40, cap=200000):
    """git 이 없을 때의 추정: `since_ts` 이후 수정된 파일(변경/추가)."""
    rows = []
    total = 0
    threshold = since_ts - 1.0
    scanned = 0
    for root, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            scanned += 1
            if scanned > cap:
                break
            full = os.path.join(root, fn)
            try:
                if os.path.getmtime(full) < threshold:
                    continue
            except OSError:
                continue
            total += 1
            if len(rows) < limit:
                rows.append({"status": "M", "path": os.path.relpath(full, repo_path)})
    return rows, total


# --------------------------------------------------------------------------- #
# 갱신 결과 저장 (sync.json)
# --------------------------------------------------------------------------- #
class SyncState(object):
    """리포별 '마지막 갱신 결과' 를 남긴다(패널이 재시작해도 유지)."""

    VERSION = 1
    HISTORY_MAX = 30

    def __init__(self, path):
        self.path = path
        self.data = {"version": self.VERSION, "repos": {}, "history": []}
        self.load()

    def load(self):
        try:
            with io.open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return self.data
        if isinstance(data, dict):
            repos = data.get("repos")
            history = data.get("history")
            self.data = {
                "version": self.VERSION,
                "repos": repos if isinstance(repos, dict) else {},
                "history": history if isinstance(history, list) else [],
            }
        return self.data

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with io.open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def get(self, name):
        return (self.data.get("repos") or {}).get(name)

    def last_all(self):
        history = self.data.get("history") or []
        return history[-1] if history else None

    def set(self, result):
        name = result.get("name") or "?"
        self.data.setdefault("repos", {})[name] = result

    def add_history(self, entry):
        history = self.data.setdefault("history", [])
        history.append(entry)
        del history[:-self.HISTORY_MAX]


# --------------------------------------------------------------------------- #
# 갱신 실행
# --------------------------------------------------------------------------- #
def _read_log_since(path, offset, max_bytes=65536):
    """로그 파일의 `offset` 이후 구간을 줄 단위로 (오프셋은 파일이 줄면 0 으로 재시작)."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    if size < offset:                                  # 회전(잘림) → 처음부터
        offset = 0
    if size - offset > max_bytes:
        offset = size - max_bytes
    try:
        with io.open(path, "rb") as f:
            f.seek(offset)
            raw = f.read()
    except OSError:
        return []
    return raw.decode("utf-8", "replace").splitlines()


def _log_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def git_log_lines(lines, limit=12):
    """자식 로그에서 git repo 관련 줄만 추려 메시지 부분만 남긴다."""
    picked = []
    for line in lines:
        if GIT_LOG_SERVICE not in line:
            continue
        if "[Level:Debug]" in line:
            continue
        msg = line.split("] ")[-1].strip() if "]" in line else line.strip()
        msg = _TS_RE.split(msg)[0].strip()          # 자식이 개행 없이 이어 쓴 경우 정리
        if not msg:
            continue
        picked.append({"error": "[Level:Error]" in line, "text": msg})
        if len(picked) >= limit:
            break
    return picked


def sync_one(st, repo, log=None):
    """리포 하나 갱신 + 결과 dict. (예외를 던지지 않는다)"""
    name = (repo or {}).get("name") or "?"
    path = st.rel((repo or {}).get("path"))
    started = time.time()
    result = {
        "name": name,
        "ts": started,
        "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
        "ok": False,
        "changed": False,
        "head": None,
        "from": None,
        "to": None,
        "commitCount": 0,
        "commits": [],
        "fileCount": 0,
        "files": [],
        "durationMs": 0,
        "error": None,
        "log": [],
    }

    if not os.path.isdir(path):
        result["error"] = "경로가 없습니다: %s" % path
        result["durationMs"] = int((time.time() - started) * 1000)
        return result

    port = repo.get("webhookPort")
    token = repo.get("webhookToken") or ""
    before = read_head(path)

    # multirole 은 웹훅의 **첫 256바이트**에서 토큰을 찾는다. 본문만 보내면 헤더/본문이
    # 다른 TCP 세그먼트로 갈 때 토큰을 놓치는 경합이 실측되어(간헐적 "does not have a token"),
    # 토큰을 **URL 경로**에도 넣어 첫 줄에 반드시 포함시킨다.
    url = "http://127.0.0.1:%d/%s" % (int(port), urllib.parse.quote(token, safe=""))
    body = ("token=%s" % token).encode("utf-8")
    lines_all = []
    token_error = False
    for attempt in range(2):
        log_offset = _log_size(st.log_path) if log is not None else 0
        try:
            req = urllib.request.Request(url, data=body, method="POST")
            with urllib.request.urlopen(req, timeout=180) as resp:
                resp.read()
        except Exception as exc:                        # noqa: BLE001
            result["error"] = "웹훅 연결 실패 (포트 %s) — %s" % (port, exc)
            result["durationMs"] = int((time.time() - started) * 1000)
            return result
        if log is None:
            break
        try:
            lines = git_log_lines(_read_log_since(st.log_path, log_offset))
        except Exception:                               # noqa: BLE001
            lines = []
        lines_all.extend(lines)
        token_error = any("does not have a token" in x["text"] for x in lines)
        if token_error and attempt == 0:
            time.sleep(0.4)                             # 첫 읽기 경합 → 한 번만 재시도
            continue
        break

    after = read_head(path)
    result["from"] = before[:12] if before else None
    result["to"] = after[:12] if after else None
    result["head"] = after[:12] if after else None
    result["changed"] = bool(before and after and before != after)

    # 자식 로그(갱신 구간) — 웹훅은 오류여도 200 이므로 여기서 판정한다
    if log is not None:
        result["log"] = lines_all[:12]
        errors = [x for x in result["log"] if x.get("error")]
        if errors:
            result["error"] = errors[0]["text"]

    if result["changed"] and before and after:
        if git_available():
            commits, total = commits_between(path, before, after)
            files, file_total = files_between(path, before, after)
            result["commits"] = commits
            result["commitCount"] = total
            result["files"] = files
            result["fileCount"] = file_total
        else:
            files, file_total = files_by_mtime(path, started)
            result["files"] = files
            result["fileCount"] = file_total
            result["commitCount"] = 0
    elif result["changed"] and not before:
        files, file_total = files_by_mtime(path, started)
        result["files"] = files
        result["fileCount"] = file_total

    result["ok"] = result["error"] is None
    result["durationMs"] = int((time.time() - started) * 1000)

    if log is not None:
        if result["error"]:
            log("sync '%s' FAILED: %s" % (name, result["error"]))
        elif result["changed"]:
            log("sync '%s' updated %s -> %s (+%d commits, %d files) in %dms"
                % (name, result["from"], result["to"], result["commitCount"],
                   result["fileCount"], result["durationMs"]))
        else:
            log("sync '%s' up to date (%s) in %dms"
                % (name, result["head"], result["durationMs"]))
    return result


def sync_all(st, cfg, state, log=None, name=None):
    """`name` 이 있으면 그 리포만, 없으면 **모든 리포**를 순서대로 갱신."""
    started = time.time()
    repos = [r for r in (cfg.get("repos") or []) if isinstance(r, dict)]
    if name:
        repos = [r for r in repos if r.get("name") == name]
        if not repos:
            return None

    results = []
    for repo in repos:
        res = sync_one(st, repo, log)
        state.set(res)
        results.append(res)
        if log is not None:
            log("sync result '%s': ok=%s changed=%s %s"
                % (res["name"], res["ok"], res["changed"], res["error"] or ""))

    changed = [r for r in results if r["changed"]]
    failed = [r for r in results if not r["ok"]]
    summary = {
        "total": len(results),
        "changed": len(changed),
        "failed": len(failed),
        "durationMs": int((time.time() - started) * 1000),
        "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
    }
    if not name:
        state.add_history({"at": summary["at"], "ts": started, "total": summary["total"],
                           "changed": summary["changed"], "failed": summary["failed"],
                           "repos": [{"name": r["name"], "ok": r["ok"], "changed": r["changed"],
                                      "from": r["from"], "to": r["to"],
                                      "commitCount": r["commitCount"],
                                      "fileCount": r["fileCount"],
                                      "error": r["error"]} for r in results]})
    state.save()
    return {"results": results, "summary": summary}
