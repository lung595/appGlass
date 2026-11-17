"""detect: which toolkit draws each installed app (static, read-only).

Never starts an app. Reads only .desktop files, flatpak metadata files, ELF
dynamic sections (parsed here, no readelf), wrapper scripts and directory
listings. The result is one record per launcher:

    key          the desktop id without ".desktop" (the settings.json apps key)
    desktop_id   e.g. "org.gnome.Nautilus.desktop"
    path         the .desktop file used (the system one when a user override
                 shadows it; then overridden_by names the override)
    app_ids      niri app-id regexes for the window (StartupWMClass, flatpak
                 id, desktop id)
    names        the plain names those regexes came from
    toolkit      electron, cef, gecko, flutter, qt-webengine, qt-quick,
                 qt-widgets, webkitgtk, gtk4-adw, gtk4, gtk3, terminal, sdl,
                 egui, slint, iced, winit, gpui, go-launcher, chromium,
                 wayland-raw, game, unknown
    evidence     why, strongest first
    exec         the binary or script reached from Exec

Flatpak paths that point into /app are remapped to the app's files dir at
every path component (symlinks inside the files tree included).
"""

import mmap
import os
import re
import shlex
import struct

FUSE_SENTINEL = b"dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX"
FUSES = ("RunAsNode", "EnableCookieEncryption", "EnableNodeOptionsEnvironmentVariable",
         "EnableNodeCliInspectArguments", "EnableEmbeddedAsarIntegrityValidation",
         "OnlyLoadAppFromAsar", "LoadBrowserProcessSpecificV8Snapshot",
         "GrantFileProtocolExtraPrivileges", "WasmTrapHandlers")

# toolkit -> priority; the highest-priority strong evidence wins
PRIORITY = {
    "game": 120, "electron": 100, "terminal": 98, "chromium": 95,
    "cef": 90, "gecko": 90, "flutter": 90, "qt-webengine": 85, "qt-quick": 80,
    "webkitgtk": 75, "qt-widgets": 70, "gtk4-adw": 65, "gtk4": 60, "gtk3": 55,
    "gpui": 50, "egui": 45, "slint": 45, "iced": 45, "winit": 40, "sdl": 30,
    "go-launcher": 20, "gpu-native": 10, "wayland-raw": 5, "unknown": 0,
}

SONAMES = (
    (r"^libcef\.so", "cef"),
    (r"^libxul\.so", "gecko"),
    (r"^libflutter_linux_gtk\.so", "flutter"),
    (r"^libQt[56]WebEngine(Core|Quick|Widgets)\.so", "qt-webengine"),
    (r"^libQt[56](Quick|Qml)\.so", "qt-quick"),
    (r"^libQt[56]Widgets\.so", "qt-widgets"),
    (r"^libvlc\.so", "qt-widgets"),           # VLC draws through its Qt plugin
    (r"^libwebkit(2gtk-4\.[01]|gtk-6\.0)\.so", "webkitgtk"),
    (r"^libadwaita-1\.so", "gtk4-adw"),
    (r"^libgtk-4\.so", "gtk4"),
    (r"^libgtk-3\.so", "gtk3"),
    (r"^libSDL[23]", "sdl"),
    (r"^libvulkan\.so", "gpu-native"),
    (r"^libEGL\.so", "gpu-native"),
    (r"^libwayland-client\.so", "wayland-raw"),
)
_SONAMES = tuple((re.compile(r), t) for r, t in SONAMES)

TERMINALS = ("alacritty", "kitty", "foot", "footclient", "ghostty", "wezterm",
             "wezterm-gui", "konsole", "gnome-terminal-server", "ptyxis")
# apps whose children are other apps: an environment variable set for them
# reaches every app they start (S3, S8). Categories first, then names.
SPAWNER_CATEGORIES = (("TerminalEmulator", "terminal"), ("FileManager", "file manager"))
SPAWNER_NAMES = (
    (r"(?i)^(xfce4-terminal|qterminal|tilix|terminator|lxterminal|mate-terminal|sakura"
     r"|terminology|xterm|uxterm|urxvt|rxvt|guake|tilda|yakuake|cool-retro-term|kgx"
     r"|gnome-terminal|blackbox|contour|rio|st|%s)$" % "|".join(re.escape(t) for t in TERMINALS),
     "terminal"),
    (r"(?i)^(thunar|pcmanfm|pcmanfm-qt|nemo|caja|dolphin|nautilus|spacefm|doublecmd"
     r"|krusader)$", "file manager"),
)

