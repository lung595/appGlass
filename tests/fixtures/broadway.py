"""A private GTK3 broadway display for style tests: no compositor, no TCP
port (the web server is a unix socket), its own XDG_RUNTIME_DIR."""

import os
import shutil
import subprocess
import tempfile

DAEMON = "broadwayd"


def available():
    return shutil.which(DAEMON) is not None


class Broadway:
    def __init__(self, display=":7"):
        self.rt = tempfile.mkdtemp(prefix="agl-bw-")
        os.chmod(self.rt, 0o700)
        self.display = display
        self.proc = subprocess.Popen(
            [DAEMON, "-u", os.path.join(self.rt, "http.sock"), display],
            env={"PATH": os.environ.get("PATH", ""), "XDG_RUNTIME_DIR": self.rt},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        # the display socket is abstract (not in rt): wait for its announcement
        line = self.proc.stdout.readline()
        if not line.startswith("Listening on"):
            self.close()
            raise RuntimeError("broadwayd did not start: %s" % line)
        self.env = {"GDK_BACKEND": "broadway", "BROADWAY_DISPLAY": display,
                    "XDG_RUNTIME_DIR": self.rt}

    def close(self):
        self.proc.stdout.close()
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        shutil.rmtree(self.rt, ignore_errors=True)
