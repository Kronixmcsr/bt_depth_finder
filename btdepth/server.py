"""Start / stop a Minecraft server process and edit server.properties."""
import os
import shutil
import socket
import subprocess
import threading
import time
from collections import deque

from .rcon import Rcon


def write_properties(path, updates):
    lines = open(path).read().splitlines() if os.path.exists(path) else []
    seen = set()
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0].strip()
        if k in updates and not line.lstrip().startswith("#"):
            lines[i] = "%s=%s" % (k, updates[k]); seen.add(k)
    lines += ["%s=%s" % (k, v) for k, v in updates.items() if k not in seen]
    open(path, "w").write("\n".join(lines) + "\n")


def check_eula(server_dir):
    p = os.path.join(server_dir, "eula.txt")
    if not os.path.exists(p) or "eula=true" not in open(p).read().replace(" ", ""):
        raise SystemExit("Accept the EULA first: set eula=true in %s (run server.jar once to create it)." % p)


def port_in_use(host, port):
    try:
        socket.create_connection((host, port), timeout=1).close()
        return True
    except OSError:
        return False


def wait_ports_free(host, ports, timeout=30):
    """True once nothing listens on any of `ports` (gives a previous server time to shut down)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not any(port_in_use(host, p) for p in ports):
            return True
        time.sleep(1)
    return False


HINT = ("\n\nAnother Minecraft server is probably still running in this folder (or a stale java.exe is holding "
        "its files). Close any server window, end java.exe in Task Manager, then rerun the same command "
        "(finished seeds are kept).")


class Server:
    def __init__(self, server_dir, cmd, ready_timeout=600):
        self.dir, self.cmd, self.ready_timeout = server_dir, cmd, ready_timeout
        self.proc = None
        self.tail = deque(maxlen=30)
        self.ready = threading.Event()

    def _reader(self):
        for line in self.proc.stdout:
            self.tail.append(line.rstrip())
            if "Done (" in line:
                self.ready.set()

    def start(self):
        self.ready.clear()
        self.proc = subprocess.Popen(self.cmd, cwd=self.dir, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace")
        threading.Thread(target=self._reader, daemon=True).start()
        t0 = time.time()
        while not self.ready.wait(0.5):
            if self.proc.poll() is not None:
                log = "\n".join(self.tail)
                locked = any(w in log.lower() for w in ("latest.log", "locked", "verrouill", "in use", "utilis", "bindexception"))
                raise RuntimeError("server exited during startup:\n" + log + (HINT if locked else ""))
            if time.time() - t0 > self.ready_timeout:
                self.kill()
                raise RuntimeError("server did not become ready in time:\n" + "\n".join(self.tail))

    def connect_rcon(self, host, port, password, tries=60, timeout=600):
        for _ in range(tries):
            try:
                return Rcon(host, port, password, timeout=timeout)
            except OSError:
                time.sleep(0.5)
        raise RuntimeError("could not connect to RCON on %s:%d" % (host, port))

    def stop(self, rc=None, timeout=180):
        if self.proc is None:
            return
        graceful = rc is not None
        if rc is not None:
            try:
                rc.sock.settimeout(120)
                rc.command("save-all flush", retries=0)
                rc.command("stop", retries=0)
            except Exception:
                graceful = False                 # server unresponsive: don't wait long for it
        try:
            self.proc.wait(timeout if graceful else 15)
        except subprocess.TimeoutExpired:
            self.kill()
        self.proc = None

    def kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self.proc = None


def default_cmd(java_args):
    java = shutil.which("java")
    if not java:
        raise SystemExit("java not found on PATH.")
    return [java] + java_args.split() + ["-jar", "server.jar", "nogui"]
