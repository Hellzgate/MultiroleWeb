# 데모/스크린샷용 가짜 multirole (실제 게임 아님 — UI 확인용)
import sys, time, random

print("[demo] Multirole v1.1.0 (fake) starting", flush=True)
print("[demo] repos: 4", flush=True)
time.sleep(0.4)
print("[git] scripts: already up to date", flush=True)
print("[demo] lobby listening on :7922", flush=True)
print("[demo] room hosting listening on :7911", flush=True)
print("[demo] coreType=hornet tmpPath=./tmp/", flush=True)
i = 0
while True:
    i += 1
    time.sleep(3)
    if i % 3 == 0:
        print("[info] room 1: duel started (2 players)", flush=True)
    elif i % 3 == 1:
        print("[info] script provider: 12043 scripts loaded", flush=True)
    else:
        print("[warn] sample warning line for the log viewer", flush=True)
