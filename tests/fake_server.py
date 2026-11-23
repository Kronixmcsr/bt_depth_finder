"""Stand-in for the Minecraft server, for testing `bt.py chain` without Minecraft.
Reads server.properties in the cwd, speaks RCON, and writes fake 'full' chunks with a buried-treasure
chest and a block column chosen by chunk coordinates (see PATTERNS)."""
import os, re, socket, struct, sys, threading, time, zlib

def props():
    d = {}
    for l in open("server.properties"):
        if "=" in l and not l.startswith("#"):
            k, v = l.strip().split("=", 1); d[k] = v
    return d

S, G, W, A = "minecraft:sand", "minecraft:gravel", "minecraft:water", "minecraft:air"
PATTERNS = [[S, S, W], [S, G, S, A], [S, S, "minecraft:oak_planks"], [W], [S, S, S, S, W], [S, W, "minecraft:ice"]]
def pattern(cx, cz): return PATTERNS[(cx * 7 + cz * 3) % len(PATTERNS)]

# --- tiny NBT writer
def nstr(s): b = s.encode(); return struct.pack(">H", len(b)) + b
def named(t, n, p): return bytes([t]) + nstr(n) + p
def longarr(v): return struct.pack(">i", len(v)) + struct.pack(">%dq" % len(v), *v)

def chunk_nbt(cx, cz):
    x, z, y = cx * 16 + 9, cz * 16 + 9, 50
    blocks = pattern(cx, cz)
    pal = [A] + sorted(set(blocks)); idx = {n: i for i, n in enumerate(pal)}
    cells = [0] * 4096
    for k, n in enumerate(blocks):
        cells[(((y + 1 + k) & 15) << 8) | (9 << 4) | 9] = idx[n]
    bits = max(4, (len(pal) - 1).bit_length()); per = 64 // bits
    longs = [0] * ((4096 + per - 1) // per)
    for i, v in enumerate(cells): longs[i // per] |= v << ((i % per) * bits)
    longs = [q - (1 << 64) if q >= (1 << 63) else q for q in longs]
    palette = b"".join(named(8, "Name", nstr(n)) + b"\x00" for n in pal)
    section = (named(1, "Y", bytes([y >> 4])) + named(9, "Palette", bytes([10]) + struct.pack(">i", len(pal)) + palette)
               + named(12, "BlockStates", longarr(longs)) + b"\x00")
    chest = (named(8, "id", nstr("minecraft:chest")) + named(8, "LootTable", nstr("minecraft:chests/buried_treasure"))
             + named(3, "x", struct.pack(">i", x)) + named(3, "y", struct.pack(">i", y))
             + named(3, "z", struct.pack(">i", z)) + b"\x00")
    lvl = (named(8, "Status", nstr("full"))
           + named(9, "Sections", bytes([10]) + struct.pack(">i", 1) + section)
           + named(9, "TileEntities", bytes([10]) + struct.pack(">i", 1) + chest) + b"\x00")
    return bytes([10]) + nstr("") + named(10, "Level", lvl) + b"\x00"

def save(world, forced):
    os.makedirs(world + "/region", exist_ok=True)
    regions = {}
    for x, z in forced:
        cx, cz = (x - 9) // 16, (z - 9) // 16
        regions.setdefault((cx >> 5, cz >> 5), []).append((cx, cz))
    for (rx, rz), cl in regions.items():
        path = "%s/region/r.%d.%d.mca" % (world, rx, rz)
        data = bytearray(open(path, "rb").read()) if os.path.exists(path) else bytearray(8192)
        for cx, cz in cl:
            comp = zlib.compress(chunk_nbt(cx, cz))
            sec = struct.pack(">IB", len(comp) + 1, 2) + comp
            sec += b"\0" * (-len(sec) % 4096)
            i = (cx & 31) + (cz & 31) * 32
            data[4*i:4*i+4] = (len(data) // 4096).to_bytes(3, "big") + b"\x01"
            data += sec
        open(path, "wb").write(bytes(data))

def main():
    P = props(); world = P["level-name"]; seed = P["level-seed"]
    forced, polls, state = [], {}, {"stalled": False}
    stall = os.environ.get("FAKE_STALL") == "1"
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", int(P["rcon.port"]))); srv.listen(5)
    print("Done (0.1s)! For help, type \"help\"", flush=True)

    def handle(conn):
        def rd(n):
            b = b""
            while len(b) < n:
                c = conn.recv(n - len(b))
                if not c: raise EOFError
                b += c
            return b
        try:
            while True:
                (l,) = struct.unpack("<i", rd(4)); d = rd(l)
                rid, t = struct.unpack("<ii", d[:8]); cmd = d[8:-2].decode(); out = ""
                if t == 3 and cmd != P["rcon.password"]: rid = -1
                if t == 2:
                    if cmd == "seed": out = "Seed: [%s]" % seed
                    elif cmd.startswith("forceload add"): forced.append(tuple(map(int, cmd.split()[2:4])))
                    elif cmd == "forceload remove all": forced.clear()
                    elif cmd.startswith("execute if block"):
                        k = (cmd.split()[3], cmd.split()[5]); polls[k] = polls.get(k, 0) + 1
                        out = "That position is not loaded" if polls[k] < 3 else "Test failed"
                    elif cmd == "save-all flush":
                        if stall and not state["stalled"]:     # one reply slower than the client timeout
                            state["stalled"] = True; time.sleep(3)
                        save(world, forced)
                    elif cmd == "stop":
                        conn.sendall(struct.pack("<i", 10) + struct.pack("<ii", rid, 0) + b"\x00\x00"); os._exit(0)
                body = struct.pack("<ii", rid, 0) + out.encode() + b"\x00\x00"
                conn.sendall(struct.pack("<i", len(body)) + body)
        except (EOFError, OSError):
            pass

    while True:
        threading.Thread(target=handle, args=(srv.accept()[0],), daemon=True).start()

main()
