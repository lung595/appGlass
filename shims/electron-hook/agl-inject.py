#!/usr/bin/env python3
"""agl-inject.py WS_URL HOOK_PATH

Connects to the Node inspector of an Electron main process (ws://127.0.0.1:PORT/UUID),
requires HOOK_PATH there (it clears the window background and injects the glass CSS),
Stdlib only, loopback only. The app is started with --inspect-publish-uid=stderr, so the
inspector does not list its target over HTTP: a client needs the random session UUID that only the
wrapper reads from the app's stderr.
"""
import base64, json, os, socket, struct, sys


class WS:
    def __init__(self, url):
        if not url.startswith('ws://127.0.0.1:'):
            raise SystemExit('refusing non-loopback inspector url: ' + url)
        hp, path = url[5:].split('/', 1)
        host, port = hp.split(':')
        self.s = socket.create_connection((host, int(port)), timeout=15)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f'GET /{path} HTTP/1.1\r\nHost: {hp}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                        f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            d = self.s.recv(4096)
            if not d:
                raise SystemExit('inspector closed during handshake')
            buf += d
        head, self.rest = buf.split(b'\r\n\r\n', 1)
        if b' 101 ' not in head.split(b'\r\n')[0]:
            raise SystemExit('ws handshake failed')
        self.id = 0

    def _recvn(self, n):
        while len(self.rest) < n:
            d = self.s.recv(65536)
            if not d:
                raise EOFError
            self.rest += d
        r, self.rest = self.rest[:n], self.rest[n:]
        return r

    def send(self, obj):
        data = json.dumps(obj).encode()
        m = os.urandom(4)
        n = len(data)
        hdr = bytes([0x81])
        if n < 126:
            hdr += bytes([0x80 | n])
        elif n < 65536:
            hdr += bytes([0x80 | 126]) + struct.pack('>H', n)
        else:
            hdr += bytes([0x80 | 127]) + struct.pack('>Q', n)
        self.s.sendall(hdr + m + bytes(b ^ m[i % 4] for i, b in enumerate(data)))

    def recv(self):
        msg = b''
        while True:
            b0, b1 = self._recvn(2)
            n = b1 & 0x7f
            if n == 126:
                n = struct.unpack('>H', self._recvn(2))[0]
            elif n == 127:
                n = struct.unpack('>Q', self._recvn(8))[0]
            msg += self._recvn(n)
            if b0 & 0x80:
                break
        return json.loads(msg)

    def call(self, method, params=None):
        self.id += 1
        i = self.id
        self.send({'id': i, 'method': method, 'params': params or {}})
        while True:
            r = self.recv()
            if r.get('id') == i:
                return r


def main():
    url, hook = sys.argv[1], sys.argv[2]
    ws = WS(url)
    js = "(()=>{require(" + json.dumps(hook) + ");return 'ok '+!!global.__aglInstalled})()"
    r = ws.call('Runtime.evaluate', {'expression': js, 'includeCommandLineAPI': True, 'returnByValue': True})
    print(json.dumps(r.get('result', r))[:500])
    try:
        ws.s.close()
    except OSError:
        pass


main()
