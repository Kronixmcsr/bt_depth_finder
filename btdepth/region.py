"""Read single chunks out of Anvil .mca region files."""
import os
import struct
import zlib

from .nbt import parse_nbt


def read_chunk(world_dir, cx, cz):
    """Return the chunk's root NBT dict, or None if the chunk isn't saved."""
    path = os.path.join(world_dir, "region", "r.%d.%d.mca" % (cx >> 5, cz >> 5))
    if not os.path.exists(path):
        return None
    idx = (cx & 31) + (cz & 31) * 32
    with open(path, "rb") as f:
        f.seek(4 * idx)
        entry = f.read(4)
        if len(entry) < 4:
            return None
        off = int.from_bytes(entry[:3], "big")
        if off == 0:
            return None
        f.seek(off * 4096)
        length = struct.unpack(">I", f.read(4))[0]
        ctype = f.read(1)[0]
        raw = f.read(length - 1)
    if ctype == 2:
        raw = zlib.decompress(raw)
    elif ctype == 1:
        raw = zlib.decompress(raw, 31)
    elif ctype != 3:
        return None
    return parse_nbt(raw)


def chunk_status(world_dir, cx, cz):
    try:
        root = read_chunk(world_dir, cx, cz)
    except Exception:
        return None  # file mid-write; treat as not ready
    if not root:
        return None
    return root.get("Level", {}).get("Status")


def heightmap_value(longs, lx, lz):
    """1.16 heightmaps: 256 entries x 9 bits, 7 entries per long (non-spanning)."""
    i = lz * 16 + lx
    v = longs[i // 7] & 0xFFFFFFFFFFFFFFFF
    return (v >> ((i % 7) * 9)) & 0x1FF
