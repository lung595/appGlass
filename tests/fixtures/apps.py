"""A fake installed-apps world for detect/learn tests: .desktop files, tiny
ELF binaries with chosen DT_NEEDED entries, wrapper scripts, a flatpak
install dir with /app symlinks, Discord's updater layout."""

import json
import os
import struct

from appglass.detect import FUSE_SENTINEL


def elf(needed=(), extra=b""):
    """A minimal ELF64 little-endian file: one PT_LOAD over the whole file,
    a PT_DYNAMIC with DT_NEEDED entries and DT_STRTAB."""
    strtab = b"\0"
    offs = []
    for n in needed:
        offs.append(len(strtab))
        strtab += n.encode() + b"\0"
    base = 0x400000
    str_off = 64 + 2 * 56
    dyn_off = (str_off + len(strtab) + 7) & ~7
    dyn = b"".join(struct.pack("<qQ", 1, o) for o in offs)
    dyn += struct.pack("<qQ", 5, base + str_off) + struct.pack("<qQ", 0, 0)
    body_end = dyn_off + len(dyn)
    total = body_end + len(extra)
    eh = (b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8
          + struct.pack("<HHIQQQIHHHHHH", 3, 62, 1, base, 64, 0, 0, 64, 56, 2, 64, 0, 0))
    ph_load = struct.pack("<IIQQQQQQ", 1, 5, 0, base, base, total, total, 0x1000)
    ph_dyn = struct.pack("<IIQQQQQQ", 2, 6, dyn_off, base + dyn_off, base + dyn_off,
                         len(dyn), len(dyn), 8)
    out = eh + ph_load + ph_dyn + strtab
    out += b"\0" * (dyn_off - len(out)) + dyn + extra
    return out


def fuse_blob(version="40.1.0", wire="0010001"):
    return (b"\0Electron/" + version.encode() + b"\0" + FUSE_SENTINEL + b"\x01"
            + bytes([len(wire)]) + wire.encode() + b"\0")


def _w(path, data, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)
    os.chmod(path, mode)
    return path


