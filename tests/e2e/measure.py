#!/usr/bin/env python3
"""Measure a niri screenshot-window PNG (premultiplied RGBA).

niri writes window shots with premultiplied colour: a pixel shown over a
backdrop B is  P + B * (255 - a) / 255.  So:

  * glass level  = the most common alpha among translucent pixels
  * glass colour = the premultiplied rgb of those pixels
  * opaque text  = pixels with a == 255 whose rgb is the expected colour
  * contrast     = text colour vs the glass composited over white, black
                   and the (scaled, blurred) wallpaper, worst pixel

    measure.py shot.png --content 153 [--tol 6] [--bar 166 --bar-tol 8]
               [--popup HEX ...] [--solid HEX ...] [--text HEX ...]
               [--wallpaper img] [--min-contrast 2.0] [--json out.json]

Prints a JSON report; exits 1 when a check fails.
"""

import argparse
import collections
import json
import statistics
import subprocess
import sys


def decode(path, size=None, blur=None):
    """rgba (or rgb24 for a backdrop) bytes and (w, h)."""
    if size is None:
        w, h = map(int, subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height", "-of", "csv=p=0", path]).decode().strip().split(","))
        data = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", path,
                                        "-f", "rawvideo", "-pix_fmt", "rgba", "-"])
        return data, (w, h)
    w, h = size
    vf = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (w, h, w, h)
    if blur:
        vf += ",gblur=sigma=%s" % blur
    data = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", vf,
                                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                    "-"])
    return data, (w, h)


def hexrgb(h):
    h = h.strip().lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lum(rgb):
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(la, lb):
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def a8(v):
    v = float(v)
    return int(round(v * 255)) if v <= 1.0 else int(round(v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shot")
    ap.add_argument("--content", required=True, help="expected glass alpha (0-1 or 0-255)")
    ap.add_argument("--tol", type=int, default=6)
    ap.add_argument("--bar", help="expected bar alpha, when the app has bars")
    ap.add_argument("--bar-tol", type=int, default=8)
    ap.add_argument("--popup", action="append", default=[],
                    help="hex of an opaque popup/menu surface (alpha 255)")
    ap.add_argument("--solid", action="append", default=[],
                    help="hex of an opaque fill expected at alpha 255")
    ap.add_argument("--solid-min", type=int, default=200)
    ap.add_argument("--text", action="append", default=[], help="hex of opaque text")
    ap.add_argument("--text-tol", type=int, default=4)
    ap.add_argument("--glyph-min", type=int, default=12, help="min fully opaque glyph px")
    ap.add_argument("--wallpaper")
    ap.add_argument("--blur", default="20")
    ap.add_argument("--min-contrast", type=float, default=2.0)
    ap.add_argument("--json")
    a = ap.parse_args()

    data, (w, h) = decode(a.shot)
    n = w * h
    fails = []
    hist = collections.Counter(data[3::4])
    visible = n - hist.get(0, 0)
    translucent = collections.Counter({k: v for k, v in hist.items() if 0 < k < 255})
    rep = {"shot": a.shot, "size": [w, h], "visible_px": visible,
           "opaque_px": hist.get(255, 0)}

    # glass level
    want = a8(a.content)
    mode = translucent.most_common(1)[0][0] if translucent else None
    near = sum(v for k, v in hist.items() if abs(k - want) <= a.tol and k not in (0, 255))
    rep["content"] = {"expected": want, "alpha_mode": mode,
                      "share_within_tol": round(near / max(visible, 1), 3)}
    if mode is None or abs(mode - want) > a.tol:
        fails.append("content alpha mode %s, expected %d+-%d" % (mode, want, a.tol))
    elif near / max(visible, 1) < 0.25:
        fails.append("only %.1f%% of the window at the content alpha" % (100.0 * near / visible))
    if a.bar:
        bw = a8(a.bar)
        bpx = sum(v for k, v in hist.items() if abs(k - bw) <= a.bar_tol and abs(k - want) > a.tol
                  and k != 255)
        rep["bar"] = {"expected": bw, "px": bpx}
        if bpx < 200:
            fails.append("no bar surface at alpha %d+-%d" % (bw, a.bar_tol))

    # glass colour (premultiplied) at the mode alpha
    glass = None
    if mode is not None:
        px = [i for i in range(3, len(data), 4) if data[i] == mode]
        step = max(1, len(px) // 20000)
        px = px[::step]
        glass = tuple(int(statistics.median(data[i - 3 + c] for i in px)) for c in range(3))
        rep["glass_premul_rgb"] = list(glass)

    def opaque_count(rgb, tol):
        r0, g0, b0 = rgb
        cnt = 0
        for i in range(0, len(data), 4):
            if data[i + 3] == 255 and abs(data[i] - r0) <= tol and abs(data[i + 1] - g0) <= tol \
                    and abs(data[i + 2] - b0) <= tol:
                cnt += 1
        return cnt

    # opaque fills: popups and explicit backgrounds
    for kind, hexes in (("popup", a.popup), ("solid", a.solid)):
        for hx in hexes:
            cnt = opaque_count(hexrgb(hx), 2)
            rep.setdefault(kind, {})[hx] = {"alpha255_px": cnt}
            if cnt < a.solid_min:
                fails.append("%s %s: %d px at alpha 255 (< %d)" % (kind, hx, cnt, a.solid_min))

    # backdrops for the contrast check
    backs = {"white": [(255, 255, 255)], "black": [(0, 0, 0)]}
    if a.wallpaper:
        wp, _ = decode(a.wallpaper, (w, h), a.blur)
        step = 7
        backs["wallpaper"] = [tuple(wp[i:i + 3]) for i in range(0, len(wp), 3 * step)]
    glass_l = {}
    if glass is not None:
        k = (255 - mode) / 255.0
        for name, bs in backs.items():
            ls = [lum(tuple(min(255, glass[c] + b[c] * k) for c in range(3))) for b in bs]
            glass_l[name] = (min(ls), max(ls))
        rep["glass_luminance"] = {k2: [round(v[0], 4), round(v[1], 4)]
                                  for k2, v in glass_l.items()}

    # text: opaque glyphs of the expected colour, readable over every backdrop
    texts = {}
    for hx in a.text:
        rgb = hexrgb(hx)
        cnt = opaque_count(rgb, a.text_tol)
        lt = lum(rgb)
        worst = {}
        for name, (lo, hi) in glass_l.items():
            if lo <= lt <= hi:
                worst[name] = 1.0
            else:
                worst[name] = round(min(contrast(lt, lo), contrast(lt, hi)), 3)
        texts[hx] = {"glyph_alpha255_px": cnt, "contrast": worst}
        if cnt < a.glyph_min:
            fails.append("text %s: %d opaque glyph px (< %d)" % (hx, cnt, a.glyph_min))
        for name, c in worst.items():
            if c < a.min_contrast:
                fails.append("text %s: contrast %.2f over %s (< %.1f)"
                             % (hx, c, name, a.min_contrast))
    if texts:
        rep["text"] = texts
        rep["min_text_contrast"] = min(min(t["contrast"].values()) for t in texts.values()
                                       if t["contrast"]) if glass_l else None

    rep["fails"] = fails
    rep["pass"] = not fails
    out = json.dumps(rep, indent=1)
    if a.json:
        with open(a.json, "w") as f:
            f.write(out + "\n")
    print(out)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
