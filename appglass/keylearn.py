"""keylearn: ck-shim colour keys from one opaque capture (stdlib only).

For apps that paint their own opaque background (Flutter, custom GL
renderers), the ck-shim keys the background colours to the glass levels.
Hand-made key tables go stale with every theme, so the keys are learned
from one opaque capture of the window (engine spec 1.6):

1. the RGB colour of each cell of a 4 px grid;
2. a colour counts only by its large connected areas: grid cells whose four
   neighbours have the same colour (interior cells), in 4-connected
   components of at least MIN_COMPONENT cells;
3. at most 3 keys, each covering at least 2 % of the window that way;
4. the text colour is rejected: a colour seen almost only at edges (under 15 %
   of its cells interior) is ink, not a surface;
5. a surface far brighter or darker than the main one (more than MAX_LUMA_GAP)
   is a highlight, a popup or another toolkit's chrome, not a key: keying it
   would fade the popups that share its colour;
6. a flat band touching a window edge (title bar, tab strip, status bar) is a
   ``bar`` key, everything else ``content``.

Learned keys are low confidence. They are kept in
``$XDG_CACHE_HOME/appglass/keys/<app>/<fingerprint>/<mode>.json`` as
``waiting`` and only ``verified()`` after a verify PASS (``confirm``). A
wrong key fails safe: an exact-match key that misses leaves the window
opaque, and text never fades.

    python3 -m appglass.keylearn shot.png [--content 0.60 --bar 0.65]
"""

import json
import os
import re
import struct
import sys
import time
import zlib

STEP = 4
MAX_KEYS = 3
MIN_SHARE = 0.02
MIN_COMPONENT = 12
MIN_INTERIOR = 0.15
BAND_SPAN = 0.9
BAND_DEPTH = 0.2
BAND_FILL = 0.8
MAX_LUMA_GAP = 80
MODES = ("dark", "light")
_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


