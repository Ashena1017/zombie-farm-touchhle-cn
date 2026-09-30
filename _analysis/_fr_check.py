#!/usr/bin/env python3
"""Decisive checks for the ZFR frame-rate investigation.

1. What the game computes as CADisplayLink.frameInterval:
   animationInterval (double at sub6 0x190bd8) * 60.0, then vcvt.s32.f64
   (truncate toward zero). If the product is even a hair below 1.0 the
   result is 0, which touchHLE asserts on -- so this must be exactly 1.0.
2. Whether 1/60 * 60 round-trips to exactly 1.0 in IEEE-754 double.
3. How long a 1/60 second run-loop wake period is vs the 16 ms the
   integer-division `Duration::from_millis(1000 / 60)` produces.
"""
import struct

RAW = bytes.fromhex("111111111111913f")
anim_interval = struct.unpack("<d", RAW)[0]
one_sixtieth = 1.0 / 60.0

print(f"raw double at 0x190bd8      : {anim_interval!r}")
print(f"same as 1.0/60.0 in Python  : {anim_interval == one_sixtieth}")
print(f"product  * 60.0             : {anim_interval * 60.0!r}")
print(f"product  == 1.0             : {anim_interval * 60.0 == 1.0}")
print(f"int(trunc) of product       : {int(anim_interval * 60.0)}")
print()

# The exact decimal expansions, to show the double is just below 1/60.
print("exact value of the double   :", format(anim_interval, ".20f"))
print("exact value of 1/60         :", format(one_sixtieth, ".20f"))
print("double is below 1/60        :", anim_interval < one_sixtieth)
print()

# touchHLE run-loop sleep cap: Duration::from_millis(1000 / 60) -- INTEGER division.
cap_ms_integer = 1000 // 60
cap_ms_true = 1000.0 / 60.0
print(f"1000 / 60 (Rust, both u64)  : {cap_ms_integer} ms   <-- what ns_run_loop.rs uses")
print(f"1000.0 / 60.0 (true)        : {cap_ms_true!r} ms")
print(f"shortfall per wake          : {cap_ms_true - cap_ms_integer!r} ms")
print()

# touchHLE display-link interval, set from setFrameInterval:1
print("CADisplayLink frameInterval passed by the game : 1")
print(f"touchHLE interval = 1/60 s  : {1.0/60.0!r} s = {1000.0/60.0!r} ms")
print(f"advance_by = ceil(overdue/interval): needs overdue > "
      f"{1000.0/60.0!r} ms before it skips a whole interval (halving the rate)")
