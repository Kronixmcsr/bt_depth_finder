"""End-to-end test of `bt.py chain` against tests/fake_server.py (no Minecraft needed)."""
import csv, os, shutil, subprocess, sys, tempfile
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
work = tempfile.mkdtemp()
os.makedirs(work + "/server")
open(work + "/server/eula.txt", "w").write("eula=true\n")
seeds = "-6240136574013258961,8123456789012345678,4242424242,-99,7"
cmd = [sys.executable, root + "/bt.py", "chain", "--target", "40", "--per-seed", "20", "--radius", "500",
       "--seeds=" + seeds, "--server-dir", work + "/server", "--out", work + "/out", "--rcon-port", "25599",
       "--poll", "0.05", "--rcon-timeout", "1", "--server-cmd", '"%s" "%s"' % (sys.executable, os.path.join(root, "tests", "fake_server.py"))]
env = dict(os.environ, FAKE_STALL="1")      # every fake server stalls one reply past the 1 s timeout
r = subprocess.run(cmd, capture_output=True, text=True, cwd=root, env=env)
print(r.stdout[-1800:], r.stderr[-800:])
if r.returncode != 0:
    print("CHAIN TEST FAIL: bt.py chain exited with", r.returncode); sys.exit(1)
rows = list(csv.DictReader(open(work + "/out/combined.csv")))
disc = list(csv.DictReader(open(work + "/out/combined_discarded.csv")))
depths = sorted(set(int(x["depth"]) for x in rows))
reasons = {d["reason"] for d in disc}
ok = ("reconnecting" in r.stdout and r.returncode == 0 and len(rows) >= 40 and depths == [0, 1, 2, 4] and
      reasons == {"minecraft:oak_planks"} and
      not [d for d in os.listdir(work + "/server") if d.startswith("world_")] and
      any(int(x["gravel"]) == 1 for x in rows))
# resume: second run must reuse finished seeds and not start any server
r2 = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
ok &= r2.returncode == 0 and "already done" in r2.stdout
print("valid", len(rows), "discarded", len(disc), "depths", depths, "reasons", reasons)
print("CHAIN TEST", "OK" if ok else "FAIL")
shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if ok else 1)
