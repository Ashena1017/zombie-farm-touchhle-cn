#!/usr/bin/env python3
"""Does the ZFR binary reference the GL symbols whose scaling we changed?

We scale the viewport/scissor/renderbuffer on the host side only. If the guest
never names those entry points, it cannot be reading back a scaled value, which
would rule out "the app asks GL how big it is" as the cause of the floating
lights and point the finger at the app's own screen-size math instead.

Usage: python _analysis/_gl_symcheck.py
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"

NAMES = [
    # things whose *scaled* value we hand back to the guest
    b"glGetRenderbufferParameterivOES",
    b"glGetRenderbufferParameteriv",
    b"glGetIntegerv",
    b"glViewport",
    b"glScissor",
    b"glRenderbufferStorageOES",
    b"glRenderbufferStorage",
    b"glGetError",
    # matrix stack / projection, i.e. where getZEye is consumed
    b"glOrthof",
    b"glFrustumf",
    b"glMatrixMode",
    b"glLoadMatrixf",
    b"glMultMatrixf",
    b"glPushMatrix",
    b"glPopMatrix",
    b"glLoadIdentity",
    # sprites and points
    b"glDrawArrays",
    b"glDrawElements",
    b"glDrawTex",
    b"glPointSize",
    b"glPointSizePointerOES",
    b"glVertexPointer",
    b"glTexCoordPointer",
    b"glColorPointer",
    b"glBlendFunc",
    # readback / copy (framebuffer-sized operations)
    b"glReadPixels",
    b"glCopyTexImage2D",
    b"glCopyTexSubImage2D",
    # selectors the app could use to ask the view how big it is
    b"backingWidth",
    b"backingHeight",
    b"drawableProperties",
    b"contentScaleFactor",
    b"setContentScaleFactor:",
    b"recalculateProjectionAndEAGLViewSize",
    b"surfaceSize",
    b"getZEye",
    b"setProjection:",
]


def main() -> int:
    with zipfile.ZipFile(IPA) as z:
        fat = z.read("Payload/ZFR.app/ZFR")
    for sl in parse_fat(fat):
        if sl.subtype != 9:
            continue
        data = sl.data
        print(f"===== sub{sl.subtype} ({len(data)} bytes) =====")
        for n in NAMES:
            hits = []
            start = 0
            while True:
                i = data.find(n, start)
                if i < 0:
                    break
                hits.append(i)
                start = i + 1
                if len(hits) > 20:
                    break
            # NUL-terminated occurrence is the one a linker/objc string table
            # would use; a bare substring may be part of a longer identifier.
            exact = [h for h in hits if data[h + len(n):h + len(n) + 1] == b"\0"]
            mark = "REF" if exact else ("sub" if hits else "---")
            print(
                "  %-36s %-3s  at=%s exact=%s"
                % (n.decode(), mark, [hex(h) for h in hits[:4]], len(exact))
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
