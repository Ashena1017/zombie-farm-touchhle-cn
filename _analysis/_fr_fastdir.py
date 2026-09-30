#!/usr/bin/env python3
"""Find the game's own frame-driver class (FastDirectory) and every string
around it, in both slices of the ZFR executable."""
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import EXECUTABLE, ROOT  # noqa: E402

IPA = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa"
NEEDLES = [
    b"FastDirectory",
    b"doesn't support setAnimationInterval",
    b"setAnimationInterval",
    b"CCFastDirector",
    b"FastDirector",
    b"CCDisplayLinkDirector",
    b"preMainLoop:",
    b"setFrameInterval:",
    b"displayLinkWithTarget",
]


def sec_of(sl, addr):
    for s in sl.sections:
        if s.addr <= addr < s.addr + s.size:
            return s
    return None


def main():
    with zipfile.ZipFile(ROOT / IPA) as z:
        fat = z.read(EXECUTABLE)
    for sl in parse_fat(fat):
        print(f"\n########## sub{sl.subtype} ({len(sl.data)} bytes) ##########")
        for needle in NEEDLES:
            hits = []
            start = 0
            while True:
                i = sl.data.find(needle, start)
                if i < 0:
                    break
                hits.append(i)
                start = i + 1
            if not hits:
                continue
            print(f"\n-- {needle!r}: {len(hits)} hit(s)")
            for off in hits[:12]:
                sec = None
                for s in sl.sections:
                    if s.offset <= off < s.offset + s.size:
                        sec = s
                        break
                addr = (sec.addr + (off - sec.offset)) if sec else None
                # show a little context
                ctx = sl.data[max(0, off - 24):off + len(needle) + 24]
                pretty = re.sub(rb"[^\x20-\x7e]", b".", ctx).decode("ascii")
                print(f"   off={off:#x} addr={addr if addr is None else hex(addr)} "
                      f"sec={sec.name if sec else '?'}  |{pretty}|")


if __name__ == "__main__":
    main()