# next to the binary (or one level up)
DIR_MARKERS = (
    ("resources/app.asar", "electron"), ("resources/app", "electron"),
    ("app.asar", "electron"), ("libcef.so", "cef"), ("libxul.so", "gecko"),
    ("omni.ja", "gecko"), ("lib/libflutter_linux_gtk.so", "flutter"),
    ("data/flutter_assets", "flutter"),
)

# crate paths left in statically linked Rust GUIs; Go's build info
STATIC_MARKERS = (
    (rb"gpui[-_/]", "gpui", "gpui crate"),
    (rb"/eframe[-_/][0-9a-z]", "egui", "eframe crate"),
    (rb"/egui[-_/][0-9a-z]", "egui", "egui crate"),
    (rb"/slint-1\.\d+", "slint", "slint crate"),
    (rb"/iced_[a-z]+-0\.\d+", "iced", "iced crate"),
    (rb"winit-0\.\d+", "winit", "winit crate"),
)
GO_BUILDINF = b"\xff Go buildinf:"
# toolkit libraries named as strings (dlopen at run time, e.g. nvidia-settings)
DLOPEN_MARKERS = (
    (rb"libnvidia-gtk3\.so", "gtk3"),
    (rb"libgtk-4\.so\.1", "gtk4"),
    (rb"libgtk-3\.so\.0", "gtk3"),
    (rb"libQt6Widgets\.so", "qt-widgets"),
)

FLATPAK_BASES = (
    ("org.electronjs.Electron2.BaseApp", "electron"),
    ("org.chromium.Chromium.BaseApp", "chromium"),
    ("io.qt.qtwebengine.BaseApp", "qt-webengine"),
)

MAX_SCAN = 512 << 20

# classes (engine spec 1.3): root, game (sticky), sensitive, game-launcher
ROOT_CMDS = ("pkexec", "sudo", "run0", "doas", "kdesu", "kdesudo", "lxqt-sudo", "lxsudo",
             "gksu", "gksudo", "beesu", "su-to-root")
# options of the elevators that take a value (the value is not the app)
_ROOT_VALUED = {"-u", "--user", "-g", "--group", "-p", "--property", "--uid", "--gid",
                "-m", "--message", "-D", "--description", "--unit", "-E", "--setenv",
                "--slice", "-M", "--machine", "-H", "--host", "--working-directory",
                "-C", "--chdir", "--prompt", "-P"}
_ROOT_SCRIPT = re.compile(r"(?m)(?:^|[\s;&|(`'\"])(?:exec\s+)?(?:/\S*/)?(%s)\s+\S"
                          r"|(?:^|[\s;&|(`])(?:/\S*/)?su\s+(?:-c|-|-l|--login)(?:\s|$)"
                          % "|".join(re.escape(c) for c in sorted(ROOT_CMDS, key=len, reverse=True)))
_SYSTEMD_RUN = re.compile(r"(?m)(?:^|[\s;&|(`'\"])(?:exec\s+)?(?:/\S*/)?systemd-run(\s[^\n]*)$")
GAME_DIRS = ("/steamapps/common/", "/compatdata/", "/Heroic/", "/lutris/", "/Games/")
GAME_CMDS = ("wine", "wine64", "proton", "umu-run")
_GAME_SCRIPT = re.compile(r"(?m)(?:^|[\s;&|(`'\"/])(wine|wine64|proton|umu-run)\s+\S")
SENSITIVE = (r"(?i)keepassxc", r"(?i)bitwarden", r"(?i)1password", r"(?i)proton[ ._-]?pass",
             r"(?i)seahorse", r"(?i)(^|\.)authenticator$", r"(?i)org\.gnome\.World\.Secrets",
             r"(?i)^secrets$")
GAME_LAUNCHERS = (r"(?i)^(steam|lutris|heroic|bottles|umu-run|prismlauncher|polymc|multimc"
                  r"|atlauncher|itch|minigalaxy|gamehub|playonlinux|legendary-gl)$",
                  r"net\.lutris\.Lutris", r"com\.heroicgameslauncher\.",
                  r"com\.usebottles\.bottles", r"com\.valvesoftware\.Steam",
                  r"org\.prismlauncher\.", r"org\.polymc\.", r"org\.multimc\.",
                  r"com\.atlauncher\.", r"io\.itch\.", r"io\.github\.sharkwouter\.Minigalaxy")
