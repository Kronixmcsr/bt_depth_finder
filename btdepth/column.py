"""Walk up the block column above a buried-treasure chest and measure its sand depth.

Rules (edit the sets below to change them):
  - start at the block directly above the chest, go up
  - stop (valid sample) at the first air / water / non-solid decoration block
  - minecraft:sand blocks are counted
  - gravel is skipped: not counted, does not stop the walk
  - any other block (planks, logs, stone, ice, ...) -> sample is discarded
"""

SAND = {"minecraft:sand", "minecraft:red_sand"}
GRAVEL = {"minecraft:gravel"}
# "Open" blocks that end the walk. Seagrass/kelp/snow layers etc. sit on top of the sand and
# count as the surface, not as terrain.
STOP = {
    "minecraft:air", "minecraft:cave_air", "minecraft:void_air",
    "minecraft:water", "minecraft:bubble_column",
    "minecraft:seagrass", "minecraft:tall_seagrass", "minecraft:kelp", "minecraft:kelp_plant",
    "minecraft:sea_pickle", "minecraft:snow", "minecraft:grass", "minecraft:tall_grass",
    "minecraft:fern", "minecraft:large_fern", "minecraft:dead_bush", "minecraft:sugar_cane",
    "minecraft:lily_pad",
}


def block_name(sections, x, y, z):
    """Block id at world (x, y, z) from a 1.16 chunk's Sections (dict Y -> section)."""
    sec = sections.get(y >> 4)
    if sec is None:
        return "minecraft:air"
    palette = sec.get("Palette")
    if not palette:
        return "minecraft:air"
    states = sec.get("BlockStates")
    if not states:
        return palette[0]["Name"]
    bits = max(4, (len(palette) - 1).bit_length())
    per_long = 64 // bits                      # 1.16: entries never span two longs
    idx = ((y & 15) << 8) | ((z & 15) << 4) | (x & 15)
    word = states[idx // per_long] & 0xFFFFFFFFFFFFFFFF
    return palette[(word >> ((idx % per_long) * bits)) & ((1 << bits) - 1)]["Name"]


def walk_column(level, x, y, z):
    """level = chunk['Level'] dict. Returns dict(ok=True, depth, gravel, stop_block, stop_y)
    or dict(ok=False, reason=<block id or marker>, reason_y)."""
    sections = {s["Y"]: s for s in level.get("Sections", [])}
    depth = gravel = 0
    for yy in range(y + 1, 256):
        name = block_name(sections, x, yy, z)
        if name in STOP:
            return dict(ok=True, depth=depth, gravel=gravel, stop_block=name, stop_y=yy)
        if name in SAND:
            depth += 1
        elif name in GRAVEL:
            gravel += 1
        else:
            return dict(ok=False, reason=name, reason_y=yy)
    return dict(ok=False, reason="reached_build_limit", reason_y=256)