def read_png(path):
    """(width, height, RGBA bytes) of an 8-bit RGB or RGBA, non-interlaced PNG."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("%s: not a PNG" % path)
    pos, idat, hdr = 8, [], None
    while pos < len(data):
        n, t = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if t == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif t == b"IDAT":
            idat.append(body)
        elif t == b"IEND":
            break
    if not hdr:
        raise ValueError("%s: no IHDR" % path)
    w, h, depth, ctype, _, _, interlace = hdr
    if depth != 8 or ctype not in (2, 6) or interlace:
        raise ValueError("%s: only 8-bit RGB/RGBA non-interlaced PNGs" % path)
    bpp = 4 if ctype == 6 else 3
    raw = zlib.decompress(b"".join(idat))
    stride = w * bpp
    out = bytearray(w * h * 4)
    prev = bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        row = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                row[i] = (row[i] + a) & 255
            elif f == 2:
                row[i] = (row[i] + b) & 255
            elif f == 3:
                row[i] = (row[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                row[i] = (row[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            elif f:
                raise ValueError("%s: bad filter %d" % (path, f))
        if bpp == 4:
            out[y * w * 4:(y + 1) * w * 4] = row
        else:
            for x in range(w):
                out[4 * (y * w + x):4 * (y * w + x) + 3] = row[3 * x:3 * x + 3]
                out[4 * (y * w + x) + 3] = 255
        prev = row
    return w, h, bytes(out)


def _grid(px, w, h, step):
    o = step // 2
    xs = list(range(o, w, step))
    ys = list(range(o, h, step))
    cells = []
    for y in ys:
        base = y * w
        cells.append([px[4 * (base + x):4 * (base + x) + 3] for x in xs])
    return cells, len(xs), len(ys)


def learn(px, w, h, step=STEP, max_keys=MAX_KEYS, min_share=MIN_SHARE):
    """[{"rgb": "rrggbb", "role": "content"|"bar", "share": float}], largest first."""
    g, gw, gh = _grid(px, w, h, step)
    total = gw * gh
    if not total:
        return []
    count, inner = {}, {}
    interior = [[False] * gw for _ in range(gh)]
    for y in range(gh):
        row = g[y]
        for x in range(gw):
            c = row[x]
            count[c] = count.get(c, 0) + 1
            same = ((x == 0 or row[x - 1] == c) and (x == gw - 1 or row[x + 1] == c)
                    and (y == 0 or g[y - 1][x] == c) and (y == gh - 1 or g[y + 1][x] == c))
            if same:
                interior[y][x] = True
                inner[c] = inner.get(c, 0) + 1
    floor = min_share * total
    cands = [c for c, n in inner.items()
             if n >= floor and n >= MIN_INTERIOR * count[c]]   # text: mostly edges
    seen = [[False] * gw for _ in range(gh)]
    found = []
    for c in cands:
        comps = []
        for y0 in range(gh):
            for x0 in range(gw):
                if seen[y0][x0] or not interior[y0][x0] or g[y0][x0] != c:
                    continue
                seen[y0][x0] = True
                stack, n = [(x0, y0)], 0
                bx0 = bx1 = x0
                by0 = by1 = y0
                while stack:
                    x, y = stack.pop()
                    n += 1
                    bx0, bx1, by0, by1 = min(bx0, x), max(bx1, x), min(by0, y), max(by1, y)
                    for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                        if 0 <= nx < gw and 0 <= ny < gh and not seen[ny][nx] \
                                and interior[ny][nx] and g[ny][nx] == c:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
                if n >= MIN_COMPONENT:
                    comps.append((n, bx0, bx1, by0, by1))
        area = sum(k[0] for k in comps)
        if area < floor:
            continue
        found.append({"rgb": "%02x%02x%02x" % tuple(c), "share": round(area / total, 4),
                      "role": "bar" if _band(max(comps), gw, gh) else "content"})
    found.sort(key=lambda k: -k["share"])
    if found:
        main = _luma(found[0]["rgb"])
        found = [k for k in found if abs(_luma(k["rgb"]) - main) <= MAX_LUMA_GAP]
    return found[:max_keys]


def _luma(rgb):
    r, g, b = (int(rgb[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _band(comp, gw, gh):
    """A flat band on a window edge: spans (almost) the whole side, shallow, filled."""
    n, x0, x1, y0, y1 = comp
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    if n < BAND_FILL * bw * bh:
        return False
    # the interior cells start one cell in from a neighbour of another colour
    horiz = bw >= BAND_SPAN * (gw - 2) and bh <= BAND_DEPTH * gh and (y0 <= 1 or y1 >= gh - 2)
    vert = bh >= BAND_SPAN * (gh - 2) and bw <= BAND_DEPTH * gw and (x0 <= 1 or x1 >= gw - 2)
    return horiz or vert


def keys_arg(keys, content, bar):
    """APPGLASS_KEYS for the ck-shim: rrggbb:level,..."""
    return ",".join("%s:%.2f" % (k["rgb"], bar if k["role"] == "bar" else content) for k in keys)


def _path(env, app, fp, mode):
    for p in (app, fp):
        if not _PART.match(p or "") or ".." in p:
            raise ValueError("unsafe key path part: %r" % (p,))
    if mode not in MODES:
        raise ValueError("mode must be dark or light: %r" % (mode,))
    return env.cache_path("appglass", "keys", app, fp, mode + ".json")


def _write(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rec, f, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def save(env, app, fp, mode, keys):
    """Store learned keys as waiting (opaque until a verify PASS). Returns the path."""
    p = _path(env, app, fp, mode)
    _write(p, {"version": 1, "status": "waiting", "learned": int(time.time()), "keys": keys})
    return p


def confirm(env, app, fp, mode):
    """A verify PASS: the stored keys may be used."""
    p = _path(env, app, fp, mode)
    with open(p) as f:
        rec = json.load(f)
    rec["status"] = "verified"
    rec["verified"] = int(time.time())
    _write(p, rec)


def verified(env, app, fp, mode):
    """The stored keys once verified, else None."""
    try:
        with open(_path(env, app, fp, mode)) as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    return rec.get("keys") if rec.get("status") == "verified" else None


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="appglass.keylearn")
    ap.add_argument("png")
    ap.add_argument("--content", type=float, default=0.60)
    ap.add_argument("--bar", type=float, default=0.65)
    a = ap.parse_args(argv)
    t0 = time.time()
    w, h, px = read_png(a.png)
    keys = learn(px, w, h)
    print(json.dumps({"keys": keys, "arg": keys_arg(keys, a.content, a.bar),
                      "seconds": round(time.time() - t0, 3)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
