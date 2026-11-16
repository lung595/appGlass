"""A sandbox for the shim adapters: DMS colours and niri config, a fake
toolchain, system launchers under <root>/usr/share/applications, flatpak
exports under <root>/flatpak/exports/share/applications and fake app
binaries in <root>/usr/bin.

    w = ShimWorld()
    w.launcher("vlc.desktop", text)             # a system launcher
    w.launcher("x.desktop", text, flatpak=True)  # a flatpak export
    w.run("apply", "--only", "qtstyle")         # sb.run with the world env
"""

import os

from fixtures.sandbox import Sandbox
from fixtures.toolchain import Toolchain


class ShimWorld:
    def __init__(self, bins=()):
        self.sb = sb = Sandbox()
        sb.seed_dms()
        sb.seed_niri()
        self.usr = sb.path("usr")
        self.bin = os.path.join(self.usr, "bin")
        os.makedirs(self.bin)
        for b in bins:
            self.exe(b)
        sb.env["XDG_DATA_DIRS"] = os.path.join(self.usr, "share")
        sb.env["FLATPAK_SYSTEM_DIR"] = sb.path("flatpak")
        sb.env["FLATPAK_USER_DIR"] = sb.path("no-user-flatpak")
        self.tc = Toolchain(sb, [self.bin])

    def exe(self, name, text="#!/bin/sh\nexit 0\n"):
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, 0o755)
        return p

    def launcher(self, desktop_id, text, flatpak=False):
        base = (self.sb.path("flatpak", "exports", "share") if flatpak
                else os.path.join(self.usr, "share"))
        return self.sb.write(os.path.join("applications", desktop_id), text, base=base)

    def user(self, *p):
        return os.path.join(self.sb.home, *p)

    def hand(self, rel, text, mode=0o644):
        p = self.user(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb" if isinstance(text, bytes) else "w") as f:
            f.write(text)
        os.chmod(p, mode)
        return p

    def run(self, *argv, **kw):
        return self.sb.run(*argv, **kw)

    def state(self):
        return self.sb.json(os.path.join(self.sb.state, "appglass", "state.json"))

    def mode(self, p):
        return os.stat(p).st_mode & 0o777

    def cleanup(self):
        self.tc.cleanup()
        self.sb.cleanup()
