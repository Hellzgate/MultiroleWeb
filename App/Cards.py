# -*- coding: utf-8 -*-
"""cdb(카드 DB) 조회 + **저장소 갱신 후 카드 반영 여부 확인**.

용도: `databases` 리포를 갱신한 뒤 "이 카드가 실제로 cdb 에 들어왔나 / 값이 바뀌었나" 를 확인한다.

  - 검색: `/api/cards?q=` — 카드 ID · 이름 · 효과 텍스트
    결과에 **출처 cdb 파일 + 그 파일의 mtime** 을 함께 준다(= 언제 갱신됐는지)
  - 상세: `/api/cards/<id>` — datas + texts(str1~16)
  - 변경 감지: 스냅샷(기준) 대비 추가/변경/삭제. `/api/sync` 성공 후 **자동**으로 스냅샷을 갱신한다.
      `POST /api/cards/snapshot` 으로 수동 갱신도 가능.
"""

import glob
import hashlib
import io
import json
import os
import sqlite3
import threading
import time

ATTR = {0x01: "땅", 0x02: "물", 0x04: "화염", 0x08: "바람", 0x10: "빛", 0x20: "어둠", 0x40: "신"}
RACE = {
    0x1: "전사족", 0x2: "마법사족", 0x4: "천사족", 0x8: "악마족", 0x10: "번개족", 0x20: "드래곤족",
    0x40: "야수족", 0x80: "야수전사족", 0x100: "언데드족", 0x200: "기계족", 0x400: "물족",
    0x800: "파충류족", 0x1000: "사이킥족", 0x2000: "암석족", 0x4000: "곤충족", 0x8000: "공룡족",
    0x10000: "어류족", 0x20000: "해룡족", 0x40000: "창조신족", 0x80000: "환상수족",
    0x100000: "사이버스족", 0x200000: "환룡족", 0x400000: "사이킥족(구)", 0x800000: "신족",
    0x8000000: "환상마족",
}
SUBTYPE = [
    (0x800000, "엑시즈"), (0x4000000, "링크"), (0x2000, "싱크로"), (0x40, "융합"), (0x80, "의식"),
    (0x1000000, "펜듈럼"), (0x1000, "튜너"), (0x20, "효과"), (0x10, "일반"), (0x4000, "토큰"),
]


def kind_text(ctype):
    if ctype is None:
        return "?"
    if ctype & 0x2:
        base = "함정" if ctype & 0x4 else "마법"
        if ctype & 0x10000:
            base += "·속공"
        if ctype & 0x20000:
            base += "·지속"
        if ctype & 0x40000:
            base += "·장비"
        if ctype & 0x80000:
            base += "·필드"
        if ctype & 0x100000:
            base += "·의식"
        if ctype & 0x200000:
            base += "·카운터"
        return base
    if ctype & 0x1:
        tags = [name for bit, name in SUBTYPE if ctype & bit]
        return "몬스터" + (("·" + "·".join(tags)) if tags else "")
    return "?"


def _desc_hash(text):
    return hashlib.sha1((text or "").encode("utf-8", "replace")).hexdigest()[:12]


