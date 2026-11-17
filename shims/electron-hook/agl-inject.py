#!/usr/bin/env python3
"""agl-inject.py WS_URL HOOK_PATH

Connects to the Node inspector of an Electron main process (ws://127.0.0.1:PORT/UUID),
requires HOOK_PATH there (it clears the window background and injects the glass CSS).
Retries while Node is still starting, then waits for the hook to install (it answers "ok true");
exits 1 when it never does. Then it closes the inspector (user decision "Auto, port closed after"):
Node's inspector.close(), armed on a timer so it runs after this client hangs up (also after a
failed install). A second connect then checks the port.
When it is still open (an Electron that cannot close it), it stays loopback only on its random
port, and the target UUID stays unlisted. Stdlib only, loopback only. The app is started with --inspect-publish-uid=stderr, so the
inspector does not list its target over HTTP: a client needs the random session UUID that only the
wrapper reads from the app's stderr.
"""
import base64, json, os, socket, struct, sys, time


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


TRIES, PAUSE = 50, 0.2    # about 10 s


def main():
    url, hook = sys.argv[1], sys.argv[2]
    ws = WS(url)
    h = json.dumps(hook)
    done = "'ok '+!!global.__aglInstalled"
    load = "(()=>{require(%s);return %s})()" % (h, done)
    # the url is printed before Node has finished its bootstrap: a require() then throws inside
    # node:internal (TypeError: testEnabled is not a function); try again from a clean cache
    again = ("(()=>{try{delete require.cache[require.resolve(%s)]}catch(e){}require(%s);return %s})()"
             % (h, h, done))
    js, out, ok = load, '', False
    for _ in range(TRIES):
        r = ws.call('Runtime.evaluate', {'expression': js, 'includeCommandLineAPI': True,
                                         'returnByValue': True})
        res = r.get('result', r)
        out = json.dumps(res)[:500]
        val = res.get('result', {}) if isinstance(res, dict) else {}
        if 'error' in r or 'exceptionDetails' in res or val.get('subtype') == 'error':
            js = again if js != done else done
        elif val.get('value') == 'ok true':
            ok = True
            break
        else:
            js = done          # loaded: the hook waits for electron.app by itself
        time.sleep(PAUSE)
    print(out)
    # inspector.close() waits for every session to end: armed now, run once this one is gone
    ws.call('Runtime.evaluate', {'expression': CLOSE, 'includeCommandLineAPI': True,
                                 'returnByValue': True})
    try:
        ws.s.close()
    except OSError:
        pass
    port = int(url[5:].split('/', 1)[0].split(':')[1])
    if closed(port):
        print('inspector closed')
    else:
        print('agl-inject: inspector still open on 127.0.0.1:%d (loopback only)' % port,
              file=sys.stderr)
    return 0 if ok else 1


CLOSE = ("(()=>{const i=require('inspector');"
         "setTimeout(()=>{try{i.close()}catch(e){}},200);return 'armed'})()")


def closed(port, wait=3.0):
    """True once 127.0.0.1:port refuses a connect (polled up to wait s)."""
    import time
    end = time.monotonic() + wait
    while True:
        try:
            socket.create_connection(('127.0.0.1', port), timeout=0.5).close()
        except ConnectionRefusedError:
            return True
        except OSError:
            pass    # a timeout is not a closed port
        if time.monotonic() >= end:
            return False
        time.sleep(0.2)


sys.exit(main())
