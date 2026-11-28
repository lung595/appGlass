#!/usr/bin/python3
"""Focused vs unfocused (:backdrop) style of common GTK3 widgets, as JSON.

    gtk3_backdrop.py

Run with GTK_THEME=AppGlass on any GDK backend (the tests use broadway, no
compositor needed). Builds a window with a CSD headerbar (title + button),
a notebook, a spin button, a button, a label, an entry, a popover and a
menu, reads each node's text colour, the headerbar button edges, a few
background colours and the pixels of a panel (button, frame, tree view), sets the windows to :backdrop and reads them again.
Prints {"focused": {...}, "backdrop": {...}}.
"""

import base64
import json
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

w = Gtk.Window(title="backdrop")
hb = Gtk.HeaderBar(title="Title", show_close_button=True)
hb_button = Gtk.Button(label="Hdr")
hb.pack_start(hb_button)
w.set_titlebar(hb)
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
nb = Gtk.Notebook()
tab_checked, tab = Gtk.Label(label="One"), Gtk.Label(label="Two")
nb.append_page(Gtk.Label(label="page one"), tab_checked)
nb.append_page(Gtk.Label(label="page two"), tab)
spin = Gtk.SpinButton.new_with_range(0, 100, 1)
button, label, entry = Gtk.Button(label="Button"), Gtk.Label(label="Label"), Gtk.Entry()
for x in (nb, spin, button, label, entry):
    box.add(x)
w.add(box)
w.show_all()
popover = Gtk.Popover(relative_to=button)
popover.add(Gtk.Label(label="popover"))
menu = Gtk.Menu()
menu.append(Gtk.MenuItem(label="item"))
# the same CSD headerbar in an offscreen window, to read its pixels: the
# window buttons (close, maximize, minimize) and a flat button
ow = Gtk.OffscreenWindow()
ohb = Gtk.HeaderBar(title="Title", show_close_button=True)
ohb.get_style_context().add_class("titlebar")      # what set_titlebar() adds
ow.get_style_context().add_class("csd")
hb_flat = Gtk.Button(label="Flat")
hb_flat.get_style_context().add_class("flat")
ohb.pack_end(hb_flat)
ow.add(ohb)
ow.show_all()
# a panel read as pixels: a plain button, a frame, a tree view with grid
# and tree lines, an expanded row, a selected row, an insensitive row and a
# separator row, and paned separators (thin and wide)
pw = Gtk.OffscreenWindow()
panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
panel.add(Gtk.Button(label="Plain"))
fr = Gtk.Frame(label="Frame")
fr.add(Gtk.Label(label="inside"))
panel.add(fr)
store = Gtk.TreeStore(str, bool)
store.append(store.append(None, ["Parent", True]), ["Child", True])
selected = store.append(None, ["Selected", True])
store.append(None, ["Insensitive", False])
store.append(None, ["--", True])
tree = Gtk.TreeView(model=store)
tree.set_grid_lines(Gtk.TreeViewGridLines.BOTH)
tree.set_enable_tree_lines(True)
for title in ("One", "Two"):
    tree.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=0, sensitive=1))
tree.set_row_separator_func(lambda m, it: m[it][0] == "--")
tree.expand_all()
tree.get_selection().select_iter(selected)
panel.add(tree)
for wide in (False, True):
    pn = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, wide_handle=wide)
    pn.pack1(Gtk.Label(label="left"), True, False)
    pn.pack2(Gtk.Label(label="right"), True, False)
    panel.add(pn)
pw.add(panel)
pw.show_all()


def settle(t=0.3):
    end = time.time() + t
    while time.time() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)


def child_node(parent, gtype, name):
    """A style context for an internal CSS node (spin button button/image)."""
    p = parent.get_style_context().get_path().copy()
    p.append_type(gtype)
    p.iter_set_object_name(-1, name)
    c = Gtk.StyleContext()
    c.set_path(p)
    c.set_parent(parent.get_style_context())
    c.set_state(parent.get_style_context().get_state())
    return c


