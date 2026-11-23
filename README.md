# Buried treasure depth histogram (Minecraft Java 1.16.1), v3

Picks real buried-treasure chunks (correct RNG + beach biome, via Cubiomes), has a real 1.16.1 server generate
them, and measures how many **sand blocks** you'd mine to reach each chest. `chain` repeats this over many
random 64-bit seeds (fresh server + world per seed) and merges everything into one dataset and histogram.

## Depth rule (v3)  -> `btdepth/column.py`
Start at the block directly above the chest and walk up:
- `sand` -> counted. `gravel` -> skipped (not counted, doesn't stop the walk).
- air / water -> stop, sample is valid. Seagrass, kelp, snow layer, grass etc. also count as "open" (edit `STOP`).
- any other block (planks, logs, stairs, stone, lava...) -> sample **discarded**, reason logged.
So ice-over-water, villages above the chest, and ravines with sand on top no longer pollute the data.
Valid samples go to `combined.csv`; discards (with the offending block) to `combined_discarded.csv`.

## Setup
1. Official **1.16.1** `server.jar` in `server/`, run once, set `eula=true`. `chain` rewrites `server/server.properties`
   itself (seed, world name, RCON) and starts/stops the server for every seed (needs `java` on PATH).
2. Biome filter: Linux x86-64 binary included; otherwise `python bt.py build` (gcc/clang; Windows: MSYS2 or WSL).

## Run
```
python bt.py selftest && python tests/test_chain.py     # offline checks (no Minecraft needed)
python bt.py chain --test                               # small test: ~500 valid points, 5 seeds x 100 chests
python bt.py chain --target 10000 --per-seed 500        # full run (~25 seeds)
```
Negative seeds on the command line need `=`: `--seeds=-123,456`.
Output folder (`out/test` or `out/chain`): `seeds.txt`, `seed_<seed>.csv` per seed, `combined.csv`,
`combined_discarded.csv`, `histogram.png`, plus a text histogram.

- **Resumable**: finished seeds are skipped; Ctrl+C then rerun the same command. Seed list is reproducible
  (`--rng-seed`, default 2024) or explicit (`--seeds=`).
- Each seed uses its nearest `--per-seed` chests (default radius 800 chunks; ~490 chests exist within radius 600 on
  average). Smaller radius / more seeds: e.g. `--per-seed 200 --max-seeds 80`. Each seed costs one server start (~1 min).
- Worlds are deleted after analysis (`--keep-worlds` to keep). Use `--java-args "-Xmx12G"` for more RAM, `--batch` for parallelism.
- `--target` counts **valid** samples, so discards are made up by extra seeds (`--max-seeds`, default 60).

Single-seed tools still exist: `candidates | generate | analyze --seed S --world server/world`.
Cubiomes (MIT, Cubitect) is bundled in `tools/cubiomes`.
