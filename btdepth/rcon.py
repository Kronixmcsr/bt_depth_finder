"""Tiny RCON client (Source RCON protocol, as used by Minecraft) with reconnect + retry.

Minecraft runs RCON commands on its main thread, so a busy server (e.g. a big `save-all flush`)
can take minutes to answer. Every command we send is safe to repeat, so on a timeout or dropped
connection we open a fresh socket and send it again."""
import socket
import struct
import time


class Rcon:
    def __init__(self, host, port, password, timeout=600, retries=4):
        self.host, self.port, self.password = host, port, password
        self.timeout, self.retries = timeout, retries
        self.sock = None
        self._id = 0
        self._connect()

    def _connect(self):
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        rid, _ = self._send(3, self.password)
        if rid == -1:
            self.close()
            raise PermissionError("RCON login failed (wrong password?)")

    def _send(self, ptype, payload):
        if self.sock is None:
            raise ConnectionError("RCON not connected")
        self._id += 1
        body = struct.pack("<ii", self._id, ptype) + payload.encode() + b"\x00\x00"
        self.sock.sendall(struct.pack("<i", len(body)) + body)
        while True:                              # skip stale replies from an earlier timed-out command
            rid, text = self._recv()
            if rid == -1 or rid == self._id:
                return rid, text

    def _recv(self):
        (length,) = struct.unpack("<i", self._read(4))
        data = self._read(length)
        rid, _t = struct.unpack("<ii", data[:8])
        return rid, data[8:-2].decode(errors="replace")

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("RCON connection closed")
            buf += chunk
        return buf

    def command(self, cmd, retries=None):
        n = self.retries if retries is None else retries
        for attempt in range(n + 1):
            try:
                return self._send(2, cmd)[1]
            except OSError as e:                 # includes timeouts and ConnectionError
                if attempt == n:
                    raise
                print("  RCON %s on '%s', reconnecting (%d/%d)" % (type(e).__name__, cmd.split()[0], attempt + 1, n))
                time.sleep(min(2 * (attempt + 1), 30))
                try:
                    self._connect()
                except OSError:
                    pass                         # next attempt fails fast and retries again

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