# a Categories=Game app that draws through SDL, GL or Vulkan is a game,
# whatever toolkit draws its menus
_GFX = re.compile(r"^lib(SDL[23]|GL|GLX|OpenGL|EGL|vulkan)[-.]")


def root_target(argv):
    """(elevator, the app it runs) when argv runs something as root (or as
    another user), else None. The app is None when not found."""
    if not argv:
        return None
    b0 = os.path.basename(argv[0])
    if b0 == "su":
        if not set(argv[1:]) & {"-c", "-", "-l", "--login"}:
            return None
    elif b0 == "systemd-run":
        opts = " ".join(argv[1:])
        if "--user" in argv[1:] and not re.search(r"--uid\b|\bUser=", opts):
            return None
    elif b0 not in ROOT_CMDS:
        return None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--":
            i += 1
            break
        if a in ("-c", "--command"):
            words = argv[i + 1].split() if i + 1 < len(argv) else []
            return b0, (words[0] if words else None)
        if not a.startswith("-"):
            break
        i += 2 if a in _ROOT_VALUED else 1
    return b0, (argv[i] if i < len(argv) else None)


def _root_in_script(txt):
    m = _ROOT_SCRIPT.search(txt)
    if m:
        return (m.group(1) or "su").strip()
    for m in _SYSTEMD_RUN.finditer(txt):
        if root_target(["systemd-run"] + m.group(1).split()):
            return "systemd-run"
    return None


APPIMAGE_MAGIC = b"AI\x02"
# an AppImage is not opened (the squashfs reader is deferred): its toolkit is
# guessed from its name, weak evidence only (opaque until learned)
APPIMAGE_HINTS = (
    (r"(?i)obsidian|discord|slack|signal|element|vscodium|visual.?studio|joplin|bitwarden"
     r"|electron|feishin|heroic|logseq|notion", "electron"),
    (r"(?i)krita|kdenlive|qt|kde", "qt-widgets"),
    (r"(?i)gimp|inkscape|gtk|audacity", "gtk3"),
)


def is_appimage(path):
    return _head(path, 16)[8:11] == APPIMAGE_MAGIC


def game_argv(argv):
    """Why argv starts a game (Wine, Proton, umu, Lutris, Heroic, a .exe), or None."""
    for a in argv:
        b = os.path.basename(a)
        if b in GAME_CMDS:
            return "runs %s" % b
        if a.startswith(("lutris:", "heroic://")):
            return "%s link" % a.split(":", 1)[0]
        if a.lower().endswith(".exe"):
            return "targets a Windows .exe"
        if a.startswith("/") and any(d in a for d in GAME_DIRS):
            return "game dir %s" % next(d for d in GAME_DIRS if d in a).strip("/")
    return None


# ---------------------------------------------------------------- small readers

def _head(path, n=65536):
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return b""


def is_elf(path):
    return _head(path, 4) == b"\x7fELF"


def elf_needed(path):
    """DT_NEEDED sonames of an ELF file ([] when not one or unreadable)."""
    try:
        with open(path, "rb") as f:
            eh = f.read(64)
            if len(eh) < 52 or eh[:4] != b"\x7fELF":
                return []
            cls, data = eh[4], eh[5]
            e = "<" if data == 1 else ">"
            if cls == 2:
                phoff, = struct.unpack_from(e + "Q", eh, 32)
                phentsize, phnum = struct.unpack_from(e + "HH", eh, 54)
                phfmt, dynfmt = e + "IIQQQQQQ", e + "qQ"
            elif cls == 1:
                phoff, = struct.unpack_from(e + "I", eh, 28)
                phentsize, phnum = struct.unpack_from(e + "HH", eh, 42)
                phfmt, dynfmt = e + "IIIIIIII", e + "iI"
            else:
                return []
            if phnum == 0 or phnum > 512:
                return []
            f.seek(phoff)
            ph = f.read(phentsize * phnum)
            loads, dyn = [], None
            for i in range(phnum):
                fields = struct.unpack_from(phfmt, ph, i * phentsize)
                if cls == 2:
                    ptype, _flags, off, vaddr, _pa, filesz = fields[:6]
                else:
                    ptype, off, vaddr, _pa, filesz = fields[:5]
                if ptype == 1:
                    loads.append((vaddr, off, filesz))
                elif ptype == 2:
                    dyn = (off, filesz)
            if not dyn:
                return []
            f.seek(dyn[0])
            raw = f.read(min(dyn[1], 1 << 20))
            step = struct.calcsize(dynfmt)
            needed, strtab = [], None
            for i in range(0, len(raw) - step + 1, step):
                tag, val = struct.unpack_from(dynfmt, raw, i)
                if tag == 0:
                    break
                if tag == 1:
                    needed.append(val)
                elif tag == 5:
                    strtab = val
            if strtab is None:
                return []
            base = None
            for vaddr, off, filesz in loads:
                if vaddr <= strtab < vaddr + filesz:
                    base = strtab - vaddr + off
                    break
            if base is None:
                return []
            out = []
            for n in needed:
                f.seek(base + n)
                s = f.read(256).split(b"\0", 1)[0]
                out.append(s.decode("ascii", "replace"))
            return out
    except (OSError, struct.error):
        return []


