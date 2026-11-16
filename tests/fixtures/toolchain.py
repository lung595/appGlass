"""A fake host toolchain (gcc, g++, moc, pkg-config) in a sandbox bin dir.

    tc = Toolchain(sb, bins)  # sb.env PATH = bins + the tool dir
    tc.calls()                # ["g++ ...", "moc ..."] in order
    tc.qt = "6.12.0"          # the next pkg-config --modversion answer

The compilers write "FAKE-BUILD <out>\\n" plus the sha256 of every source
named on the command line into the -o file, so a changed source gives a
changed artifact.
"""

import os
import shutil
import sys
import tempfile
import textwrap

CC = textwrap.dedent("""\
    #!PYTHON
    import hashlib, os, sys
    d = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(d) == "libexec":
        d = os.path.dirname(d)
    with open(os.path.join(d, "calls"), "a") as f:
        f.write(os.path.basename(sys.argv[0]) + " " + " ".join(sys.argv[1:]) + "\\n")
    if sys.argv[1:] == ["--version"]:
        print("fake-" + os.path.basename(sys.argv[0]) + " 1.0"); sys.exit(0)
    if os.path.exists(os.path.join(d, "fail")):
        print("fake compile error", file=sys.stderr); sys.exit(1)
    out = sys.argv[sys.argv.index("-o") + 1]
    h = hashlib.sha256()
    for a in sys.argv[1:]:
        if a.endswith((".c", ".cpp")) and os.path.exists(a):
            h.update(open(a, "rb").read())
    with open(out, "w") as f:
        f.write("FAKE-BUILD %s %s\\n" % (os.path.basename(out), h.hexdigest()))
    """)

PKG = textwrap.dedent("""\
    #!/bin/sh
    d=$(dirname "$0")
    echo "pkg-config $*" >> "$d/calls"
    case "$1" in
    --modversion) cat "$d/qt-version";;
    --variable=libexecdir) echo "$d/libexec";;
    --cflags-only-I) echo "-I/fake/qt6";;
    --cflags) echo "-I/fake/qt6 -lQt6Fake";;
    esac
    """)


# the host tools the fake tools and the wrappers need, linked next to them
# so PATH can leave out /usr/bin (and the real apps in it)
HOST = ("sh", "cat", "dirname", "jq", "sed", "env", "flock", "sort", "ls", "tail", "sleep",
        "readlink", "grep", "touch", "mkdir", "stat", "id", "tr", "cut", "mv", "rm", "head")


class Toolchain:
    """Lives outside the sandbox root (its call log is not a sandbox
    write); PATH becomes <bins>:<toolbin>."""

    def __init__(self, sb, bins=()):
        self.dir = tempfile.mkdtemp(prefix="appglass-tools-")
        os.makedirs(os.path.join(self.dir, "libexec"))
        for name, text in (("gcc", CC), ("g++", CC), ("pkg-config", PKG),
                           ("libexec/moc", CC)):
            p = os.path.join(self.dir, name)
            with open(p, "w") as f:
                f.write(text.replace("PYTHON", sys.executable))
            os.chmod(p, 0o755)
        for h in HOST:
            real = shutil.which(h)
            if real:
                os.symlink(real, os.path.join(self.dir, h))
        os.symlink(sys.executable, os.path.join(self.dir, "python3"))
        self.qt = "6.11.2"
        sb.env["PATH"] = os.pathsep.join(list(bins) + [self.dir])

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    @property
    def qt(self):
        with open(os.path.join(self.dir, "qt-version")) as f:
            return f.read().strip()

    @qt.setter
    def qt(self, v):
        with open(os.path.join(self.dir, "qt-version"), "w") as f:
            f.write(v + "\n")

    def fail(self, on=True):
        p = os.path.join(self.dir, "fail")
        if on:
            open(p, "w").close()
        elif os.path.exists(p):
            os.remove(p)

    def calls(self):
        p = os.path.join(self.dir, "calls")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return f.read().splitlines()

    def builds(self):
        return [c for c in self.calls() if c.split()[0] in ("gcc", "g++")
                and "--version" not in c]
