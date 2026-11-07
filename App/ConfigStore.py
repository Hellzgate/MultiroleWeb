# -*- coding: utf-8 -*-
"""config.json 읽기 / 검증 / 원자적 저장 / 백업.

* 저장 순서: 검증 → `.tmp` 작성 → fsync → 재파싱 검증 → `.bak-<시각>` → os.replace
* `.tmp` 는 **실제 파일과 같은 폴더**(= 바인드 마운트 안)에 만든다.
  단일 파일 바인드 마운트 위에서는 rename() 이 EBUSY 라 이 방식이 필요하다.
"""

import json
import os
import shutil
import time

from .ConfigSchema import validate


class ConfigError(Exception):
    def __init__(self, errors, warnings=None):
        Exception.__init__(self, "; ".join(errors))
        self.errors = errors
        self.warnings = warnings or []


def load_config(st):
    try:
        with open(st.real_config(), "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        raise ConfigError(["config.json 을 읽을 수 없습니다: %s" % exc])
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ConfigError(["config.json 파싱 실패: %s" % exc])


def prune_backups(st, pattern):
    folder = os.path.dirname(st.real_config())
    try:
        items = sorted([f for f in os.listdir(folder) if f.startswith(pattern)])
    except OSError:
        return
    for old in items[: max(0, len(items) - st.backup_keep)]:
        try:
            os.remove(os.path.join(folder, old))
        except OSError:
            pass


def save_config(st, cfg):
    errors, warnings = validate(cfg)
    if errors:
        raise ConfigError(errors, warnings)

    real = st.real_config()
    tmp = real + ".tmp"
    payload = json.dumps(cfg, indent="\t", ensure_ascii=False) + "\n"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
    except OSError as exc:
        raise ConfigError(["임시 파일 작성 실패: %s" % exc])

    # 방어: 활성화 직전에 다시 파싱해 본다
    try:
        with open(tmp, "r", encoding="utf-8") as f:
            json.loads(f.read())
    except (OSError, ValueError) as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise ConfigError(["작성된 JSON 이 유효하지 않습니다: %s" % exc])

    if os.path.exists(real):
        bak = real + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
        try:
            shutil.copy2(real, bak)
            prune_backups(st, "config.json.bak-")
        except OSError:
            pass
    os.replace(tmp, real)
    return warnings