def titlebuttons(widget):
    """The headerbar's own window buttons (internal children)."""
    out = []
    if isinstance(widget, Gtk.Button) and widget.get_style_context().has_class("titlebutton"):
        out.append(widget)
    if isinstance(widget, Gtk.Container):
        widget.forall(lambda c: out.extend(titlebuttons(c)))
    return out


def frame(widget):
    """The button's pixels with its icon or label not drawn (opacity 0): its
    background and border, what a ring around it changes. RGBA, base64."""
    widget.get_child().set_opacity(0)
    settle(0.1)
    a = widget.get_allocation()
    full = ow.get_pixbuf()
    pb = full.new_subpixbuf(a.x, a.y, a.width, a.height)
    widget.get_child().set_opacity(1)
    rows = pb.get_pixels()
    st, n = pb.get_rowstride(), pb.get_n_channels()
    px = b"".join(rows[y * st:y * st + a.width * n] for y in range(a.height))
    # the bar's own background, left of the title where nothing is drawn
    y = a.y + a.height // 2
    bar = full.get_pixels()[y * full.get_rowstride() + 2 * n:][:n]
    return {"w": a.width, "h": a.height, "n": n, "rgba": base64.b64encode(px).decode(),
            "bar": list(bar)}


def colour(ctx, prop="color"):
    st = ctx.get_state()
    v = ctx.get_color(st) if prop == "color" else ctx.get_property(prop, st)
    return v.to_string()


def read():
    fg = {
        "tab checked": tab_checked, "tab": tab, "headerbar button": hb_button.get_child(),
        "button": button.get_child(), "label": label, "entry": entry, "spinbutton": spin,
    }
    out = {"fg": {k: colour(x.get_style_context()) for k, x in fg.items()}}
    out["fg"]["spinbutton button"] = colour(child_node(spin, Gtk.Button, "button"))
    out["fg"]["spinbutton image"] = colour(child_node(spin, Gtk.Image, "image"))
    hbc = hb_button.get_style_context()
    out["edge"] = {"headerbar button " + side: colour(hbc, "border-%s-color" % side)
                   for side in ("top", "bottom")}
    named = {"titlebutton %d" % i: x for i, x in enumerate(titlebuttons(ohb))}
    named["flat headerbar button"] = hb_flat
    for i, x in enumerate(titlebuttons(hb)):        # the real window's own
        named["window titlebutton %d" % i] = x
    for name, x in named.items():
        for side in ("top", "bottom"):
            out["edge"]["%s %s" % (name, side)] = colour(x.get_style_context(),
                                                         "border-%s-color" % side)
    out["frame"] = {k: frame(x) for k, x in named.items() if not k.startswith("window ")}
    out["bg"] = {
        "window": colour(w.get_style_context(), "background-color"),
        "headerbar": colour(hb.get_style_context(), "background-color"),
        "popover": colour(popover.get_style_context(), "background-color"),
        "menu": colour(menu.get_style_context(), "background-color"),
    }
    pb = pw.get_pixbuf()
    out["panel"] = {"w": pb.get_width(), "h": pb.get_height(), "n": pb.get_n_channels(),
                    "stride": pb.get_rowstride(),
                    "rgba": base64.b64encode(pb.get_pixels()).decode()}
    return out


settle()
res = {"focused": read()}
w.set_state_flags(Gtk.StateFlags.BACKDROP, False)
menu.get_toplevel().set_state_flags(Gtk.StateFlags.BACKDROP, False)  # its own popup window
ow.set_state_flags(Gtk.StateFlags.BACKDROP, False)
pw.set_state_flags(Gtk.StateFlags.BACKDROP, False)
settle()
# the tree view keeps its old picture until something redraws it
for x in panel.get_children():
    x.queue_draw()
settle()
res["backdrop"] = read()
print(json.dumps(res))