def _mapped(path):
    try:
        f = open(path, "rb")
    except OSError:
        return None, None
    try:
        size = os.fstat(f.fileno()).st_size
        if size == 0 or size > MAX_SCAN:
            f.close()
            return None, None
        return f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    except (OSError, ValueError):
        f.close()
        return None, None


def electron_fuses(path):
    """{"electron": version, <fuse>: "0"/"1"/"r"} or None."""
    f, m = _mapped(path)
    if m is None:
        return None
    try:
        i = m.find(FUSE_SENTINEL)
        if i < 0:
            return None
        j = i + len(FUSE_SENTINEL)
        n = m[j + 1]
        wire = m[j + 2:j + 2 + n]
        out = {}
        k = m.find(b"Electron/")
        v = re.match(rb"\d+\.\d+\.\d+", m[k + 9:k + 30]) if k >= 0 else None
        out["electron"] = v.group(0).decode() if v else "?"
        for idx, b in enumerate(wire):
            if idx < len(FUSES):
                out[FUSES[idx]] = chr(b)
        return out
    finally:
        m.close()
        f.close()


def static_markers(path):
    f, m = _mapped(path)
    if m is None:
        return []
    try:
        out = []
        for rx, tk, why in STATIC_MARKERS:
            hit = re.search(rx, m)
            if hit and all(t != tk for t, _ in out):
                out.append((tk, "static marker %r (%s)"
                            % (hit.group(0).decode("ascii", "replace"), why)))
        if not out and m.find(GO_BUILDINF) >= 0:
            out.append(("go-launcher", "Go binary (a launcher; the window is elsewhere)"))
        return out[:2]
    finally:
        m.close()
        f.close()


def dlopen_markers(path):
    f, m = _mapped(path)
    if m is None:
        return []
    try:
        for rx, tk in DLOPEN_MARKERS:
            hit = re.search(rx, m)
            if hit:
                return [(tk, "names %s (dlopen)" % hit.group(0).decode("ascii", "replace"))]
        return []
    finally:
        m.close()
        f.close()


# ---------------------------------------------------------------- paths

def resolve(path, root=None, limit=40):
    """realpath with flatpak's /app mapped onto root at every component."""
    if root and (path == "/app" or path.startswith("/app/")):
        path = root + path[4:]
    parts = [p for p in path.split("/") if p]
    cur = "/"
    seen = 0
    while parts:
        part = parts.pop(0)
        if part == ".":
            continue
        if part == "..":
            cur = os.path.dirname(cur)
            continue
        nxt = os.path.join(cur, part)
        if os.path.islink(nxt):
            seen += 1
            if seen > limit:
                return nxt
            t = os.readlink(nxt)
            if root and (t == "/app" or t.startswith("/app/")):
                t = root + t[4:]
            if t.startswith("/"):
                cur = "/"
            parts = [p for p in t.split("/") if p] + parts
            continue
        cur = nxt
    return cur


def _which(name, env):
    for d in env.environ.get("PATH", "/usr/bin").split(":"):
        p = os.path.join(d, name)
        if d and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


# ---------------------------------------------------------------- .desktop

def parse_desktop(path):
    """The [Desktop Entry] group as a dict (unlocalised keys only)."""
    out, group = {}, None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    group = line[1:-1]
                    continue
                if group != "Desktop Entry" or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                if "[" in k or k in out:
                    continue
                out[k] = v.strip()
    except OSError:
        return {}
    return out


