import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from fixtures.shimcase import ShimCase

L = ".local/lib/appglass/feishin/"


class Feishin(ShimCase, unittest.TestCase):
    FAMILY = "feishin"
    KEY = "org.jeffvli.feishin"
    FLATPAK = KEY
    SYSTEM = "org.jeffvli.feishin.desktop"
    LAUNCHER = ".local/share/applications/org.jeffvli.feishin.desktop"
    FILES = {L + "agl-hook.js": 0o644, L + "agl-inject.py": 0o644,
             L + "feishin-glass.css.tmpl": 0o644, L + "feishin-glass.css": 0o644,
             ".local/bin/appglass-feishin": 0o755}
    CSS = L + "feishin-glass.css"

    def test_inspector_local_only(self):
        self.enable()
        self.apply()
        w = self.w.sb.read(self.w.user(".local/bin/appglass-feishin"))
        self.assertIn("--inspect=127.0.0.1:0", w)
        self.assertIn("--inspect-publish-uid=stderr", w)
        self.assertIn("mkdir -m 700", w)
        text = self.w.sb.read(self.w.user(self.LAUNCHER))
        self.assertEqual(re.findall(r"(?m)^Exec=(.*)$", text),
                         [self.w.user(".local/bin/appglass-feishin")])

    def test_css_levels_raw(self):
        self.enable()
        self.w.sb.set_level(0.7)
        self.apply()
        self.assertIn("0.7", self.w.sb.read(self.w.user(self.CSS)))

    FAKE = """#!/bin/sh
echo "$*" >> "%s"
[ "$1" = ps ] && exit 0
case "$*" in *--inspect*) echo "Debugger listening on ws://127.0.0.1:9/0000-aaaa" >&2; sleep 1 ;; esac
exit 0
"""

    def wrapper(self, rt):
        tmp = tempfile.mkdtemp(prefix="appglass-fp-")
        self.addCleanup(shutil.rmtree, tmp, True)
        calls, fp = os.path.join(tmp, "calls"), os.path.join(tmp, "flatpak")
        with open(fp, "w") as f:
            f.write(self.FAKE % calls)
        os.chmod(fp, 0o755)
        env = dict(self.w.sb.env, APPGLASS_FLATPAK=fp, XDG_RUNTIME_DIR=rt)
        r = subprocess.run([self.w.user(".local/bin/appglass-feishin")], env=env,
                           capture_output=True, text=True, timeout=60)
        with open(calls) as f:
            return r, f.read().splitlines()

    def test_log_deleted_whatever_the_injection(self):
        self.enable()
        self.apply()
        rt = self.w.sb.path("run")
        os.makedirs(rt, mode=0o700)
        r, calls = self.wrapper(rt)
        self.assertIn("injection failed", r.stderr)       # nothing listens on :9
        self.assertTrue(any("--inspect=127.0.0.1:0" in c for c in calls), calls)
        self.assertEqual(os.listdir(os.path.join(rt, "appglass")), [])
        self.assertEqual(os.stat(os.path.join(rt, "appglass")).st_mode & 0o777, 0o700)

    def test_css_takes_only_hex_colours(self):
        self.enable()
        self.apply()
        p = os.path.join(self.w.sb.cache, "dms", "dms-colors.json")
        d = json.loads(self.w.sb.read(p))
        d["mode"] = "dark"
        d["colors"]["dark"]["surface"] = "#1/;w x"
        with open(p, "w") as f:
            json.dump(d, f)
        rt = self.w.sb.path("run")
        os.makedirs(rt, mode=0o700)
        self.wrapper(rt)
        css = self.w.sb.read(self.w.user(self.CSS))
        self.assertIn("#root { background: rgba(16, 20, 24, ", css)   # 101418, the fallback
        self.assertFalse(os.path.exists(os.path.join(self.w.sb.root, " x")))

    def test_no_private_runtime_dir_no_inspector(self):
        self.enable()
        self.apply()
        rt = self.w.sb.path("run-shared")
        os.makedirs(rt)
        os.chmod(rt, 0o777)
        for d in (rt, ""):
            r, calls = self.wrapper(d)
            self.assertFalse(any("--inspect" in c for c in calls), calls)
            self.assertTrue(any(c.startswith("run ") for c in calls), calls)
        self.assertEqual(os.listdir(rt), [])


