#!/usr/bin/python3
"""GTK3 role window for the gtk3 e2e (app id org.appglass.Gtk3Roles).

    gtk3_roles.py [plain|popover]

A CSD headerbar, a menubar, a toolbar, a .sidebar list, body text, a dim
label and a GtkTextView: every role the AppGlass theme sets. ``popover``
opens a GtkPopover from the headerbar after 1.5 s (no input injection is
needed). Plain Gtk.Window: no GApplication, nothing on the session bus.
Run it with GTK_THEME=AppGlass, like the launcher overrides do.
"""

import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

MODE = sys.argv[1] if len(sys.argv) > 1 else "plain"
# the Wayland app id of a plain Gtk.Window is the program name
GLib.set_prgname("org.appglass.Gtk3Roles")

w = Gtk.Window(title="appglass gtk3 roles")
w.set_default_size(1000, 700)
hb = Gtk.HeaderBar(title="HeaderBar title", subtitle="headerbar subtitle", show_close_button=True)
w.set_titlebar(hb)
pop_btn = Gtk.MenuButton(label="Popover")
hb.pack_end(pop_btn)

vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
w.add(vb)
menubar = Gtk.MenuBar()
for t in ("File", "Edit", "View", "Help"):
    menubar.append(Gtk.MenuItem(label=t))
vb.pack_start(menubar, False, False, 0)
tb = Gtk.Toolbar()
for icon in ("document-open", "document-save", "edit-copy"):
    b = Gtk.ToolButton(icon_name=icon)
    b.set_label(icon)
    tb.insert(b, -1)
vb.pack_start(tb, False, False, 0)

paned = Gtk.Paned()
vb.pack_start(paned, True, True, 0)
side = Gtk.ListBox()
side.get_style_context().add_class("sidebar")
for t in ("Sidebar row one", "Devices", "Settings", "About"):
    r = Gtk.ListBoxRow()
    r.add(Gtk.Label(label=t, xalign=0, margin=8))
    side.add(r)
sw0 = Gtk.ScrolledWindow()
sw0.add(side)
sw0.set_size_request(240, -1)
paned.pack1(sw0, False, False)

content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=16)
paned.pack2(content, True, False)
head = Gtk.Label(xalign=0)
head.set_markup("<big><b>Content heading on the glass</b></big>\n"
                "Regular body text on the window background. The quick brown fox 0123456789.")
content.pack_start(head, False, False, 0)
dim = Gtk.Label(label="dim-label secondary text", xalign=0)
dim.get_style_context().add_class("dim-label")
content.pack_start(dim, False, False, 0)
content.pack_start(Gtk.Entry(text="Entry text"), False, False, 0)
tv = Gtk.TextView()
tv.get_buffer().set_text("GtkTextView (.view) text line 1\nline 2")
sw = Gtk.ScrolledWindow()
sw.add(tv)
sw.set_size_request(-1, 120)
content.pack_start(sw, True, True, 0)

pop = Gtk.Popover()
pb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=10, spacing=6)
pb.pack_start(Gtk.Label(label="Popover text"), False, False, 0)
pb.pack_start(Gtk.ModelButton(text="Popover item one"), False, False, 0)
pb.pack_start(Gtk.ModelButton(text="Popover item two"), False, False, 0)
pb.pack_start(Gtk.ModelButton(text="Popover item three"), False, False, 0)
pb.show_all()
pop.add(pb)
pop.set_modal(False)
pop.set_transitions_enabled(False)
pop_btn.set_popover(pop)

w.connect("destroy", Gtk.main_quit)
w.show_all()
if MODE == "popover":
    GLib.timeout_add(1500, lambda: (pop_btn.set_active(True), False)[1])
Gtk.main()