def exec_argv(exec_line):
    s = re.sub(r"%[a-zA-Z%]", "", exec_line or "")
    try:
        argv = shlex.split(s)
    except ValueError:
        argv = s.split()
    out = list(argv)
    if out and os.path.basename(out[0]) == "env":
        out.pop(0)
        while out and (out[0].startswith("-") or "=" in out[0]):
            if out[0] in ("-u", "--unset", "-C", "--chdir", "-S"):
                out.pop(0)
            if out:
                out.pop(0)
    while out and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", out[0]):
        out.pop(0)
    return out


def data_dirs(env):
    dirs = [env.data_home]
    xdg = env.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs += [d for d in xdg.split(":") if d]
    for root in flatpak_roots(env):
        dirs.append(os.path.join(root, "exports", "share"))
    out = []
    for d in dirs:
        d = os.path.abspath(d)
        if d not in out:
            out.append(d)
    return out


def desktop_files(env):
    """[(desktop_id, [paths in XDG order])] for every application launcher."""
    found = {}
    order = []
    for d in data_dirs(env):
        apps = os.path.join(d, "applications")
        if not os.path.isdir(apps):
            continue
        for top, subdirs, files in os.walk(apps):
            subdirs.sort()
            for n in sorted(files):
                if not n.endswith(".desktop"):
                    continue
                p = os.path.join(top, n)
                did = os.path.relpath(p, apps).replace("/", "-")
                if did not in found:
                    found[did] = []
                    order.append(did)
                if p not in found[did]:
                    found[did].append(p)
    return [(did, found[did]) for did in order]


# ---------------------------------------------------------------- flatpak

def flatpak_roots(env):
    user = env.environ.get("FLATPAK_USER_DIR") or os.path.join(env.data_home, "flatpak")
    system = env.environ.get("FLATPAK_SYSTEM_DIR") or "/var/lib/flatpak"
    return [r for r in (user, system) if os.path.isdir(r)]


