"""A throwaway HOME + XDG tree with APPGLASS_SANDBOX set, for unit tests.

    sb = Sandbox()                 # tempfile.mkdtemp
    sb.seed_dms(); sb.seed_niri(); sb.seed("alacritty/alacritty.toml", "alacritty/alacritty.toml")
    code, out, err = sb.run("apply", "--only", "alacritty", assume="alacritty")
    sb.tree_hash()                 # sha256 over every path, type and content
    sb.cleanup()
"""

import hashlib
import io
import os
import shutil
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
        root = root or self.root
        h = hashlib.sha256()
        for dp, dns, fns in os.walk(root):
            dns.sort()
            rel = os.path.relpath(dp, root)
            h.update(b"D " + rel.encode() + b"\n")
            for fn in sorted(fns):
                p = os.path.join(dp, fn)
                r = os.path.relpath(p, root).encode()
                if os.path.islink(p):
                    h.update(b"L " + r + b" " + os.readlink(p).encode() + b"\n")
                else:
                    with open(p, "rb") as f:
                        h.update(b"F " + r + b" " + hashlib.sha256(f.read()).digest() + b"\n")
        return h.hexdigest()

    def files(self):
        out = []
        for dp, dns, fns in os.walk(self.root):
            for fn in fns:
                out.append(os.path.relpath(os.path.join(dp, fn), self.root))
        return sorted(out)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)
