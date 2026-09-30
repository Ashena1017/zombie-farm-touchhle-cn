"""v24 recon:
 (a) who repositions `title1` (the label whose dimensions box we enlarged)?
 (b) the CFString object addresses for 'AmericanTypewriter' vs
     'AmericanTypewriter-Bold' (for the Mausoleum caption de-bolding).
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import Annotator, load

IPA = "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v23fix.ipa"
a = Annotator(load(IPA))
sl = a.sl

WANT_SEL = {"title1", "setTitle1:", "body1", "setBody1:", "setPosition:", "setAnchorPoint:"}
print("== every title1/setPosition send inside ZFAlertWindow* subclasses ==")
for cls_name in sorted(a.by_name):
    if not (cls_name.startswith("ZFAlertWindow") or cls_name in ("ZFMenu", "ZFStorageMenu")):
        continue
    for _s, sel, _m in a.ordered_methods(cls_name):
        _mm, start, end = a.method_range(cls_name, sel)
        if start is None:
            continue
        rows = a.annotate(a.disasm(start, end))
        for i, (x, ann, _) in enumerate(rows):
            if not ann.startswith("MSG "):
                continue
            nm = ann[4:].split("(", 1)[0]
            if nm not in ("setTitle1:", "setBody1:"):
                continue
            print("  %#010x  %s -%s  -> %s" % (x.address, cls_name, sel, nm))
            for y, yann, _ in rows[i + 1:i + 12]:
                if yann.startswith("MSG "):
                    k = yann[4:].split("(", 1)[0]
                    if k in ("setPosition:", "setAnchorPoint:", "addChild:z:",
                             "addChild:z:tag:", "setColor:", "setScale:", "setTag:"):
                        print("        -> %#010x  %s(%s)" % (
                            y.address, k, ", ".join(yann.split("(", 1)[1].rstrip(")").split(", ")[:4])))

print("\n== CFString objects whose text is a bare font name ==")
for sec in sl.sections:
    if sec.name != "__cfstring":
        continue
    for off in range(0, sec.size, 16):
        addr = sec.addr + off
        isa, flags, data, ln = struct.unpack_from("<IIII", sl.data, sec.offset + off)
        if not (0x7C0 <= flags <= 0x7FF) or ln == 0 or ln > 64:
            continue
        o = sl.addr_to_file(data)
        if o is None:
            continue
        try:
            txt = sl.data[o:o + ln].decode("utf-8")
        except Exception:
            continue
        if txt.startswith("AmericanTypewriter"):
            print("  %#010x  len=%2d  %r" % (addr, ln, txt))

print("\n== how the Mausoleum caption loads its fontName (sub9 0xd28f2..0xd2912) ==")
for x, ann, _ in a.annotate(a.disasm(0xD28F2, 0xD2914)):
    print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann))