def flatpak_app(env, app_id):
    """{"installation", "dir", "files", runtime/sdk/base/command} or None."""
    for root in flatpak_roots(env):
        d = os.path.join(root, "app", app_id, "current", "active")
        meta = os.path.join(d, "metadata")
        if not os.path.isfile(meta):
            continue
        info = {"installation": "user" if root.startswith(env.data_home) else "system",
                "dir": os.path.realpath(d), "files": os.path.realpath(os.path.join(d, "files"))}
        group = None
        try:
            with open(meta, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("["):
                        group = line
                    elif group == "[Application]" and "=" in line:
                        k, v = line.split("=", 1)
                        if k in ("runtime", "sdk", "base", "command", "name"):
                            info[k] = v
        except OSError:
            continue
        return info
    return None


def flatpak_id(argv):
    if not argv or os.path.basename(argv[0]) != "flatpak":
        return None
    rest = argv[1:]
    if not rest or rest[0] != "run":
        return None
    for a in rest[1:]:
        if not a.startswith("-"):
            return a
    return None


def flatpak_command(argv):
    for a in argv:
        if a.startswith("--command="):
            return a.split("=", 1)[1]
    return None


# ---------------------------------------------------------------- probing

class Probe:
    def __init__(self, env):
        self.env = env
        self.ev = []           # [(toolkit, why, weak)]
        self.seen = set()
        self.fuses = None
        self.exec = None
        self.classes = {}      # class -> why (root, game)
        self.appimage = None
        self.gfx = None        # an SDL/GL/Vulkan library it links

    def mark(self, cls, why):
        self.classes.setdefault(cls, why)

    def add(self, tk, why, weak=False):
        self.ev.append((tk, why, weak))

    def dir_markers(self, d):
        hits = []
        for rel, tk in DIR_MARKERS:
            if os.path.exists(os.path.join(d, rel)):
                hits.append(tk)
                self.add(tk, "file %s next to the binary" % rel)
        return hits

    def binary(self, path, root=None, depth=0):
        if not path or depth > 4:
            return
        real = resolve(path, root)
        if real in self.seen or not os.path.isfile(real):
            return
        self.seen.add(real)
        if self.exec is None:
            self.exec = real
        if any(d in real for d in GAME_DIRS):
            self.mark("game", "exe under %s" % next(d for d in GAME_DIRS if d in real).strip("/"))
        if is_appimage(real):
            self.appimage = real
            name = os.path.basename(real)
            self.add("unknown", "AppImage %s (not opened)" % name, weak=True)
            for rx, tk in APPIMAGE_HINTS:
                if re.search(rx, name):
                    self.add(tk, "AppImage name %s" % name, weak=True)
                    break
            return
        d = os.path.dirname(real)
        for dd in (d, os.path.dirname(d)):
            if "electron" in self.dir_markers(dd) and self.fuses is None:
                # the Electron executable sits next to resources/: the biggest ELF
                try:
                    names = os.listdir(dd)
                except OSError:
                    names = []
                elfs = [os.path.join(dd, n) for n in names
                        if os.path.isfile(os.path.join(dd, n)) and is_elf(os.path.join(dd, n))]
                for e in sorted(elfs, key=os.path.getsize, reverse=True)[:1]:
                    fz = electron_fuses(e)
                    if fz:
                        self.fuses = fz
                        self.add("electron", "Electron %s fuse wire in %s"
                                 % (fz["electron"], os.path.basename(e)))
        if is_elf(real):
            self.elf(real)
        else:
            self.script(real, root, depth)

    def elf(self, real):
        if os.path.basename(real) in TERMINALS:
            self.add("terminal", "terminal binary %s" % os.path.basename(real))
        if self.fuses is None:
            fz = electron_fuses(real)
            if fz:
                self.fuses = fz
                self.add("electron", "Electron %s fuse wire" % fz["electron"])
        for so in elf_needed(real):
            if self.gfx is None and _GFX.search(so):
                self.gfx = so
            for rx, tk in _SONAMES:
                if rx.search(so):
                    self.add(tk, "links %s" % so)
                    break
        strong = [t for t, _, w in self.ev if not w and t not in ("wayland-raw", "gpu-native")]
        if not strong:
            for tk, why in static_markers(real):
                self.add(tk, why)
        if not [t for t, _, w in self.ev if not w and t not in ("wayland-raw", "gpu-native")]:
            for tk, why in dlopen_markers(real):
                self.add(tk, why, weak=True)

    def script(self, real, root, depth):
        raw = _head(real)
        if b"\0" in raw[:4096]:
            return
        txt = raw.decode("utf-8", "replace")
        first = txt.split("\n", 1)[0]
        if not first.startswith("#!"):
            return
        if "gjs" in first:
            if re.search(r"""Gtk['"]?\s*[:=]\s*['"]4""", txt):
                self.add("gtk4", "gjs script, Gtk 4.0")
            else:
                self.add("gtk4", "gjs script (GNOME JS: GTK4 assumed)", weak=True)
        if "python" in first:
            if re.search(r"""require_version\(\s*['"]Gtk['"]\s*,\s*['"]4""", txt):
                self.add("gtk4", "python gi Gtk 4")
            elif re.search(r"""require_version\(\s*['"]Gtk['"]\s*,\s*['"]3""", txt):
                self.add("gtk3", "python gi Gtk 3")
            elif re.search(r"PyQt[56]|PySide[26]", txt):
                self.add("qt-widgets", "python Qt import")
            elif re.search(r"\bGtk\b|\bgtk\b", txt):
                self.add("gtk3", "python gtk import (GTK3 assumed)", weak=True)
        el = _root_in_script(txt)
        if el:
            self.mark("root", "%s in %s" % (el, os.path.basename(real)))
        m = _GAME_SCRIPT.search(txt)
        if m:
            self.mark("game", "runs %s (%s)" % (m.group(1), os.path.basename(real)))
        if "updates.discord.com" in txt:
            self.discord(txt, depth)
        for t in self.script_targets(txt, real, root):
            self.binary(t, root, depth + 1)

    @staticmethod
    def expand(txt):
        """Path tokens with simple shell variables filled in: X="/usr/lib64"
        then "$X/firefox/$Y" (first assignment wins)."""
        vars_ = {}
        for k, v in re.findall(r"""(?m)^\s*(?:export\s+|local\s+)?([A-Za-z_]\w*)=['"]?([\w./+-]*)['"]?\s*(?:;|$)""",
                               txt):
            vars_.setdefault(k, v)
        toks = []
        for tok in re.findall(r"""(?:\$\{?[A-Za-z_]\w*\}?|/)[\w.+/${}-]*""", txt):
            def sub(m):
                return vars_.get(m.group(1) or m.group(2), "\0")
            t = re.sub(r"\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)", sub, tok)
            if t.startswith("/") and "\0" not in t and "$" not in t and t not in toks:
                toks.append(t)
        return toks

    def script_targets(self, txt, me, root):
        out = []
        for tok in self.expand(txt):
            if root and (tok == "/app" or tok.startswith("/app/")):
                cand = resolve(tok, root)
            else:
                cand = tok
            if (cand != me and cand not in out and os.path.isfile(cand)
                    and not cand.startswith(("/bin/", "/usr/bin/env", "/dev/"))
                    and os.path.basename(cand) not in ("sh", "bash", "env", "zenity")):
                out.append(cand)
        # app_command='timeshift-gtk' / exec name: a bare command on PATH
        for name in re.findall(r"""(?m)^\s*\w*command\w*=['"]?([\w.+-]+)['"]?\s*$""", txt):
            p = _which(name, self.env)
            if p and p != me and p not in out:
                out.append(p)
        return out

    def discord(self, txt, depth):
        """Discord's updater script: the client lives in $XDG_CONFIG_HOME/<DIR>."""
        dir_ = re.search(r"(?m)^DIR=(\S+)", txt)
        exe = re.search(r"(?m)^EXE=(\S+)", txt)
        if not dir_ or not exe:
            return
        host = os.path.join(self.env.config_home, dir_.group(1).strip("'\""),
                            exe.group(1).strip("'\""))
        if os.path.exists(host):
            self.add("electron", "Discord updater: client %s" % self.env.tilde(host))
            self.binary(host, depth=depth + 1)

    def flatpak(self, info):
        base, rt = info.get("base", ""), info.get("runtime", "")
        for name, tk in FLATPAK_BASES:
            if name in base:
                self.add(tk, "flatpak base %s" % name)
        if rt.startswith("org.kde.Platform"):
            self.add("qt-widgets", "flatpak runtime org.kde.Platform", weak=True)
        if rt.startswith("org.gnome.Platform"):
            self.add("gtk4", "flatpak runtime org.gnome.Platform", weak=True)

    def best(self):
        strong = [(t, why) for t, why, w in self.ev if not w]
        pool = strong or [(t, why) for t, why, _ in self.ev]
        if not pool:
            return "unknown"
        return max(pool, key=lambda e: PRIORITY.get(e[0], 0))[0]

    def evidence(self):
        ranked = sorted(self.ev, key=lambda e: (e[2], -PRIORITY.get(e[0], 0)))
        out = []
        for t, why, w in ranked:
            s = "%s -> %s%s" % (why, t, " (weak)" if w else "")
            if s not in out:
                out.append(s)
        return out


def _rx(name):
    return "^%s$" % re.escape(name).replace("\\-", "-").replace("\\_", "_")


def _steam_game(argv):
    for a in argv[1:]:
        m = re.match(r"^steam://rungameid/(\d+)$", a)
        if m:
            return m.group(1)
    return None


def _steam_client(env):
    for rel in ("steamrt64/libcef.so", "ubuntu12_64/libcef.so"):
        p = os.path.join(env.data_home, "Steam", rel)
        if os.path.isfile(p):
            return p
    return None


def detect_desktop(env, desktop_id, paths):
    """The record for one launcher. paths: its .desktop files in XDG order."""
    user_dir = os.path.join(env.data_home, "applications")
    user = [p for p in paths if p.startswith(user_dir + os.sep)]
    system = [p for p in paths if p not in user]
    path = system[0] if system else paths[0]
    entry = parse_desktop(path)
    key = desktop_id[:-len(".desktop")]
    rec = {
        "key": key, "desktop_id": desktop_id, "path": path,
        "name": entry.get("Name") or key,
        "overridden_by": user[0] if user and system else None,
        "user_only": not system,
        "nodisplay": entry.get("NoDisplay", "").lower() == "true",
    }
    if entry.get("Type", "Application") != "Application" or \
            entry.get("Hidden", "").lower() == "true":
        return None
    argv = exec_argv(entry.get("Exec", ""))
    fid = entry.get("X-Flatpak") or flatpak_id(argv)
    names = []
    wm = entry.get("StartupWMClass")
    for n in (wm, fid, key, os.path.basename(argv[0]) if argv and not fid else None):
        if n and n not in names and n not in ("env", "flatpak", "sh", "bash"):
            names.append(n)
    pr = Probe(env)
    rec["flatpak"] = None
    game = _steam_game(argv) if argv and os.path.basename(argv[0]) == "steam" else None
    if game:
        names = ["steam_app_%s" % game]
        pr.add("game", "Steam game %s (steam://rungameid)" % game)
        pr.mark("game", "Steam game %s" % game)
    elif fid:
        info = flatpak_app(env, fid)
        if info:
            rec["flatpak"] = {k: info[k] for k in ("installation", "runtime", "base", "command")
                              if k in info}
            pr.flatpak(info)
            cmd = flatpak_command(argv) or info.get("command")
            if cmd:
                b = cmd if cmd.startswith("/") else "/app/bin/" + cmd
                pr.binary(b, root=info["files"])
        else:
            rec["installed"] = False
    elif argv:
        exe = argv[0]
        if os.path.basename(exe) == "env":
            i = 1
            while i < len(argv) and ("=" in argv[i] and not argv[i].startswith("/")
                                     or argv[i].startswith("-")):
                i += 1
            if i < len(argv):
                argv = argv[i:]
                exe = argv[0]
        rt = root_target(argv)
        if rt:
            pr.mark("root", "%s in Exec" % rt[0])
            if rt[1]:
                exe = rt[1]
        why = game_argv(argv)
        if why:
            pr.mark("game", why)
        p = exe if os.path.isabs(exe) else _which(exe, env)
        if p and os.path.exists(p):
            if os.path.basename(exe) == "steam":
                cef = _steam_client(env)
                if cef:
                    pr.add("cef", "Steam client (steamwebhelper, %s)" % env.tilde(cef))
            pr.binary(p)
        else:
            rec["installed"] = False
    # TryExec (desktop entry spec): the entry is not usable when it is missing
    tx = entry.get("TryExec")
    if tx and not (os.path.exists(tx) if os.path.isabs(tx) else _which(tx, env)):
        rec["installed"] = False
    rec.setdefault("installed", True)
    rec["names"] = names
    rec["app_ids"] = [_rx(n) for n in names[:1]]
    rec["exec"] = pr.exec
    rec["toolkit"] = pr.best()
    rec["strong"] = any(t == rec["toolkit"] and not w for t, _, w in pr.ev)
    rec["evidence"] = pr.evidence()
    rec["fuses"] = pr.fuses
    rec["seen"] = sorted(pr.seen)
    rec["appimage"] = bool(pr.appimage)
    if rec["toolkit"] == "sdl":
        pr.mark("game", "SDL with no toolkit")
    classes = dict(pr.classes)
    allnames = names + [key, fid or ""]
    if any(re.search(rx, n) for rx in SENSITIVE for n in allnames if n):
        classes["sensitive"] = "password or secrets app"
    if any(re.search(rx, n) for rx in GAME_LAUNCHERS for n in allnames + [
            os.path.basename(argv[0]) if argv else ""] if n) and "game" not in classes:
        classes["game-launcher"] = "game launcher (its children are games)"
    cats = [c for c in entry.get("Categories", "").split(";") if c]
    if "Game" in cats and pr.gfx and not {"game", "game-launcher"} & set(classes):
        classes["game"] = "Categories=Game and links %s" % pr.gfx
    spawn = next((why for c, why in SPAWNER_CATEGORIES if c in cats), None) or next(
        (why for rx, why in SPAWNER_NAMES for n in allnames + [
            os.path.basename(pr.exec or ""), os.path.basename(argv[0]) if argv else ""]
         if n and re.search(rx, n)), None)
    if spawn:
        classes["spawner"] = "%s (starts other apps)" % spawn
    if "game" in classes and rec["toolkit"] != "game":
        rec["toolkit"] = "game"
        rec["evidence"] = ["%s -> game" % classes["game"]] + rec["evidence"]
    rec["classes"] = classes
    if rec["toolkit"] == "electron" and pr.exec:
        rec["vencord"] = _vencord(pr) if "discord" in key.lower() else None
    return rec


def _vencord(pr):
    for p in pr.seen:
        res = os.path.join(os.path.dirname(p), "resources")
        if os.path.isfile(os.path.join(res, "_app.asar")):
            return True
        if os.path.isfile(os.path.join(res, "app.asar")):
            return False
    return None


def scan(env):
    """Every launcher's record, sorted by key."""
    out = []
    for did, paths in desktop_files(env):
        rec = detect_desktop(env, did, paths)
        if rec is not None:
            out.append(rec)
    out.sort(key=lambda r: r["key"].lower())
    return out
