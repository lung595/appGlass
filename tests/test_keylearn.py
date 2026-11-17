"""keylearn: ck-shim colour keys from one opaque capture (engine 1.6)."""

import json
import os
import struct
import tempfile
import unittest
import zlib

from appglass import keylearn
from appglass.core import Env


class Canvas:
    """An opaque RGBA image to paint rectangles on."""

    def __init__(self, w, h, rgb):
        self.w, self.h = w, h
        self.px = bytearray(bytes(rgb) + b"\xff") * (w * h)

    def rect(self, x, y, w, h, rgb):
        for yy in range(y, min(y + h, self.h)):
            for xx in range(x, min(x + w, self.w)):
                i = 4 * (yy * self.w + xx)
                self.px[i:i + 3] = bytes(rgb)

    def learn(self, **kw):
        return keylearn.learn(bytes(self.px), self.w, self.h, **kw)


PAGE = (0x23, 0x23, 0x23)
CARD = (0x2c, 0x2c, 0x2c)
TEXT = (0xe0, 0xe0, 0xe0)


def text_lines(c, rgb, x0, y0, x1, y1):
    """Lines of 1 px glyph strokes, 8 px high every 20 px: many pixels, no area of their own."""
    for y in range(y0, y1, 20):
        for x in range(x0, x1, 2):
            c.rect(x, y, 1, 8, rgb)


class Learn(unittest.TestCase):
    def test_page_colour_is_the_content_key(self):
        c = Canvas(400, 300, PAGE)
        keys = c.learn()
        self.assertEqual([(k["rgb"], k["role"]) for k in keys], [("232323", "content")])
        self.assertGreater(keys[0]["share"], 0.95)

    def test_text_colour_rejected(self):
        c = Canvas(400, 300, PAGE)
        text_lines(c, TEXT, 10, 10, 390, 290)   # about 20 % of the pixels
        n = sum(1 for i in range(0, len(c.px), 4) if c.px[i] == 0xe0)
        self.assertGreater(n, 0.15 * c.w * c.h)
        keys = c.learn()
        self.assertEqual([k["rgb"] for k in keys], ["232323"])

    def test_band_on_an_edge_is_a_bar(self):
        c = Canvas(400, 300, PAGE)
        c.rect(0, 0, 400, 24, CARD)             # title bar, full width, on the top edge
        keys = {k["rgb"]: k["role"] for k in c.learn()}
        self.assertEqual(keys, {"232323": "content", "2c2c2c": "bar"})

    def test_block_inside_is_content(self):
        c = Canvas(400, 300, PAGE)
        c.rect(60, 60, 200, 120, CARD)          # a card, touches no edge
        keys = {k["rgb"]: k["role"] for k in c.learn()}
        self.assertEqual(keys, {"232323": "content", "2c2c2c": "content"})

    def test_at_most_three_keys_by_share(self):
        c = Canvas(400, 300, PAGE)
        c.rect(20, 20, 120, 120, CARD)
        c.rect(160, 20, 100, 100, (0x30, 0x30, 0x30))
        c.rect(280, 20, 80, 80, (0x40, 0x40, 0x40))
        keys = c.learn()
        self.assertEqual([k["rgb"] for k in keys], ["232323", "2c2c2c", "303030"])

    def test_far_brighter_surface_dropped(self):
        """A light block in a dark window (a highlight, another toolkit's menubar) is not
        a key: keying it would fade the popups that share its colour."""
        c = Canvas(400, 300, (0x30, 0x38, 0x41))
        c.rect(0, 0, 400, 24, (0xc7, 0xcb, 0xd1))
        c.rect(60, 60, 200, 120, (0x72, 0x78, 0x7e))
        self.assertEqual([k["rgb"] for k in c.learn()], ["303841", "72787e"])

    def test_small_area_ignored(self):
        c = Canvas(400, 300, PAGE)
        c.rect(100, 100, 16, 16, CARD)          # 0.2 % of the window
        self.assertEqual([k["rgb"] for k in c.learn()], ["232323"])

    def test_keys_arg(self):
        keys = [{"rgb": "232323", "role": "content", "share": 0.8},
                {"rgb": "2c2c2c", "role": "bar", "share": 0.1}]
        self.assertEqual(keylearn.keys_arg(keys, 0.6, 0.65), "232323:0.60,2c2c2c:0.65")


def png(w, h, rows, filters):
    """A PNG (RGBA 8) with the given filter byte per row (the rows already filtered)."""
    raw = b"".join(bytes([f]) + r for f, r in zip(filters, rows))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class ReadPng(unittest.TestCase):
    def test_filters(self):
        a = bytes([10, 20, 30, 255, 12, 22, 32, 255])
        b = bytes([11, 21, 31, 255, 14, 24, 34, 255])
        sub_a = a[:4] + bytes((a[i] - a[i - 4]) % 256 for i in range(4, 8))
        up_b = bytes((b[i] - a[i]) % 256 for i in range(8))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.png")
            with open(p, "wb") as f:
                f.write(png(2, 2, [sub_a, up_b], [1, 2]))
            w, h, px = keylearn.read_png(p)
        self.assertEqual((w, h, px), (2, 2, a + b))

    def test_paeth_and_average(self):
        a = bytes([100, 100, 100, 255, 90, 80, 70, 255])
        b = bytes([50, 60, 70, 255, 200, 10, 0, 255])
        avg_a = bytes(a[i] - (a[i - 4] // 2 if i >= 4 else 0) & 255 for i in range(8))

        def paeth(l, u, ul):
            p = l + u - ul
            pa, pb, pc = abs(p - l), abs(p - u), abs(p - ul)
            return l if pa <= pb and pa <= pc else (u if pb <= pc else ul)
        pae_b = bytes((b[i] - paeth(b[i - 4] if i >= 4 else 0, a[i], a[i - 4] if i >= 4 else 0)) & 255
                      for i in range(8))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.png")
            with open(p, "wb") as f:
                f.write(png(2, 2, [avg_a, pae_b], [3, 4]))
            self.assertEqual(keylearn.read_png(p)[2], a + b)


class Store(unittest.TestCase):
    def test_saved_waiting_until_verified(self):
        with tempfile.TemporaryDirectory() as d:
            env = Env({"HOME": d, "XDG_CACHE_HOME": os.path.join(d, "cache")})
            keys = [{"rgb": "232323", "role": "content", "share": 0.9}]
            p = keylearn.save(env, "saber", "1.37.1", "dark", keys)
            self.assertEqual(p, os.path.join(d, "cache", "appglass", "keys", "saber", "1.37.1",
                                             "dark.json"))
            rec = json.load(open(p))
            self.assertEqual((rec["status"], rec["keys"]), ("waiting", keys))
            self.assertIsNone(keylearn.verified(env, "saber", "1.37.1", "dark"))
            keylearn.confirm(env, "saber", "1.37.1", "dark")
            self.assertEqual(keylearn.verified(env, "saber", "1.37.1", "dark"), keys)

    def test_unsafe_parts_refused(self):
        with tempfile.TemporaryDirectory() as d:
            env = Env({"HOME": d, "XDG_CACHE_HOME": os.path.join(d, "cache")})
            for bad in (("..", "1", "dark"), ("a", "../x", "dark"), ("a", "1", "dim")):
                with self.assertRaises(ValueError):
                    keylearn.save(env, *bad, [])


if __name__ == "__main__":
    unittest.main()
