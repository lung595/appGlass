#!/usr/bin/python3
"""Focused vs unfocused (:backdrop) style of common GTK3 widgets, as JSON.

    gtk3_backdrop.py

Run with GTK_THEME=AppGlass on any GDK backend (the tests use broadway, no
compositor needed). Builds a window with a CSD headerbar (title + button),
a notebook, a spin button, a button, a label, an entry, a popover and a
menu, reads each node's text colour, the headerbar button edges and a few
background colours, sets the windows to :backdrop and reads them again.
Prints {"focused": {...}, "backdrop": {...}}.
"""

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
    out["bg"] = {
        "window": colour(w.get_style_context(), "background-color"),
        "headerbar": colour(hb.get_style_context(), "background-color"),
        "popover": colour(popover.get_style_context(), "background-color"),
        "menu": colour(menu.get_style_context(), "background-color"),
    }
    return out


settle()
res = {"focused": read()}
w.set_state_flags(Gtk.StateFlags.BACKDROP, False)
menu.get_toplevel().set_state_flags(Gtk.StateFlags.BACKDROP, False)  # its own popup window
settle()
res["backdrop"] = read()
print(json.dumps(res))