class CardIndex(object):
    def __init__(self, st):
        self.st = st
        base = getattr(st, "base", "/multirole")
        self.dir = os.environ.get("MR_CDB_DIR") or os.path.join(base, "sync", "databases")
        persist = os.path.dirname(getattr(st, "auth_path", "") or ".") or "."
        self.cache_dir = os.environ.get("MR_CARD_CACHE_DIR") or os.path.join(persist, "_cache")
        self.snap_path = os.path.join(self.cache_dir, "cdb-snapshot.json")
        self.diff_path = os.path.join(self.cache_dir, "cdb-changes.json")
        self._lock = threading.Lock()
        self._cards = {}
        self._meta = []
        self._loaded_at = 0.0
        self._stamp = None

    # -- 파일 -------------------------------------------------------------- #
    def files(self):
        out = []
        for full in sorted(glob.glob(os.path.join(self.dir, "*.cdb"))):
            try:
                stt = os.stat(full)
            except OSError:
                continue
            out.append({"name": os.path.basename(full), "bytes": stt.st_size,
                        "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stt.st_mtime))})
        return out

    def _stamp_now(self):
        parts = []
        for full in sorted(glob.glob(os.path.join(self.dir, "*.cdb"))):
            try:
                stt = os.stat(full)
            except OSError:
                continue
            parts.append("%s:%d:%d" % (os.path.basename(full), stt.st_size, int(stt.st_mtime)))
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()

    # -- 로드 -------------------------------------------------------------- #
    def _read_cdb(self, path):
        rows = {}
        try:
            con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
        except sqlite3.Error:
            return rows
        try:
            datas = {}
            for row in con.execute("select id,ot,alias,setcode,type,atk,def,level,race,attribute from datas"):
                datas[row[0]] = row
            for row in con.execute("select id,name,desc,str1,str2,str3,str4,str5 from texts"):
                d = datas.get(row[0])
                if not d:
                    continue
                rows[row[0]] = {
                    "id": d[0], "ot": d[1], "alias": d[2], "setcode": d[3], "type": d[4],
                    "atk": d[5], "def": d[6], "level": d[7], "race": d[8], "attribute": d[9],
                    "name": row[1] or "", "desc": row[2] or "",
                    "str1": row[3] or "", "str2": row[4] or "", "str3": row[5] or "",
                    "str4": row[6] or "", "str5": row[7] or "",
                }
        except sqlite3.Error:
            pass
        finally:
            try:
                con.close()
            except sqlite3.Error:
                pass
        return rows

    def ensure(self, force=False):
        stamp = self._stamp_now()
        with self._lock:
            if not force and self._cards and stamp == self._stamp:
                return self._cards
            cards = {}
            for full in sorted(glob.glob(os.path.join(self.dir, "*.cdb"))):
                name = os.path.basename(full)
                rows = self._read_cdb(full)
                for cid, rec in rows.items():
                    rec["src"] = name
                    cards[cid] = rec            # 뒤 파일이 덮어씀(unofficial/커스텀 우선)
            self._cards = cards
            self._stamp = stamp
            self._loaded_at = time.time()
            return cards

    # -- 검색 -------------------------------------------------------------- #
    def search(self, q="", limit=50):
        cards = self.ensure()
        q = (q or "").strip()
        out = []
        ql = q.lower()
        if not q:
            # 빈 검색: 최근 파일 기준 상위 ID 몇 개
            ids = sorted(cards)[:limit]
            return [self._slim(cards[i]) for i in ids]
        exact = []
        prefix = []
        contains = []
        by_id = []
        for cid, rec in cards.items():
            name = rec["name"] or ""
            nl = name.lower()
            s_id = str(cid)
            if s_id == q:
                by_id.append(rec)
            elif nl == ql:
                exact.append(rec)
            elif nl.startswith(ql):
                prefix.append(rec)
            elif ql in nl or ql in s_id:
                contains.append(rec)
            elif ql in (rec["desc"] or "").lower():
                contains.append(rec)
            if len(by_id) + len(exact) + len(prefix) + len(contains) > 4000:
                break
        for group in (by_id, exact, prefix, contains):
            for rec in group:
                if len(out) >= limit:
                    return out
                out.append(self._slim(rec))
        return out

    def get(self, cid):
        cards = self.ensure()
        rec = cards.get(int(cid))
        if not rec:
            return None
        out = dict(rec)
        out["kind"] = kind_text(rec.get("type"))
        out["attr"] = ATTR.get(rec.get("attribute"), "")
        out["race"] = RACE.get(rec.get("race"), "")
        f = self._file_info(rec.get("src"))
        out["cdb"] = f
        return out

    def _file_info(self, name):
        if not name:
            return None
        full = os.path.join(self.dir, name)
        try:
            stt = os.stat(full)
        except OSError:
            return {"name": name}
        return {"name": name, "bytes": stt.st_size,
                "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stt.st_mtime))}

    def _slim(self, rec):
        return {"id": rec["id"], "name": rec["name"], "type": rec["type"],
                "kind": kind_text(rec.get("type")), "atk": rec["atk"], "def": rec["def"],
                "level": rec["level"], "src": rec.get("src"),
                "mtime": (self._file_info(rec.get("src")) or {}).get("mtime"),
                "desc": (rec.get("desc") or "")[:120]}

    # -- 스냅샷 / 변경 ------------------------------------------------------ #
    def _current_state(self):
        cards = self.ensure(force=True)
        state = {}
        for cid, rec in cards.items():
            state[str(cid)] = [rec["name"], rec["type"], rec["atk"], rec["def"], rec["level"],
                               _desc_hash(rec.get("desc"))]
        return state

    def snapshot(self, why="manual"):
        """현재 상태를 기준으로 저장하고, 직전 스냅샷과 비교한 결과를 남긴다."""
        now = self._current_state()
        prev = {}
        try:
            with io.open(self.snap_path, "r", encoding="utf-8") as f:
                prev = (json.load(f) or {}).get("cards") or {}
        except (OSError, ValueError):
            prev = {}

        added, changed, removed = [], [], []
        if prev:
            for cid, cur in now.items():
                old = prev.get(cid)
                if old is None:
                    added.append(cid)
                elif old != cur:
                    fields = []
                    for i, label in enumerate(("이름", "타입", "ATK", "DEF", "레벨", "설명")):
                        if (old[i] if i < len(old) else None) != cur[i]:
                            fields.append(label)
                    changed.append({"id": int(cid), "name": cur[0], "fields": fields})
            for cid in prev:
                if cid not in now:
                    removed.append(int(cid))

        name_of = {}
        cards = self.ensure()
        for cid in added:
            name_of[cid] = (cards.get(int(cid)) or {}).get("name", "")

        result = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "why": why,
            "first": not bool(prev),
            "counts": {"added": len(added), "changed": len(changed), "removed": len(removed),
                       "total": len(now)},
            "added": [{"id": int(c), "name": name_of.get(c, "")} for c in added[:100]],
            "changed": changed[:100],
            "removed": removed[:100],
            "files": self.files(),
        }
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            tmp = self.snap_path + ".tmp"
            with io.open(tmp, "w", encoding="utf-8") as f:
                json.dump({"at": result["at"], "why": why, "cards": now}, f, ensure_ascii=False)
            os.replace(tmp, self.snap_path)
            tmp2 = self.diff_path + ".tmp"
            with io.open(tmp2, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
            os.replace(tmp2, self.diff_path)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "result": result}

    def changes(self):
        out = {"counts": None, "at": None, "files": self.files(), "loaded": len(self._cards)}
        try:
            with io.open(self.diff_path, "r", encoding="utf-8") as f:
                out.update(json.load(f) or {})
        except (OSError, ValueError):
            pass
        return out
