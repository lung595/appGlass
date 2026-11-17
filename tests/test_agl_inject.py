"""agl-inject.py against a fake Node inspector: the wrapper reads the inspector
url as soon as it is printed, which can be before Node has finished its
bootstrap (require() then throws inside node:internal), so the injector
retries until the hook answers "ok true", then closes the inspector (one
more evaluate, also after a failed install)."""

import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import threading
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INJECT = os.path.join(REPO, "shims", "electron-hook", "agl-inject.py")
EARLY = {"result": {"type": "object", "subtype": "error", "className": "TypeError",
                    "description": "TypeError: testEnabled is not a function"},
         "exceptionDetails": {"text": "Uncaught"}}


def value(v):
    return {"result": {"type": "string", "value": v}}


class Inspector(threading.Thread):
    """Answers each Runtime.evaluate with the next scripted result (the last one repeats)."""

    def __init__(self, answers):
        super().__init__(daemon=True)
        self.answers, self.calls = list(answers), []
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.srv.settimeout(20)
        self.url = "ws://127.0.0.1:%d/0000-aaaa" % self.srv.getsockname()[1]

    def frame(self, c):
        def n(k):
            b = b""
            while len(b) < k:
                d = c.recv(k - len(b))
                if not d:
                    raise EOFError
                b += d
            return b
        b0, b1 = n(2)
        size = b1 & 0x7f
        if size == 126:
            size = struct.unpack(">H", n(2))[0]
        elif size == 127:
            size = struct.unpack(">Q", n(8))[0]
        m = n(4)
        return bytes(x ^ m[i % 4] for i, x in enumerate(n(size)))

    def send(self, c, obj):
        data = json.dumps(obj).encode()
        hdr = bytes([0x81]) + (bytes([len(data)]) if len(data) < 126
                               else bytes([126]) + struct.pack(">H", len(data)))
        c.sendall(hdr + data)

    def run(self):
        try:
            c, _ = self.srv.accept()
            head = b""
            while b"\r\n\r\n" not in head:
                head += c.recv(4096)
            key = [ln.split(b":", 1)[1].strip() for ln in head.split(b"\r\n")
                   if ln.lower().startswith(b"sec-websocket-key")][0]
            acc = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
                                   .digest()).decode()
            c.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                       "Connection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n" % acc).encode())
            while True:
                msg = json.loads(self.frame(c))
                self.calls.append(msg["params"].get("expression", ""))
                ans = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
                self.send(c, {"id": msg["id"], "result": ans})
        except (EOFError, OSError, ValueError):
            pass


def hook_calls(calls):
    """The evaluate calls before the inspector close (the last one)."""
    return [c for c in calls if "require('inspector')" not in c]


def inject(answers):
    srv = Inspector(answers)
    srv.start()
    r = subprocess.run(["python3", "-I", INJECT, srv.url, "/x/agl-hook.js"],
                       capture_output=True, text=True, timeout=60)
    srv.join(5)
    return r, srv.calls


class AglInject(unittest.TestCase):
    def test_installed_at_once(self):
        r, calls = inject([value("ok true")])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ok true", r.stdout)
        self.assertEqual(len(hook_calls(calls)), 1)
        self.assertIn('require("/x/agl-hook.js")', calls[0])
        self.assertIn("require('inspector')", calls[-1])

    def test_retries_while_node_is_still_starting(self):
        r, calls = inject([EARLY, EARLY, value("ok true")])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ok true", r.stdout)
        self.assertEqual(len(hook_calls(calls)), 3)
        self.assertEqual(len(calls), 4)
        # a require that threw must not leave a half-loaded module in the cache
        self.assertIn("require.cache", calls[1])

    def test_waits_for_electron_app(self):
        # the hook polls for electron.app itself: the injector waits for it to install
        r, calls = inject([value("ok false"), value("ok false"), value("ok true")])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ok true", r.stdout)
        self.assertEqual(sum('require("/x/agl-hook.js")' in c for c in calls), 1)

    def test_gives_up_with_an_error(self):
        r, calls = inject([EARLY])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("testEnabled", r.stdout + r.stderr)
        self.assertIn("require('inspector')", calls[-1])     # closed after a failure too


if __name__ == "__main__":
    unittest.main()
