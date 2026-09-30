import pathlib

for name in ("_zfz_arial_table.py", "_zfz_table_arg2.py"):
    p = pathlib.Path("_analysis") / name
    s = p.read_text(encoding="utf-8")
    s2 = s.replace("ops[0].type == 3", "ops[0].type == 1").replace("ops[1].type == 3", "ops[1].type == 1")
    p.write_text(s2, encoding="utf-8")
    print(name, "patched:", s != s2)
