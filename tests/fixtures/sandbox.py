"""A throwaway HOME + XDG tree with APPGLASS_SANDBOX set, for unit tests.

    sb = Sandbox()                 # tempfile.mkdtemp
    sb.seed_dms(); sb.seed_niri(); sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
    code, out, err = sb.run("apply", "--only", "alacritty", assume="alacritty")
    sb.tree_hash()                 # sha256 over every path, type, mode and content
    sb.cleanup()
"""

import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from appglass import core  # noqa: E402


def fixture(*p):
    return os.path.join(HERE, *p)


class Sandbox:
    def __init__(self, prefix="appglass-test-"):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix=prefix))
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)
        self.config = os.path.join(self.home, ".config")
        self.data = os.path.join(self.home, ".local", "share")
        self.state = os.path.join(self.home, ".local", "state")
        self.cache = os.path.join(self.home, ".cache")
        for d in (self.config, self.data, self.state, self.cache):
            os.makedirs(d)
        self.env = {
            "HOME": self.home,
            "XDG_CONFIG_HOME": self.config,
            "XDG_DATA_HOME": self.data,
            "XDG_STATE_HOME": self.state,
            "XDG_CACHE_HOME": self.cache,
            "APPGLASS_SANDBOX": self.root,
            "PATH": os.environ.get("PATH", os.defpath),
        }

    # seeding
    def write(self, rel, text, base=None):
        p = os.path.join(base or self.config, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w" if isinstance(text, str) else "wb") as f:
            f.write(text)
        return p

    def seed(self, fixture_rel, rel, base=None):
        with open(fixture(fixture_rel), "rb") as f:
            return self.write(rel, f.read(), base)

    def seed_dms(self, light=False):
        self.seed("dms/settings.json", "dms/settings.json")
        self.seed("dms/dms-colors-light.json" if light else "dms/dms-colors.json",
                  "dms/dms-colors.json", base=self.cache)

    def set_level(self, v):
        """Set the content level the way the user does: the opacity of the DMS
        Glass blur window rule (when seeded), and foregroundLayerTransparency."""
        sp = os.path.join(self.config, "dms", "settings.json")
        try:
            with open(sp) as f:
                s = json.load(f)
        except (OSError, ValueError):
            s = {}
        s["foregroundLayerTransparency"] = v
        self.write("dms/settings.json", json.dumps(s))
        rp = os.path.join(self.config, "niri", "dms", "windowrules.kdl")
        if os.path.exists(rp):
            with open(rp) as f:
                t = f.read()
            self.write("niri/dms/windowrules.kdl",
                       re.sub(r"opacity 0\.\d+", "opacity %.2f" % v, t, count=1))

    def seed_niri(self):
        self.seed("niri/config.kdl", "niri/config.kdl")
        self.seed("niri/dms/windowrules.kdl", "niri/dms/windowrules.kdl")

    def path(self, *p):
        return os.path.join(self.root, *p)

    def cfg(self, *p):
        return os.path.join(self.config, *p)

    def read(self, p):
        with open(p, "r") as f:
            return f.read()

    def readb(self, p):
        with open(p, "rb") as f:
            return f.read()

    def json(self, p):
        import json
        with open(p) as f:
            return json.load(f)

    # running
    def run(self, *argv, assume=None, assume_not=None, env=None):
        e = dict(self.env)
        if assume is not None:
            e["APPGLASS_ASSUME_INSTALLED"] = assume
        if assume_not is not None:
            e["APPGLASS_ASSUME_NOT_INSTALLED"] = assume_not
        e.update(env or {})
        out, err = io.StringIO(), io.StringIO()
        code = core.main(list(argv), environ=e, out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    # checking
    def tree_hash(self, root=None):
        """Every entry under root, dirs and links included: its path, its
        lstat type and mode, and the link target or the file's sha256."""
        root = root or self.root
        h = hashlib.sha256()
        for dp, dns, fns in os.walk(root):
            dns.sort()
            for n in sorted(dns + fns):
                p = os.path.join(dp, n)
                r = os.path.relpath(p, root).encode()
                st = os.lstat(p)
                h.update(b"%s %o " % (r, st.st_mode))
                if stat.S_ISLNK(st.st_mode):
                    h.update(b"L " + os.readlink(p).encode())
                elif stat.S_ISREG(st.st_mode):
                    with open(p, "rb") as f:
                        h.update(b"F " + hashlib.sha256(f.read()).digest())
                h.update(b"\n")
        return h.hexdigest()

    def files(self):
        out = []
        for dp, dns, fns in os.walk(self.root):
            for fn in fns:
                out.append(os.path.relpath(os.path.join(dp, fn), self.root))
        return sorted(out)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)
