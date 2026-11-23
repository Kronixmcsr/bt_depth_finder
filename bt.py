#!/usr/bin/env python3
"""Buried treasure depth histogram for Minecraft Java 1.16.1.

  python bt.py build                                  # compile the biome filter (once)
  python bt.py chain --test                           # ~500 data points over a few random 64-bit seeds
  python bt.py chain --target 10000 --per-seed 500    # the full run
  python bt.py candidates|generate|analyze --seed S   # single-seed tools
  python bt.py selftest
"""
import argparse
import csv
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections import Counter

from btdepth.rng import candidates as rng_candidates, s64
from btdepth.region import read_chunk, chunk_status
from btdepth.rcon import Rcon
from btdepth.column import walk_column
from btdepth.server import Server, write_properties, check_eula, default_cmd, wait_ports_free, HINT

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "tools", "btfilter.exe" if os.name == "nt" else "btfilter")
SOURCES = ["btfilter.c"] + ["cubiomes/%s.c" % n for n in
           ("finders", "generator", "layers", "biomes", "biomenoise", "noise", "util", "quadbase")]
LOOT = "buried_treasure"
FIELDS = ["seed", "x", "y", "z", "depth", "gravel", "stop_block", "stop_y"]
DFIELDS = ["seed", "x", "y", "z", "reason", "reason_y"]


# ---------------------------------------------------------------- candidates
def build():
    cc = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")
    if not cc:
        sys.exit("No C compiler found. Install gcc (Linux: apt install build-essential; "
                 "macOS: xcode-select --install; Windows: MSYS2 mingw-w64 or use WSL).")
    cmd = [cc, "-O3", "-o", EXE] + SOURCES + ["-lm"]
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=os.path.join(HERE, "tools"))
    print("built", EXE)


def find_candidates(seed, radius):
    """Chunks that really hold a chest (1% roll AND beach biome), nearest to spawn first."""
    if os.path.exists(EXE):
        try:
            out = subprocess.run([EXE, str(seed), str(radius)], capture_output=True, text=True, check=True)
            c = [tuple(map(int, l.split())) for l in out.stdout.splitlines() if l.strip()]
            return sorted(c, key=lambda p: p[0] ** 2 + p[1] ** 2)
        except (OSError, subprocess.CalledProcessError) as e:
            print("btfilter failed (%s); try: python bt.py build" % e)
    print("WARNING: biome filter not available -> ~30x more chunks to generate, most with no chest.\n"
          "         Run `python bt.py build` (needs a C compiler).")
    return sorted(rng_candidates(seed, radius), key=lambda p: p[0] ** 2 + p[1] ** 2)


def cmd_candidates(a):
    c = find_candidates(a.seed, a.radius)
    if a.max:
        c = c[:a.max]
    os.makedirs("out", exist_ok=True)
    path = "out/candidates_%d_%d.txt" % (a.seed, a.radius)
    with open(path, "w") as f:
        for cx, cz in c:
            f.write("%d %d  # chest column x=%d z=%d\n" % (cx, cz, cx * 16 + 9, cz * 16 + 9))
    print("%d chunks -> %s (nearest to spawn first)" % (len(c), path))


# ------------------------------------------------------------------ analysis
def analyze_chunks(world, chunks, seed):
    """Returns (rows, discards, missing). Applies the sand-column rules from btdepth/column.py."""
    rows, discards, missing = [], [], 0
    for cx, cz in chunks:
        try:
            root = read_chunk(world, cx, cz)
        except Exception:                        # e.g. half-written chunk after a killed server
            root = None
        if not root or root["Level"].get("Status") != "full":
            missing += 1
            continue
        lvl = root["Level"]
        for te in lvl.get("TileEntities", []):
            if te.get("id") == "minecraft:chest" and LOOT in te.get("LootTable", ""):
                x, y, z = te["x"], te["y"], te["z"]
                r = walk_column(lvl, x, y, z)
                if r["ok"]:
                    rows.append(dict(seed=seed, x=x, y=y, z=z, depth=r["depth"], gravel=r["gravel"],
                                     stop_block=r["stop_block"], stop_y=r["stop_y"]))
                else:
                    discards.append(dict(seed=seed, x=x, y=y, z=z, reason=r["reason"], reason_y=r["reason_y"]))
    return rows, discards, missing


