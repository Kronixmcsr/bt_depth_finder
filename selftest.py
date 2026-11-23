"""Offline checks that don't need a Minecraft server."""
import os, struct, tempfile, zlib
from btdepth.rng import JavaRandom, candidates
from btdepth.nbt import parse_nbt
from btdepth.region import read_chunk, heightmap_value


def w_str(s):
    b = s.encode(); return struct.pack(">H", len(b)) + b

def w_named(tag, name, payload):
    return bytes([tag]) + w_str(name) + payload

def w_long_array(vals):
    return struct.pack(">i", len(vals)) + struct.pack(">%dq" % len(vals), *vals)

def pack_heightmap(vals):
    longs = [0] * 37
    for i, v in enumerate(vals):
        longs[i // 7] |= v << ((i % 7) * 9)
    return [x - (1 << 64) if x >= (1 << 63) else x for x in longs]


def run():
    ok = True
    # 1. Java Random reference values
    r = JavaRandom(42)
    ok &= r.next(32) == -1170105035
    ok &= JavaRandom(0).next_long() == -4962768465676381896
    print("java random reference values:", "OK" if ok else "FAIL")

    # 2. python RNG must reproduce cubiomes' buried-treasure rolls exactly
    import subprocess
    from bt import EXE
    c = set(candidates(12345, 400))
    good = 0.007 < len(c) / 640000 < 0.013
    if os.path.exists(EXE):
        out = subprocess.run([EXE, "12345", "400"], capture_output=True, text=True).stdout
        beach = set(tuple(map(int, l.split())) for l in out.splitlines())
        good &= len(beach) > 0 and beach <= c
        print("python RNG vs cubiomes (%d beach chunks, subset of %d rolls):" % (len(beach), len(c)),
              "OK" if good else "FAIL")
    else:
        print("btfilter not built, skipped cubiomes cross-check; rate OK" if good else "rate FAIL")
    ok &= good

    # 3. NBT + region + heightmap round trip with a fake chunk
    hm = [60 + (i % 5) for i in range(256)]
    chest = (w_named(8, "id", w_str("minecraft:chest")) + w_named(8, "LootTable", w_str("minecraft:chests/buried_treasure"))
             + w_named(3, "x", struct.pack(">i", 41)) + w_named(3, "y", struct.pack(">i", 52))
             + w_named(3, "z", struct.pack(">i", 41)) + b"\x00")
    lvl = (w_named(8, "Status", w_str("full"))
           + w_named(10, "Heightmaps", w_named(12, "OCEAN_FLOOR", w_long_array(pack_heightmap(hm))) + b"\x00")
           + w_named(9, "TileEntities", bytes([10]) + struct.pack(">i", 1) + chest) + b"\x00")
    root = bytes([10]) + w_str("") + w_named(10, "Level", lvl) + b"\x00"
    comp = zlib.compress(root)
    cx, cz = 2, 2   # chunk containing x=41,z=41
    d = tempfile.mkdtemp(); os.makedirs(d + "/region")
    idx = (cx & 31) + (cz & 31) * 32
    header = bytearray(8192); header[4 * idx:4 * idx + 4] = (2).to_bytes(3, "big") + b"\x01"
    sector = struct.pack(">IB", len(comp) + 1, 2) + comp
    sector += b"\0" * (-len(sector) % 4096)
    open(d + "/region/r.0.0.mca", "wb").write(bytes(header) + sector)
    got = read_chunk(d, cx, cz)["Level"]
    te = got["TileEntities"][0]
    lx, lz = te["x"] & 15, te["z"] & 15
    h = heightmap_value(got["Heightmaps"]["OCEAN_FLOOR"], lx, lz)
    good = h == hm[lz * 16 + lx] and te["y"] == 52 and got["Status"] == "full"
    ok &= good
    print("nbt/region/heightmap round trip:", "OK" if good else "FAIL")
    # 4. column rules (sand counted, gravel skipped, stop at air/water, discard other blocks)
    from btdepth.column import walk_column
    def col(blocks, chest_y=50):
        pal = ["minecraft:air"] + sorted(set(blocks))
        idx = {n: i for i, n in enumerate(pal)}
        cells = [0] * 4096
        for k, n in enumerate(blocks):           # blocks[0] sits at chest_y + 1
            cells[(((chest_y + 1 + k) & 15) << 8) | (9 << 4) | 9] = idx[n]
        bits = max(4, (len(pal) - 1).bit_length()); per = 64 // bits
        longs = [0] * ((4096 + per - 1) // per)
        for i, v in enumerate(cells):
            longs[i // per] |= v << ((i % per) * bits)
        longs = [x - (1 << 64) if x >= (1 << 63) else x for x in longs]
        return {"Sections": [{"Y": chest_y >> 4, "Palette": [{"Name": n} for n in pal], "BlockStates": longs}]}
    S, G, W, A = "minecraft:sand", "minecraft:gravel", "minecraft:water", "minecraft:air"
    cases = [
        ("3 sand then water", [S, S, S, W], True, 3),
        ("sand gravel sand air", [S, G, S, A], True, 2),
        ("water right above", [W, S], True, 0),
        ("ice over water ignored", [S, W, "minecraft:ice"], True, 1),
        ("village planks", [S, S, "minecraft:oak_planks"], False, None),
        ("acacia log", [S, "minecraft:acacia_log"], False, None),
        ("terrain layers above", [S, S, "minecraft:stone", S, A], False, None),
    ]
    good = True
    for name, blocks, valid, d in cases:
        r = walk_column(col(blocks), 9, 50, 9)
        if r["ok"] != valid or (valid and r["depth"] != d):
            good = False; print("  FAIL:", name, r)
    ok &= good
    print("column rules:", "OK" if good else "FAIL")

    # 5. 64-bit (negative / huge) seeds: python RNG vs cubiomes
    if os.path.exists(EXE):
        good = True
        for sd in (-6240136574013258961, 8123456789012345678):
            out = subprocess.run([EXE, str(sd), "300"], capture_output=True, text=True).stdout
            beach = set(tuple(map(int, l.split())) for l in out.splitlines())
            good &= beach <= set(candidates(sd, 300))
        ok &= good
        print("64-bit seeds vs cubiomes:", "OK" if good else "FAIL")
    print("ALL OK" if ok else "FAILURES")
    return 0 if ok else 1
