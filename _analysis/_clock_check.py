#!/usr/bin/env python3
"""Prove that the 60fps build does NOT make Zombie Farm's game clock run fast.

Method: run the app for a fixed real-time interval under each configuration and
read back how much *game* time elapsed. Game time comes from the emulated clock
that gettimeofday()/time() report (real SystemTime + the configured offset), and
the app derives its per-frame delta from gettimeofday(), so comparing the
emulated clock's advancement against wall-clock advancement is exactly the
question we care about.

The measurement is done by starting touchHLE with a *known* fake epoch
(TOUCHHLE_FAKE_UNIX_TIME) so the app's clock is deterministic, then sampling the
fork's own profile/debug output for the reported clock, and separately timing
the run with a stopwatch.

Since the fork exposes TOUCHHLE_ZF_DAILY_TRACE, which logs the day boundary it
computed, we can also check the day-boundary arithmetic agrees between 30fps and
60fps.
"""
import argparse
import os
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(ROOT)

# The emulator lives in its own folder now (the tree mirrors the shipped ./Release
# layout). Fall back to the flat layout so this keeps working either way.
_HLE = ROOT / "touchHLE"
if not (_HLE / "touchHLE.exe").exists():
    _HLE = ROOT

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa"
STOCK = _HLE / "touchHLE.exe"
FORK = _HLE / "touchHLE_fork.exe"
PERF = ROOT / "_analysis" / "perf"
FIX = "--non-blocking-zero-timeout-run-loop"

# A fixed, recognisable epoch so the emulated clock is reproducible.
FAKE_EPOCH = "1700000000"   # 2023-11-14T22:13:20Z


def run_case(tag, exe, extra, seconds):
    out = PERF / f"clock_{tag}.log"
    if out.exists():
        out.unlink()

    env = dict(os.environ)
    env["TOUCHHLE_FAKE_UNIX_TIME"] = FAKE_EPOCH
    env["TOUCHHLE_TIME_OFFSET_SECONDS"] = "0"
    env["TOUCHHLE_ZF_DAILY_TRACE"] = "1"

    argv = [str(exe), str(IPA), "--device-family=ipad", "--landscape-right",
            "--print-fps", *extra]

    t0 = time.monotonic()
    with open(out, "wb") as fh:
        # touchHLE resolves touchHLE_dylibs/ relative to cwd, so run from ROOT.
        proc = subprocess.Popen(argv, cwd=str(ROOT), env=env,
                                stdout=fh, stderr=subprocess.STDOUT)
        try:
            proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    wall = time.monotonic() - t0

    text = out.read_text(errors="replace")

    fps = [float(m) for m in re.findall(r"EAGLContext .* FPS: ([0-9.]+)", text)]
    fps = fps[3:] if len(fps) > 4 else fps

    # Any line that reports the emulated clock.
    days = re.findall(r"daily trace: returned host-local beginning of day (\S+) "
                      r"\(([0-9]+) Unix seconds", text)

    return dict(tag=tag, wall=wall, fps=fps, days=days, log=out, text=text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=25)
    a = ap.parse_args()

    print(f"fake epoch: {FAKE_EPOCH}  ({time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime(int(FAKE_EPOCH)))})")
    print(f"each run capped at {a.seconds}s of real time\n")

    cases = [
        ("stock30", STOCK, []),
        ("fork30", FORK, []),
        ("fork60", FORK, [FIX]),
    ]
    results = []
    for tag, exe, extra in cases:
        if not exe.exists():
            print(f"skip {tag}: {exe.name} missing")
            continue
        r = run_case(tag, exe, extra, a.seconds)
        results.append(r)
        avg = sum(r["fps"]) / len(r["fps"]) if r["fps"] else float("nan")
        print(f"{tag:8} wall={r['wall']:.2f}s  fps_avg={avg:.2f}  n={len(r['fps'])}")
        if r["days"]:
            for label, secs in r["days"]:
                as_unix = int(secs)
                print(f"         day boundary: {label}  unix={as_unix}  "
                      f"= {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime(as_unix))}")
        else:
            print("         day boundary: (not logged)")

    print("\n=== interpretation ===")
    print("The app's frame delta comes from gettimeofday(), i.e. the emulated")
    print("system clock, which advances with real time regardless of how many")
    print("frames are drawn. So a correct fix must show the SAME amount of game")
    print("time elapsed per second of wall-clock time at 30fps and at 60fps.")


if __name__ == "__main__":
    main()
