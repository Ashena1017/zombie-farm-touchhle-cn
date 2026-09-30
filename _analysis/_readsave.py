import sys, struct, pathlib

QUESTS = pathlib.Path(__file__).resolve().parent / "_quest_titles.txt"


def read(p):
    d = pathlib.Path(p).read_bytes()
    # quest section: find uint32 questCount at 0x10c (recent saves) or 0x130
    for base in (0x10C, 0x130, 0x100, 0x118, 0x124):
        if base + 4 > len(d):
            continue
        n = struct.unpack_from(">I", d, base)[0]
        if not (1 <= n <= 400):
            continue
        pos = base + 4
        recs = []
        try:
            for _ in range(n):
                qid = struct.unpack_from(">I", d, pos)[0]
                cnt = struct.unpack_from(">I", d, pos + 4)[0]
                if cnt > 64:
                    raise ValueError
                pos += 8
                vals = []
                for _i in range(cnt):
                    vals.append(struct.unpack_from(">I", d, pos)[0])
                    pos += 4
                recs.append((qid, vals))
        except Exception:
            continue
        if pos <= len(d):
            return base, recs
    return None, None


for p in sys.argv[1:]:
    base, recs = read(p)
    print("=== %s (%d bytes) ===" % (pathlib.Path(p).name, pathlib.Path(p).stat().st_size))
    if recs is None:
        print("   could not locate quest section")
        continue
    print("   questCount=%d @0x%x" % (len(recs), base))
    nonzero = sum(1 for _q, v in recs if any(v))
    print("   quests with non-zero progress: %d / %d" % (nonzero, len(recs)))
    for qid, vals in recs:
        flag = "" if any(vals) else "   (all zero)"
        print("     ID %-4d %s%s" % (qid, vals, flag))
    print()
