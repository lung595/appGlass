#!/usr/bin/env python3
"""Drive a test Obsidian over the DevTools protocol (stdlib only, e2e only).

    obsidian_cdp.py serve <dir> -- <obsidian> [args...]
        start Obsidian with --remote-debugging-port on 127.0.0.1 and answer
        requests dropped into <dir>. Meant to run inside a private network
        namespace (bwrap --unshare-net), so nothing outside can reach the port.
    obsidian_cdp.py call <dir> <js> [timeout]
        run <js> as the body of an async function in the vault window and
        print the JSON of what it returns.
    obsidian_cdp.py call <dir> QUIT
        stop Obsidian and the server.

Requests are files: <n>.req (JS text) -> <n>.resp ({"ok": bool, "value": ...}).
"""

import base64
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time
import urllib.request

PORT = 9222


class WS:
    def __init__(self, url):
        rest = url.split("://", 1)[1]
        hostport, path = rest.split("/", 1)
        host, port = hostport.rsplit(":", 1)
        self.s = socket.create_connection((host, int(port)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\n"
                        "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
                        "Sec-WebSocket-Version: 13\r\n\r\n" % (path, hostport, key)).encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            c = self.s.recv(4096)
            if not c:
                raise EOFError("handshake")
            self.buf += c
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise OSError("websocket refused: %r" % head[:200])
        self.n = 0

    def send(self, obj):
        data = json.dumps(obj).encode()
        n = len(data)
        if n < 126:
            hdr = bytes([0x81, 0x80 | n])
        elif n < 65536:
            hdr = bytes([0x81, 0x80 | 126]) + struct.pack(">H", n)
        else:
            hdr = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", n)
        m = os.urandom(4)
        self.s.sendall(hdr + m + bytes(b ^ m[i % 4] for i, b in enumerate(data)))

    def _need(self, k):
        while len(self.buf) < k:
            c = self.s.recv(65536)
            if not c:
                raise EOFError("websocket closed")
            self.buf += c

    def recv(self):
        msg = b""
        while True:
            self._need(2)
            fin, op, n = self.buf[0] & 0x80, self.buf[0] & 0x0f, self.buf[1] & 0x7f
            off = 2
            if n == 126:
                self._need(4)
                n = struct.unpack(">H", self.buf[2:4])[0]
                off = 4
            elif n == 127:
                self._need(10)
                n = struct.unpack(">Q", self.buf[2:10])[0]
                off = 10
            self._need(off + n)
            payload, self.buf = self.buf[off:off + n], self.buf[off + n:]
            if op == 8:
                raise EOFError("websocket closed")
            if op in (0, 1, 2):
                msg += payload
                if fin:
                    return json.loads(msg)

    def call(self, method, params=None):
        self.n += 1
        self.send({"id": self.n, "method": method, "params": params or {}})
        while True:
            r = self.recv()
            if r.get("id") == self.n:
                return r

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


def page_url():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:%d/json" % PORT, timeout=5) as f:
        targets = json.load(f)
    pages = [t for t in targets if t.get("type") == "page"
             and "index.html" in t.get("url", "") and t.get("webSocketDebuggerUrl")]
    return pages[0]["webSocketDebuggerUrl"] if pages else None


def evaluate(js):
    url = page_url()
    if not url:
        return {"ok": False, "value": "no vault window yet"}
    ws = WS(url)
    try:
        # each request is a function body: its own scope, `return` gives the value
        expr = "(async () => {\n%s\n})()" % js
        r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                         "awaitPromise": True})
    finally:
        ws.close()
    res = r.get("result", {})
    if "exceptionDetails" in res:
        return {"ok": False, "value": res["exceptionDetails"].get("text", "exception") + ": "
                + str(res["exceptionDetails"].get("exception", {}).get("description", ""))}
    if "error" in r:
        return {"ok": False, "value": r["error"]}
    return {"ok": True, "value": res.get("result", {}).get("value")}


def serve(d, cmd):
    os.makedirs(d, exist_ok=True)
    child = subprocess.Popen(cmd + ["--remote-debugging-address=127.0.0.1",
                                    "--remote-debugging-port=%d" % PORT])

    def stop(*_):
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()

    signal.signal(signal.SIGTERM, lambda *a: (stop(), sys.exit(0)))
    while child.poll() is None:
        reqs = sorted(f for f in os.listdir(d) if f.endswith(".req"))
        for f in reqs:
            p = os.path.join(d, f)
            with open(p) as fh:
                js = fh.read()
            os.remove(p)
            if js.strip() == "QUIT":
                stop()
                out = {"ok": True, "value": child.returncode}
            else:
                try:
                    out = evaluate(js)
                except Exception as ex:  # report, keep serving
                    out = {"ok": False, "value": "%s: %s" % (type(ex).__name__, ex)}
            tmp = os.path.join(d, f[:-4] + ".tmp")
            with open(tmp, "w") as fh:
                json.dump(out, fh)
            os.rename(tmp, os.path.join(d, f[:-4] + ".resp"))
            if js.strip() == "QUIT":
                return 0
        time.sleep(0.1)
    return child.returncode or 0


def call(d, js, timeout):
    n = "%d-%d" % (time.time() * 1000, os.getpid())
    tmp = os.path.join(d, n + ".tmpreq")
    with open(tmp, "w") as fh:
        fh.write(js)
    os.rename(tmp, os.path.join(d, n + ".req"))
    resp = os.path.join(d, n + ".resp")
    end = time.time() + timeout
    while time.time() < end:
        if os.path.exists(resp):
            with open(resp) as fh:
                out = json.load(fh)
            os.remove(resp)
            print(json.dumps(out["value"]))
            return 0 if out["ok"] else 1
        time.sleep(0.1)
    print(json.dumps("timeout"))
    return 1


def main(argv):
    if len(argv) >= 4 and argv[1] == "serve" and argv[3] == "--":
        return serve(argv[2], argv[4:])
    if len(argv) >= 4 and argv[1] == "call":
        return call(argv[2], argv[3], float(argv[4]) if len(argv) > 4 else 30)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
