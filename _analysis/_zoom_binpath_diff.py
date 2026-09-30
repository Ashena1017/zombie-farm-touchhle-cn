# -*- coding: utf-8 -*-
"""Compare the live touchHLE.exe with the freshly built fork exe: embedded build-path lengths."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = os.path.join(ROOT, 'touchHLE', 'touchHLE.exe')
B = os.path.join(ROOT, 'touchHLE', 'touchHLE_fork.exe')

NEEDLES = [
    rb"touchHLE-zombiefarm\touchHLE\_build_tools",
    rb"touchHLE-zombiefarm\_build_tools",
    rb"touchHLE-zombiefarm\touchHLE\touchHLE-fork",
    rb"touchHLE-zombiefarm\touchHLE-fork",
    rb"touchHLE-zombiefarm\touchHLE\src",
    rb"touchHLE-zombiefarm\src",
]

for path, label in ((A, "live touchHLE.exe"), (B, "new  touchHLE_fork.exe")):
    data = open(path, "rb").read()
    print(f"\n=== {label}  ({len(data)} bytes) ===")
    for n in NEEDLES:
        print(f"   {data.count(n):5d}  x  {n.decode()}")
