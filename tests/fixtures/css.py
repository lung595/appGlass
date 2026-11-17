"""Small CSS reader for the generated GTK files: which :backdrop rules
change how text looks (filter, opacity, color) between the two states."""

import re

# Adwaita GTK3 paints its focused text with these (``.background``,
# ``button``: theme_fg_color; ``.view``, ``entry``, ``list``: theme_text_color)
FOCUSED_NAMES = ("@theme_fg_color", "@theme_text_color")


def rules(css):
    """[(selector, {prop: value})], one entry per selector of each rule."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for chunk in css.split("}"):
        if "{" not in chunk:
            continue
        head, body = chunk.split("{", 1)
        head = head.rsplit(";", 1)[-1]          # after @import / @define-color lines
        decls = {}
        for d in body.split(";"):
            if ":" in d:
                k, v = d.split(":", 1)
                decls[k.strip()] = " ".join(v.split())
        for sel in head.split(","):
            sel = " ".join(sel.split())
            if sel:
                out.append((sel, decls))
    return out


def backdrop_text_changes(css):
    """[(selector, prop, value)] for every :backdrop rule that makes text
    look different from the focused state: a filter other than none, an
    opacity other than 1, or a colour its focused twin does not have."""
    rs = rules(css)
    colours = {}
    for sel, d in rs:
        if "color" in d:
            colours.setdefault(sel, set()).add(d["color"])
    bad = []
    for sel, d in rs:
        if ":backdrop" not in sel:
            continue
        if d.get("filter", "none") != "none":
            bad.append((sel, "filter", d["filter"]))
        if d.get("opacity", "1") != "1":
            bad.append((sel, "opacity", d["opacity"]))
        if "color" in d:
            twin = sel.replace(":backdrop", "")
            if d["color"] not in FOCUSED_NAMES and d["color"] not in colours.get(twin, ()):
                bad.append((sel, "color", d["color"]))
    return bad