INJECT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "shims", "electron-hook", "agl-inject.py")


def crc32c(data):
    """The test's own CRC-32C (Castagnoli), bit by bit."""
    crc = 0xffffffff
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82f63b78 if crc & 1 else 0)
    return crc ^ 0xffffffff


def varint(d, i):
    n = shift = 0
    while True:
        b = d[i]
        i += 1
        n |= (b & 0x7f) << shift
        shift += 7
        if not b & 0x80:
            return n, i


def read_log(d):
    """{key: value} of a leveldb log (one block of FULL records), each
    record's masked CRC checked."""
    import struct
    out, i = {}, 0
    while i + 7 <= len(d):
        crc, n, t = struct.unpack("<IHB", d[i:i + 7])
        body = d[i + 7:i + 7 + n]
        c = crc32c(bytes([t]) + body)
        assert crc == ((((c >> 15) | (c << 17)) + 0xa282ead8) & 0xffffffff), "crc"
        assert t == 1, "a FULL record"
        seq, count = struct.unpack("<QI", body[:12])
        assert seq >= 1
        j = 12
        for _ in range(count):
            assert body[j] == 1, "a put"
            kl, j = varint(body, j + 1)
            k = body[j:j + kl]
            vl, j = varint(body, j + kl)
            out[k] = body[j:j + vl]
            j += vl
        i += 7 + n
    return out


def asar(path, files):
    """A minimal asar archive with files {name: bytes} at its top."""
    import struct
    hdr, off, blob = {"files": {}}, 0, b""
    for n, data in files.items():
        hdr["files"][n] = {"size": len(data), "offset": str(off)}
        off += len(data)
        blob += data
    j = json.dumps(hdr).encode()
    pad = (4 - len(j) % 4) % 4
    pickle = struct.pack("<II", 4 + len(j) + pad, len(j)) + j + b"\0" * pad
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(struct.pack("<II", 4, len(pickle)) + pickle + blob)


class FirstRun(ShimCase, unittest.TestCase):
    """E4: the hidden check starts Feishin in a throwaway home, where its
    first run opens the release notes over the window 2 s after the page
    loads (localStorage "version" is not this version): the shot would read
    the dialog. The check seeds Feishin's Local Storage (a leveldb log
    Chromium replays) with the version it ships, read from its app.asar;
    without a version it is unverifiable, not a fail (an explicit on stays)."""
    FAMILY = "feishin"
    KEY = "org.jeffvli.feishin"
    FLATPAK = KEY
    SYSTEM = "org.jeffvli.feishin.desktop"
    LAUNCHER = Feishin.LAUNCHER
    FILES = Feishin.FILES
    LS = ".var/app/org.jeffvli.feishin/config/feishin/Local Storage/leveldb/000003.log"

    def files(self):
        return self.w.sb.path("flatpak", "app", self.KEY, "current", "active", "files")

    def ship(self, version):
        asar(os.path.join(self.files(), "main", "resources", "app.asar"),
             {"package.json": json.dumps({"name": "feishin", "version": version}).encode(),
              "x.js": b"0"})

    def app(self):
        from appglass import core
        return core.App(self.w.sb.env, quiet=True)

    def test_crc32c_of_the_test(self):
        self.assertEqual(crc32c(b"123456789"), 0xe3069283)

    def test_the_seed_holds_the_shipped_version(self):
        from appglass.families import feishin
        self.ship("9.8.7")
        seed = feishin.verify_seed(self.app().env)
        self.assertEqual(list(seed), [self.LS])
        kv = read_log(seed[self.LS])
        self.assertEqual(kv[b"VERSION"], b"1")
        self.assertEqual(kv[b"_file://\x00\x01version"], b'\x01"9.8.7"')
        self.assertIn(b"META:file://", kv)

    def test_no_version_no_seed(self):
        from appglass.families import feishin
        self.assertIsNone(feishin.verify_seed(self.app().env))
        self.ship("")
        self.assertIsNone(feishin.verify_seed(self.app().env))

    def test_the_staged_home_holds_the_seed(self):
        from appglass import engine, verify
        self.ship("1.17.0")
        self.enable()
        self.apply()
        app = self.app()
        rec = engine.record_for(app, self.KEY)
        run = self.w.sb.path("run")
        home = verify.stage(app, rec, run)
        self.assertIsNone(verify.seed(app, rec, home))
        with open(os.path.join(home, self.LS), "rb") as f:
            self.assertEqual(read_log(f.read())[b"_file://\x00\x01version"], b'\x01"1.17.0"')

    def test_without_a_seed_the_check_is_unverifiable(self):
        from appglass import engine, verify
        self.enable()
        self.apply()
        app = self.app()
        rec = engine.record_for(app, self.KEY)
        home = verify.stage(app, rec, self.w.sb.path("run"))
        why = verify.seed(app, rec, home)
        self.assertIn("first run", why)
        self.assertFalse(os.path.exists(os.path.join(home, ".var")))

    def test_an_app_without_a_seed_hook_needs_none(self):
        from appglass import verify
        app = self.app()
        self.assertIsNone(verify.seed(app, {"key": "gedit"}, self.w.sb.path("h")))