def _ln(target, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.symlink(target, path)


def desktop(name, exec_, **kw):
    lines = ["[Desktop Entry]", "Type=%s" % kw.pop("Type", "Application"),
             "Name=%s" % name, "Exec=%s" % exec_]
    lines += ["%s=%s" % (k, v) for k, v in kw.items()]
    lines += ["", "[Desktop Action new]", "Name=New", "Exec=ignored-%s" % name, ""]
    return "\n".join(lines)


class World:
    """Builds the world under sb.root; .env() gives the extra environ."""

    def __init__(self, sb):
        self.sb = sb
        self.usr = sb.path("usr")
        self.bin = os.path.join(self.usr, "bin")
        self.apps = os.path.join(self.usr, "share", "applications")
        self.user_apps = os.path.join(sb.data, "applications")
        self.flatpak = sb.path("flatpak")

    def env(self):
        return {"PATH": self.bin, "XDG_DATA_DIRS": os.path.join(self.usr, "share"),
                "FLATPAK_SYSTEM_DIR": self.flatpak,
                "FLATPAK_USER_DIR": self.sb.path("no-user-flatpak")}

    def exe(self, name, data):
        return _w(os.path.join(self.bin, name), data, 0o755)

    def app(self, did, name, exec_, user=False, **kw):
        return _w(os.path.join(self.user_apps if user else self.apps, did),
                  desktop(name, exec_, **kw))

    def flatpak_app(self, app_id, command, files, base=None, runtime="org.freedesktop.Platform/x86_64/25.08",
                    exec_extra=""):
        d = os.path.join(self.flatpak, "app", app_id)
        hashdir = os.path.join(d, "x86_64", "stable", "0123abcd")
        meta = ["[Application]", "name=%s" % app_id, "runtime=%s" % runtime,
                "command=%s" % command]
        if base:
            meta.append("base=%s" % base)
        _w(os.path.join(hashdir, "metadata"), "\n".join(meta) + "\n")
        _ln("x86_64/stable", os.path.join(d, "current"))
        _ln("0123abcd", os.path.join(hashdir, "..", "active"))
        root = os.path.join(hashdir, "files")
        os.makedirs(root, exist_ok=True)
        for rel, data in files.items():
            p = os.path.join(root, rel)
            if isinstance(data, tuple) and data[0] == "link":
                _ln(data[1], p)
            else:
                _w(p, data, 0o755)
        _w(os.path.join(self.flatpak, "exports", "share", "applications", app_id + ".desktop"),
           desktop(app_id, "/usr/bin/flatpak run --branch=stable --arch=x86_64 "
                           "--command=%s %s%s" % (command, app_id, exec_extra),
                   **{"X-Flatpak": app_id}))
        return root

    def build(self):
        sb = self.sb
        # native toolkits
        self.exe("nautilus", elf(["libgtk-4.so.1", "libadwaita-1.so.0", "libc.so.6"]))
        self.app("org.gnome.Nautilus.desktop", "Files", "nautilus --new-window",
                 StartupWMClass="org.gnome.Nautilus")
        self.exe("vlc", elf(["libvlc.so.5", "libvlccore.so.9"]))
        self.app("vlc.desktop", "VLC", "/usr/bin/vlc --started-from-file %U".replace(
            "/usr/bin", self.bin))
        self.app("vlc.desktop", "VLC", "env QT_STYLE_OVERRIDE=x %s/vlc %%U" % self.bin, user=True)
        self.exe("solaar", "#!/usr/bin/python3\nimport gi\ngi.require_version('Gtk', '3.0')\n"
                           "from gi.repository import Gtk\n")
        self.app("solaar.desktop", "Solaar", "solaar")
        self.exe("com.github.tchx84.Flatseal", "#!/usr/bin/gjs\nimports.package.init({});\n")
        self.app("com.github.tchx84.Flatseal.desktop", "Flatseal", "com.github.tchx84.Flatseal")
        self.exe("alacritty", elf(["libc.so.6"]))
        self.app("Alacritty.desktop", "Alacritty", "alacritty", StartupWMClass="Alacritty")
        self.exe("herdr", elf(["libc.so.6"], b"\0/registry/gpui-0.2.0/src\0"))
        self.app("herdr-app.desktop", "herdr", "herdr", user=True)
        self.exe("dfiles", elf(["libc.so.6"], b"\xff Go buildinf:\0"))
        self.app("dev.duxlabs.files.desktop", "Files", "dfiles")
        self.exe("nvidia-settings", elf(["libc.so.6"], b"\0libnvidia-gtk3.so\0"))
        self.app("nvidia-settings.desktop", "NVIDIA", "nvidia-settings")
        # wrapper with shell variables (firefox-like) -> lib dir with libxul
        lib = sb.path("usr", "lib64", "firefox")
        _w(os.path.join(lib, "firefox"), elf(["libc.so.6"]), 0o755)
        _w(os.path.join(lib, "libxul.so"), elf(["libgtk-3.so.0"]))
        self.exe("firefox", '#!/usr/bin/bash\nMOZ_LIB_DIR="%s"\nMOZ_FILE="firefox"\n'
                            'exec $MOZ_LIB_DIR/firefox/$MOZ_FILE "$@"\n' % sb.path("usr", "lib64"))
        self.app("org.mozilla.firefox.desktop", "Firefox", "firefox %u")
        # Discord: updater script, the client in $XDG_CONFIG_HOME/discord
        self.exe("discord", "#!/usr/bin/sh\nDOWNLOAD=https://updates.discord.com/\nDIR=discord\n"
                            "EXE=Discord\nexec \"$config_home/$DIR/$EXE\" \"$@\"\n")
        self.app("discord.desktop", "Discord", "%s/discord --url -- %%u" % self.bin,
                 StartupWMClass="discord")
        dapp = os.path.join(sb.config, "discord", "app-1.0.9")
        _w(os.path.join(dapp, "Discord"), elf(["libgtk-3.so.0"], fuse_blob("44.1.0")), 0o755)
        _w(os.path.join(dapp, "resources", "app.asar"), "asar")
        _w(os.path.join(dapp, "resources", "_app.asar"), "orig")
        _ln(dapp + "/Discord", os.path.join(sb.config, "discord", "Discord"))
        # Steam client and a Steam game
        self.exe("steam", "#!/bin/bash\nexec /nonexistent/steam.sh \"$@\"\n")
        _w(os.path.join(sb.data, "Steam", "steamrt64", "libcef.so"), elf())
        self.app("steam.desktop", "Steam", "%s/steam %%U" % self.bin)
        self.app("Pinball.desktop", "Pinball", "steam steam://rungameid/480", user=True)
        # skipped entries
        self.app("hidden.desktop", "Hidden", "nautilus", Hidden="true")
        self.app("link.desktop", "Link", "nautilus", Type="Link")
        self.app("ghost.desktop", "Ghost", "not-installed-anywhere")
        # flatpaks: /app symlinks at the command and in a middle component
        self.flatpak_app("org.example.Flutter", "localsend", {
            "bin/localsend": ("link", "/app/opt/ls/localsend_app"),
            "opt/ls": ("link", "/app/real"),
            "real/localsend_app": elf(["libflutter_linux_gtk.so", "libgtk-3.so.0"]),
            "real/lib/libflutter_linux_gtk.so": elf(["libgtk-3.so.0"]),
        })
        self.flatpak_app("md.example.Electron", "app.sh", {
            "bin/app.sh": "#!/bin/sh\nexec zypak-wrapper /app/main/electronapp \"$@\"\n",
            "main/electronapp": elf(["libgtk-3.so.0"], fuse_blob("43.8.9", "0100001")),
            "main/resources/app.asar": "asar",
        }, base="app/org.electronjs.Electron2.BaseApp/x86_64/25.08")
        # a stale export: the app itself is gone
        _w(os.path.join(self.flatpak, "exports", "share", "applications",
                        "org.example.Missing.desktop"),
           desktop("Missing", "/usr/bin/flatpak run org.example.Missing",
                   **{"X-Flatpak": "org.example.Missing"}))
        return self


def record(records, key):
    for r in records:
        if r["key"] == key:
            return r
    raise KeyError(key)


__all__ = ["World", "elf", "fuse_blob", "record", "json"]
