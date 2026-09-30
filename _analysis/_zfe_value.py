#!/usr/bin/env python3
r"""What is a planted zombie's harvest VALUE, and does it match the crop bonus?

Established (byte-verified):
  * the harvest bonus block has exactly ONE guard: [tile fertilized] (0x28a94/0x28a98)
  * there is NO isZombie/isPlant test on that path
  * the bonus pays [market costFromName:name] via [gameData addResource:0 amount:cost]
    i.e. a second copy of the market value -> the "double gold" the human sees

So a fertilized ZOMBIE gets the same second payout as a fertilized crop. This script
confirms the data side: what a zombie's harvest is worth, from Market.plist.

Read-only.
"""
from __future__ import annotations

import plistlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"


def load(blob: bytes):
    if blob[:8] == b"bplist00":
        return plistlib.loads(blob)
    return plistlib.loads(blob)


with zipfile.ZipFile(IPA) as z:
    names = z.namelist()
    market_name = next((n for n in names if n.endswith("Market.plist")), None)
    stats_name = next((n for n in names if n.endswith("UnitStats.plist")), None)
    print(f"Market.plist    : {market_name}")
    print(f"UnitStats.plist : {stats_name}")
    market = load(z.read(market_name))
    stats = load(z.read(stats_name))

# Market.plist shape
print()
print("=" * 78)
print("Market.plist top-level type")
print("=" * 78)
print(f"  {type(market).__name__}")
if isinstance(market, dict):
    print(f"  keys: {list(market)[:20]}")
    items = market.get("items") or market.get("Items") or market
else:
    items = market

# Normalise to a list of dicts.
rows = []
if isinstance(items, list):
    rows = [r for r in items if isinstance(r, dict)]
elif isinstance(items, dict):
    rows = [v for v in items.values() if isinstance(v, dict)]
print(f"  {len(rows)} candidate entries")

print()
print("=" * 78)
print("entries whose category is 'crop' (both plants AND field zombies live here)")
print("=" * 78)
crops = [r for r in rows if str(r.get("category", "")).lower() == "crop"]
print(f"  {len(crops)} entries")

zombies = [r for r in crops if str(r.get("subCategory", "")).lower() == "zombie"]
plants = [r for r in crops if str(r.get("subCategory", "")).lower() != "zombie"]
print(f"    of which subCategory == 'zombie': {len(zombies)}")
print(f"    plants (other subCategories)   : {len(plants)}")

print()
print("=" * 78)
print("ZOMBIE entries: name, cost/value fields")
print("=" * 78)
KEYS = ("name", "unitKey", "cost", "value", "price", "gold", "sellPrice",
        "harvestValue", "growTime", "info")
for r in zombies:
    nm = r.get("name", "?")
    bits = []
    for k in KEYS:
        if k in r:
            bits.append(f"{k}={r[k]!r}")
    print(f"  {nm:<28} {'  '.join(bits)}")

print()
print("=" * 78)
print("for comparison, a few PLANT entries")
print("=" * 78)
for r in plants[:8]:
    nm = r.get("name", "?")
    bits = []
    for k in KEYS:
        if k in r:
            bits.append(f"{k}={r[k]!r}")
    print(f"  {nm:<28} {'  '.join(bits)}")

print()
print("=" * 78)
print("UnitStats.plist: the garden-zombie tier table")
print("=" * 78)
if isinstance(stats, dict):
    for k, v in list(stats.items())[:5]:
        print(f"  {k}: {type(v).__name__}")
    # find garden entries
    for k, v in stats.items():
        if "Garden" in str(k) and isinstance(v, dict):
            print(f"  {k}")
            for kk, vv in v.items():
                print(f"      {kk} = {vv!r}")
