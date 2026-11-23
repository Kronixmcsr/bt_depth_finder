"""Java Random + the 1.16.1 buried-treasure start check (pure Python, no deps)."""

MASK = (1 << 48) - 1
MULT = 0x5DEECE66D
ADD = 0xB


def s64(v):
    v &= 0xFFFFFFFFFFFFFFFF
    return v - (1 << 64) if v >= (1 << 63) else v


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >= (1 << 31) else v


class JavaRandom:
    def __init__(self, seed):
        self.seed = (seed ^ MULT) & MASK

    def set_seed(self, seed):
        self.seed = (seed ^ MULT) & MASK

    def next(self, bits):
        self.seed = (self.seed * MULT + ADD) & MASK
        return s32(self.seed >> (48 - bits)) if bits == 32 else self.seed >> (48 - bits)

    def next_long(self):
        hi = self.next(32)
        lo = self.next(32)
        return s64((hi << 32) + lo)

    def next_float(self):
        return self.next(24) / float(1 << 24)


SALT = 10387320  # buried treasure region salt (1.13 - 1.17)


def chunk_has_treasure_start(world_seed, cx, cz, prob=0.01):
    """1.16.1 BuriedTreasureFeature: setRegionSeed(seed, cx, cz, 10387320); nextFloat() < 0.01.
    (An earlier version of this project used the carver seed. That was wrong.)"""
    r = JavaRandom(s64(cx * 341873128712 + cz * 132897987541 + world_seed + SALT))
    return r.next_float() < prob


def candidates(world_seed, radius, prob=0.01):
    """Chunks in [-radius, radius)^2 passing the 1% roll. Biome NOT checked (pure-Python fallback)."""
    out = []
    for cx in range(-radius, radius):
        for cz in range(-radius, radius):
            s = (cx * 341873128712 + cz * 132897987541 + world_seed + SALT) ^ MULT
            s = (s & MASK) * MULT + ADD & MASK
            if (s >> 24) / 16777216.0 < prob:
                out.append((cx, cz))
    return out
