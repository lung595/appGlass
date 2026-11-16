#!/usr/bin/python3
"""libadwaita role window for the gtk4 e2e (app id org.appglass.AdwRoles).

    adw_roles.py plain|menu|dialog

One window with every background role the gtk4 family sets: a split-view
sidebar (sidebar_bg), a raised headerbar (headerbar_bg), a boxed list
(card_bg), body text on window_bg, a dim label and a GtkTextView. ``menu``
opens the headerbar menu popover, ``dialog`` an AdwAlertDialog, both after
1.2 s (no input injection is needed). Non-unique: never talks to a running
instance.
"""

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

MODE = sys.argv[1] if len(sys.argv) > 1 else "plain"
APP_ID = "org.appglass.AdwRoles"
# without a session bus GTK names the Wayland app id after the program name
GLib.set_prgname(APP_ID)


def label(text, *classes):
    w = Gtk.Label(label=text, xalign=0)
    for c in classes:
        w.add_css_class(c)
    return w


def on_activate(app):
    win = Adw.ApplicationWindow(application=app, title="appglass roles")
    win.set_default_size(1100, 760)
    split = Adw.NavigationSplitView(min_sidebar_width=260)

    side = Adw.ToolbarView()
    side.add_top_bar(Adw.HeaderBar(title_widget=Gtk.Label(label="Sidebar")))
    lb = Gtk.ListBox()
    lb.add_css_class("navigation-sidebar")
    for t in ("Inbox", "Starred", "Archive", "Trash", "Projects", "Notes"):
        lb.append(label("%s  sidebar row" % t))
    side.set_content(lb)
    split.set_sidebar(Adw.NavigationPage(title="Sidebar", child=side))

    tv = Adw.ToolbarView(top_bar_style=Adw.ToolbarStyle.RAISED)
    hb = Adw.HeaderBar(title_widget=Adw.WindowTitle(title="Raised headerbar",
                                                    subtitle="headerbar subtitle"))
    menu = Gio.Menu()
    for t in ("New Window", "Preferences", "Keyboard Shortcuts", "About appglass roles"):
        menu.append(t, "app.noop")
    mb = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
    hb.pack_end(mb)
    tv.add_top_bar(hb)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18,
                  margin_start=18, margin_end=18, margin_bottom=18)
    box.append(label("Body text on the window background: The quick brown fox 0123456789",
                     "title-3"))
    box.append(label("Second body line on the glass, regular weight"))
    box.append(label("Dim label secondary text", "dim-label"))
    cards = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    cards.add_css_class("boxed-list")
    for t in ("Card row one", "Card row two", "Card row three"):
        r = Adw.ActionRow(title=t, subtitle="row subtitle")
        r.add_suffix(Gtk.Switch(valign=Gtk.Align.CENTER))
        cards.append(r)
    box.append(cards)
    sw = Gtk.ScrolledWindow(min_content_height=120)
    text = Gtk.TextView()
    text.get_buffer().set_text("GtkTextView on the window background.\nSecond line.")
    sw.set_child(text)
    box.append(sw)
    tv.set_content(box)
    split.set_content(Adw.NavigationPage(title="Content", child=tv))
    win.set_content(split)
    win.present()

    if MODE == "menu":
        GLib.timeout_add(1200, lambda: (mb.popup(), False)[1])
    elif MODE == "dialog":
        def show():
            d = Adw.AlertDialog(heading="Alert dialog",
                                body="Dialog body text on the opaque dialog colour.")
            d.add_response("cancel", "Cancel")
            d.add_response("ok", "OK")
            d.present(win)
            return False
        GLib.timeout_add(1200, show)


app = Adw.Application(application_id=APP_ID,
                      flags=Gio.ApplicationFlags.NON_UNIQUE)
app.add_action(Gio.SimpleAction.new("noop", None))
app.connect("activate", on_activate)
app.run([sys.argv[0]])
