# -*- coding: utf-8 -*-
"""Deeper scan: UIScrollView zoom API, camera zoom selectors, and ObjC class refs."""
import re
import sys

BIN = sys.argv[1] if len(sys.argv) > 1 else r"<PATH-TO-EXTRACTED-ZFR-BIN>"
data = open(BIN, "rb").read()

strings = [(m.start(), m.group().decode("ascii")) for m in re.finditer(rb"[\x20-\x7e]{3,}", data)]

def find(*pats):
    print("\n=== " + " | ".join(pats) + " ===")
    seen = set()
    n = 0
    for off, s in strings:
        if any(p in s for p in pats):
            if s in seen:
                continue
            seen.add(s)
            n += 1
            print(f"  0x{off:08x}  {s[:130]}")
    print(f"  ({n} unique)")

find("zoomScale", "setZoomScale", "maximumZoomScale", "minimumZoomScale", "bouncesZoom")
find("UIScrollView", "UIWebView", "UIPinchGesture", "UIRotationGesture", "UISwipeGesture", "UILongPressGesture", "UIPanGesture")
find("ZoomOutAmount", "resetCamera", "zoomFactor", "Camera")
find("setCamera", "camera", "Camera")
find("scaleCompensation", "initElementsWithWindowScale")
find("pinchDistance", "distance", "twoTouches", "touchesCount")