class FakeInspector:
    """A loopback WebSocket that answers Runtime.evaluate like Node's
    inspector. close_on_arm: stop listening once the close is armed (Node's
    inspector.close()), else keep the port open (it cannot close)."""

    def __init__(self, close_on_arm):
        import socket
        import threading
        self.close_on_arm = close_on_arm
        self.exprs = []
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.port = self.srv.getsockname()[1]
        self.url = "ws://127.0.0.1:%d/0000-aaaa" % self.port
        self.t = threading.Thread(target=self.serve, daemon=True)
        self.t.start()

    def frame(self, c):
        import struct
        b0, b1 = c.recv(2)
        n = b1 & 0x7f
        if n == 126:
            n = struct.unpack(">H", c.recv(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", c.recv(8))[0]
        m = c.recv(4)
        data = b""
        while len(data) < n:
            data += c.recv(n - len(data))
        return json.loads(bytes(b ^ m[i % 4] for i, b in enumerate(data)))

    def send(self, c, obj):
        import struct
        d = json.dumps(obj).encode()
        hdr = bytes([0x81]) + (bytes([len(d)]) if len(d) < 126 else bytes([126]) + struct.pack(">H", len(d)))
        c.sendall(hdr + d)

    def serve(self):
        try:
            c, _ = self.srv.accept()
        except OSError:
            return
        self.session(c)
        while True:             # still listening: later connects are taken and dropped
            try:
                self.srv.accept()[0].close()
            except OSError:
                return

    def session(self, c):
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += c.recv(4096)
        c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
        try:
            while True:
                msg = self.frame(c)
                expr = msg["params"]["expression"]
                self.exprs.append(expr)
                ans = "armed" if "require('inspector')" in expr else "ok true"
                self.send(c, {"id": msg["id"], "result": {"result": {"type": "string", "value": ans}}})
                if "inspector" in expr and ".close()" in expr and self.close_on_arm:
                    self.srv.close()
        except (OSError, ValueError, KeyError):
            pass
        finally:
            c.close()

    def stop(self):
        try:
            self.srv.close()
        except OSError:
            pass


class InspectorClosed(unittest.TestCase):
    """User decision "Auto, port closed after": inject, then close the
    inspector; when it cannot close, it stays loopback only, random port."""

    def run_inject(self, close_on_arm):
        fake = FakeInspector(close_on_arm)
        self.addCleanup(fake.stop)
        r = subprocess.run(["python3", "-I", INJECT, fake.url, "/x/agl-hook.js"],
                           capture_output=True, text=True, timeout=20)
        return fake, r

    def test_port_closed_after_the_injection(self):
        fake, r = self.run_inject(True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("/x/agl-hook.js", fake.exprs[0])
        self.assertIn("require('inspector')", fake.exprs[-1])
        self.assertIn("inspector closed", r.stdout)

    def test_port_that_stays_open_is_said(self):
        fake, r = self.run_inject(False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("inspector still open on 127.0.0.1:%d" % fake.port, r.stderr)


if __name__ == "__main__":
    unittest.main()