def write_csv(path, fields, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)


def read_csv(path, ints):
    with open(path, newline="") as f:
        return [{k: (int(v) if k in ints else v) for k, v in r.items()} for r in csv.DictReader(f)]


def report(rows, discards, base, title):
    if discards:
        c = Counter(d["reason"] for d in discards)
        print("discarded %d samples: %s" % (len(discards), ", ".join("%s x%d" % kv for kv in c.most_common(8))))
    if not rows:
        print("no valid samples.")
        return
    depths = [r["depth"] for r in rows]
    counts = Counter(depths)
    print("\nSand blocks above the chest (n=%d):" % len(rows))
    peak = max(counts.values())
    for d in range(min(depths), max(depths) + 1):
        n = counts.get(d, 0)
        print("%4d | %-40s %d" % (d, "#" * int(40 * n / peak), n))
    print("mean %.2f  median %d  min %d  max %d" % (
        sum(depths) / len(depths), sorted(depths)[len(depths) // 2], min(depths), max(depths)))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.figure()
        plt.hist(depths, bins=range(min(depths), max(depths) + 2), align="left", edgecolor="k")
        plt.xlabel("Sand blocks above the chest"); plt.ylabel("Chests")
        plt.title("%s (n=%d)" % (title, len(depths)))
        plt.savefig(base + ".png", dpi=150)
        print("saved", base + ".png")
    except ImportError:
        print("(pip install matplotlib for a PNG)")


# ------------------------------------------------------------------ generate
def loaded_state(rc, cx, cz):
    """True = chunk fully loaded, False = not yet, None = unrecognised reply."""
    r = rc.command("execute if block %d 0 %d minecraft:bedrock" % (cx * 16 + 9, cz * 16 + 9))
    if "not loaded" in r.lower():
        return False
    if "Test passed" in r or "Test failed" in r:
        return True
    return None


def prepare_server(rc, seed):
    m = re.search(r"-?\d+", rc.command("seed"))
    if m and int(m.group()) != seed:
        raise SystemExit("Server seed is %s but expected %d." % (m.group(), seed))
    for rule in ("randomTickSpeed 0", "doMobSpawning false", "doFireTick false",
                 "doDaylightCycle false", "doWeatherCycle false"):
        rc.command("gamerule " + rule)
    rc.command("forceload remove all")


def generate_chunks(rc, cands, world, batch, poll, timeout):
    """Force-load candidate chunks in batches until saved as 'full'. Returns chunks still not full."""
    todo = [p for p in cands if chunk_status(world, *p) != "full"]
    print("  %d chunks wanted, %d to generate" % (len(cands), len(todo)))
    t0, done = time.time(), 0
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        for cx, cz in part:
            rc.command("forceload add %d %d" % (cx * 16 + 9, cz * 16 + 9))
        pending, deadline, disk_mode = list(part), time.time() + timeout, False
        while pending and time.time() < deadline:
            time.sleep(poll)
            if not disk_mode:
                states = [(p, loaded_state(rc, *p)) for p in pending]
                if any(s is None for _, s in states):
                    disk_mode = True      # reply format not recognised: fall back to disk checks
                    continue
                pending = [p for p, s in states if not s]
            else:
                rc.command("save-all flush")
                pending = [p for p in pending if chunk_status(world, *p) != "full"]
        rc.command("save-all flush")          # flush while still loaded, then release
        rc.command("forceload remove all")
        done += len(part)
        el = time.time() - t0
        print("  %d/%d chunks | %.1f chunks/min" % (done, len(todo), done / max(el, 1) * 60))
    return [p for p in cands if chunk_status(world, *p) != "full"]


def cmd_generate(a):
    cands = find_candidates(a.seed, a.radius)
    if a.max:
        cands = cands[:a.max]
    rc = Rcon(a.host, a.rcon_port, a.password, timeout=a.rcon_timeout)
    prepare_server(rc, a.seed)
    left = generate_chunks(rc, cands, a.world, a.batch, a.poll, a.timeout)
    rc.close()
    if left:
        print("%d chunks not saved as 'full'; rerun the same command to retry." % len(left))
    print("done. now: python bt.py analyze --seed %d --radius %d --max %d" % (a.seed, a.radius, a.max))


def cmd_analyze(a):
    cands = find_candidates(a.seed, a.radius)
    if a.max:
        cands = cands[:a.max]
    rows, discards, missing = analyze_chunks(a.world, cands, a.seed)
    print("expected chunks: %d | not generated: %d | valid: %d | discarded: %d" % (
        len(cands), missing, len(rows), len(discards)))
    os.makedirs("out", exist_ok=True)
    base = "out/chests_%d" % a.seed
    write_csv(base + ".csv", FIELDS, rows)
    write_csv(base + "_discarded.csv", DFIELDS, discards)
    report(rows, discards, base, "Buried treasure sand depth, seed %d" % a.seed)


# --------------------------------------------------------------------- chain
def split_cmd(text):
    """Split a command line; Windows-safe (keeps backslashes, honours "quotes")."""
    return [t.strip('"') for t in shlex.split(text, posix=(os.name != "nt"))]


def make_seeds(n, rng_seed):
    r = random.Random(rng_seed)
    return [s64(r.getrandbits(64)) for _ in range(n)]


def run_seed(a, seed, outdir):
    """Fresh server for one seed -> generate -> analyze -> per-seed CSVs. Returns (rows, discards)."""
    sdir = os.path.abspath(a.server_dir)
    level = "world_" + str(seed).replace("-", "n")
    world = os.path.join(sdir, level)
    cands = find_candidates(seed, a.radius)[:a.per_seed]
    print("seed %d: %d chest chunks selected (nearest %d)" % (seed, len(cands), a.per_seed))
    if not cands:
        return [], []
    if not wait_ports_free(a.host, [a.rcon_port, a.server_port]):
        raise SystemExit("Port %d or %d is already in use, so a server is still running." % (a.rcon_port, a.server_port) + HINT)
    write_properties(os.path.join(sdir, "server.properties"), {
        "server-port": a.server_port, "level-seed": seed, "level-name": level, "enable-rcon": "true", "rcon.port": a.rcon_port,
        "rcon.password": a.password, "max-tick-time": -1, "sync-chunk-writes": "false"})
    cmd = split_cmd(a.server_cmd) if a.server_cmd else default_cmd(a.java_args)
    srv = Server(sdir, cmd)
    rc = None
    try:
        srv.start()
        rc = srv.connect_rcon(a.host, a.rcon_port, a.password, timeout=a.rcon_timeout)
        prepare_server(rc, seed)
        left = cands
        for attempt in range(3):
            left = generate_chunks(rc, cands, world, a.batch, a.poll, a.timeout)
            if not left:
                break
            print("  %d chunks not saved, retrying" % len(left))
    finally:
        srv.stop(rc)
    rows, discards, missing = analyze_chunks(world, cands, seed)
    print("  valid %d, discarded %d, missing chunks %d" % (len(rows), len(discards), missing))
    write_csv(os.path.join(outdir, "seed_%d.csv" % seed), FIELDS, rows)
    write_csv(os.path.join(outdir, "seed_%d_discarded.csv" % seed), DFIELDS, discards)
    if not a.keep_worlds:
        shutil.rmtree(world, ignore_errors=True)
    return rows, discards


def cmd_chain(a):
    if a.test:
        a.target, a.per_seed = 500, 100
        a.out = a.out or "out/test"
    outdir = a.out or "out/chain"
    os.makedirs(outdir, exist_ok=True)
    if not a.server_cmd:
        check_eula(a.server_dir)
    seeds_file = os.path.join(outdir, "seeds.txt")
    if a.seeds:
        seeds = [int(s) for s in a.seeds.split(",")]
    elif os.path.exists(seeds_file):
        seeds = [int(l) for l in open(seeds_file).read().split()]
    else:
        seeds = make_seeds(a.max_seeds, a.rng_seed)
    open(seeds_file, "w").write("\n".join(map(str, seeds)) + "\n")

    all_rows, all_disc = [], []
    for seed in seeds:
        have = os.path.join(outdir, "seed_%d.csv" % seed)
        if os.path.exists(have):                                  # finished earlier: resume
            all_rows += read_csv(have, {"seed", "x", "y", "z", "depth", "gravel", "stop_y"})
            all_disc += read_csv(have.replace(".csv", "_discarded.csv"), {"seed", "x", "y", "z", "reason_y"})
            print("seed %d: already done" % seed)
        elif len(all_rows) < a.target:
            for attempt in range(1, 4):          # the world is kept between attempts, so this resumes
                try:
                    rows, disc = run_seed(a, seed, outdir)
                    break
                except (OSError, RuntimeError) as e:
                    print("seed %d failed (%s: %s), attempt %d/3" % (seed, type(e).__name__, e, attempt))
                    time.sleep(10)
            else:
                print("seed %d skipped after 3 failed attempts; rerun the command later to retry it." % seed)
                continue
            all_rows += rows; all_disc += disc
        print("== %d / %d valid samples" % (len(all_rows), a.target))
        if len(all_rows) >= a.target:
            break
    write_csv(os.path.join(outdir, "combined.csv"), FIELDS, all_rows)
    write_csv(os.path.join(outdir, "combined_discarded.csv"), DFIELDS, all_disc)
    if len(all_rows) < a.target:
        print("Only %d/%d reached; raise --max-seeds or --radius/--per-seed and rerun (finished seeds are kept)."
              % (len(all_rows), a.target))
    report(all_rows, all_disc, os.path.join(outdir, "histogram"), "Buried treasure sand depth")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("selftest")

    def common(s):
        s.add_argument("--radius", type=int, default=600, help="in chunks, square [-r, r)")
        s.add_argument("--host", default="127.0.0.1")
        s.add_argument("--rcon-port", type=int, default=25575)
        s.add_argument("--password", default="btdepth")
        s.add_argument("--batch", type=int, default=96, help="chunks generated in parallel")
        s.add_argument("--poll", type=float, default=1.0)
        s.add_argument("--timeout", type=float, default=900)
        s.add_argument("--rcon-timeout", type=float, default=600, help="seconds to wait for one RCON reply")

    for name in ("candidates", "generate", "analyze"):
        s = sub.add_parser(name)
        s.add_argument("--seed", type=int, required=True)
        s.add_argument("--world", default="server/world")
        s.add_argument("--max", type=int, default=0, help="only the N chests nearest spawn")
        common(s)
    s = sub.add_parser("chain", help="several random 64-bit seeds, one fresh server per seed")
    common(s)
    s.set_defaults(radius=800)
    s.add_argument("--server-port", type=int, default=25565)
    s.add_argument("--target", type=int, default=10000, help="valid data points wanted in total")
    s.add_argument("--per-seed", type=int, default=500, help="nearest N chests used per seed")
    s.add_argument("--test", action="store_true", help="small test: target 500, 100 per seed, out/test")
    s.add_argument("--max-seeds", type=int, default=60)
    s.add_argument("--rng-seed", type=int, default=2024, help="reproducible seed list")
    s.add_argument("--seeds", help="comma-separated explicit 64-bit seeds (overrides random)")
    s.add_argument("--out", help="output folder (default out/chain, or out/test with --test)")
    s.add_argument("--server-dir", default="server")
    s.add_argument("--java-args", default="-Xms4G -Xmx8G -XX:+UseG1GC")
    s.add_argument("--server-cmd", help="override the launch command (advanced/testing)")
    s.add_argument("--keep-worlds", action="store_true", help="don't delete each world after analysis")
    a = p.parse_args()
    if a.cmd == "selftest":
        import selftest
        sys.exit(selftest.run())
    if a.cmd == "build":
        return build()
    {"candidates": cmd_candidates, "generate": cmd_generate, "analyze": cmd_analyze, "chain": cmd_chain}[a.cmd](a)


if __name__ == "__main__":
    main()
