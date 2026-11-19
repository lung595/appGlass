"""The engine (docs/engine.md): fingerprints, the detect cache, per-app state
and the gate.

* Fingerprint: stat() and readlink() only, never a subprocess. It covers the
  .desktop files, every file the probe read (detect record "seen"), the
  flatpak deploy commit (readlink of <inst>/app/<id>/current/active) and, for
  apps that update themselves, the newest asar of an Electron app, Discord's
  app-* dir and Steam's client manifest.
* Cache: $XDG_CACHE_HOME/appglass/detect.json, {desktop_id: {fp, paths,
  record, evidence}}. A launcher whose fingerprint did not change keeps its
  record; only a new or changed one is probed again.
* Store: $XDG_STATE_HOME/appglass/engine.json, per app key: the last check
  (verify: fp, result, reason), failed launches (fails: fp, count), what
  made it run plain (plain: fp, reason), the notifications sent; the sticky
  game keys; the verify queue. A key in "plain" also has a marker file
  $XDG_STATE_HOME/appglass/plain/<key>: the launch wrappers read it and
  start the plain app. Nothing here is an owned file: no event removes
  glass files (S6), the engine only says what runs plain.
* Gate (spec 1.4): an injected route (a family with OPT_IN) needs a PASS for
  the current fingerprint; one checked on an older fingerprint is "stale"
  (opaque until checked again). Without any check yet, the user's explicit
  apps.<key>.enabled true keeps it on (the switch from before the engine);
  otherwise it is "waiting". A non-injecting route (theme, CSS, style
  plugin) goes live on strong static evidence, its check is queued.
"""

import hashlib
import json
import os
import re
import time

from . import detect, inputs

CACHE_VERSION = 3       # 2: the spawner class, more elevators, Categories=Game
                        # 3: IDEs, app and game launchers, game-category, a
                        #    binary not found yet ("missing", re-probed)
STORE_VERSION = 1
ROUTE_VERSION = 1
WAITING = "waiting for a check (injected route)"
# plain markers the gate does not read as a verdict: refresh sets them for
# an injected route that is not live but has its files (its wrapper) on disk
UNJUDGED = ("stale", "waiting")


# ---------------------------------------------------------------- fingerprints

def _sig(p):
    inputs.full(p)          # a directory's mtime counts here (inputs.py)
    try:
        st = os.stat(p)
    except OSError:
        return "-"
    return "%d:%d:%d" % (st.st_ino, st.st_size, st.st_mtime_ns)


def _newest(pattern_dir, rx):
    """name:mtime of the newest entry of pattern_dir matching rx, or ''."""
    try:
        names = [n for n in os.listdir(pattern_dir) if re.match(rx, n)]
    except OSError:
        return ""
    best = ""
    best_t = -1
    for n in names:
        try:
            t = os.stat(os.path.join(pattern_dir, n)).st_mtime_ns
        except OSError:
            continue
        if t > best_t:
            best, best_t = n, t
    return "%s:%d" % (best, best_t) if best else ""


def flatpak_id(rec):
    fp = rec.get("flatpak") if rec else None
    if not fp:
        return None
    for n in rec.get("names") or ():
        if n.count(".") >= 2:
            return n
    return None


# where a linked library is looked up (the ld.so defaults of the distros)
LIB_DIRS = ("/usr/lib64", "/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu", "/usr/lib",
            "/lib64", "/lib")
_WEBKIT_SO = re.compile(r"^links (libwebkit2gtk-4\.[01]\.so\S*) -> webkitgtk")


def _library(soname):
    """The file a soname resolves to in LIB_DIRS, with its signature, or ''."""
    for d in LIB_DIRS:
        p = os.path.join(d, soname)
        if os.path.exists(p):
            real = os.path.realpath(p)
            return "%s %s" % (real, _sig(real))
    return ""


def extras(env, rec):
    """The update markers detect does not read: [str]."""
    out = []
    if not rec:
        return out
    fid = flatpak_id(rec)
    if fid:
        for root in detect.flatpak_roots(env):
            try:
                out.append("commit " + os.readlink(os.path.join(root, "app", fid, "current",
                                                                "active")))
            except OSError:
                pass
    key = (rec.get("key") or "").lower()
    names = [n.lower() for n in rec.get("names") or ()]
    if rec.get("toolkit") == "electron" or rec.get("toolkit_static") == "electron":
        # an Electron app that updates its own asar (Obsidian: obsidian-1.9.x.asar)
        bases = [os.path.join(env.home, ".var", "app", fid, "config")] if fid else \
            [env.config_home]
        for b in bases:
            for n in set(names + [key]):
                sub = n.split(".")[-1]
                if sub:
                    hit = _newest(os.path.join(b, sub), r".*\.asar$")
                    if hit:
                        out.append("asar " + hit)
    if "discord" in key and not fid:
        hit = _newest(os.path.join(env.config_home, "discord"), r"^app-")
        if hit:
            out.append("discord " + hit.split(":")[0])
    if rec.get("toolkit") == "webkitgtk":
        # the webkit shim works inside WebKitGTK: its update is a new version
        # of the app for the check, though the app's own files do not change
        for ev in rec.get("evidence") or ():
            m = _WEBKIT_SO.match(ev)
            hit = _library(m.group(1)) if m else ""
            if hit:
                out.append("webkitgtk " + hit)
                break
    if "steam" in names or key == "steam" or rec.get("toolkit") == "cef":
        for d in (os.path.join(env.data_home, "Steam", "package"),
                  os.path.join(env.home, ".steam", "steam", "package")):
            hit = _newest(d, r"^steam_client_.*\.manifest$")
            if hit:
                out.append("steam " + hit)
                break
    return out


def fingerprint(env, rec, paths, owned=()):
    """owned: the files appglass wrote (its launcher overrides): an apply
    must not change the fingerprint it was made for (spec 1.2 self-trigger)."""
    h = hashlib.sha1()
    for p in paths:
        if p in owned:
            continue
        h.update(("D %s %s\n" % (p, _sig(p))).encode())
    if rec:
        for p in rec.get("seen") or ():
            h.update(("S %s %s\n" % (p, _sig(p))).encode())
        for p in rec.get("missing") or ():
            h.update(("M %s %s\n" % (p, _sig(p))).encode())
        for x in extras(env, rec):
            h.update(("X %s\n" % x).encode())
    return h.hexdigest()[:16]


# ---------------------------------------------------------------- the cache

def cache_path(env):
    return os.path.join(env.cache_home, "appglass", "detect.json")


def _load(p):
    try:
        with open(p, "rb") as f:
            d = json.loads(f.read().decode("utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, UnicodeDecodeError):
        return {}


def _write(env, p, doc):
    from .core import _atomic_write, _missing_dirs
    for d in _missing_dirs(os.path.dirname(p)):
        env.guard(d)
    env.guard(p)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    _atomic_write(p, (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode())


def owned_files(state):
    out = set()
    for o in (state.owners if state is not None else {}).values():
        out.update((o or {}).get("files", {}))
    return out


def scan(env, write=False, owned=()):
    """(records sorted by key, [changed desktop ids]): detect.scan with the
    fingerprint cache. write: save the cache when something changed."""
    doc = _load(cache_path(env))
    ents = doc.get("apps") if doc.get("version") == CACHE_VERSION else None
    ents = ents if isinstance(ents, dict) else {}
    new, out, changed = {}, [], []
    for did, paths in detect.desktop_files(env):
        e = ents.get(did)
        rec = None
        if isinstance(e, dict) and e.get("paths") == paths and \
                e.get("fp") == fingerprint(env, e.get("record"), paths, owned):
            rec, fp = e.get("record"), e["fp"]
        else:
            rec = detect.detect_desktop(env, did, paths)
            fp = fingerprint(env, rec, paths, owned)
            changed.append(did)
        if rec is not None:
            rec["fp"] = fp
        new[did] = {"fp": fp, "paths": paths, "record": rec,
                    "evidence": rec["evidence"] if rec else []}
        if rec is not None:
            out.append(rec)
    changed += sorted(set(ents) - set(new))
    if write and (changed or doc.get("version") != CACHE_VERSION):
        _write(env, cache_path(env), {"version": CACHE_VERSION, "apps": new})
    # the cache holds the plain record; callers may merge into a copy
    out = json.loads(json.dumps(out))
    out.sort(key=lambda r: r["key"].lower())
    return out, changed


# ---------------------------------------------------------------- the store

class Store:
    def __init__(self, env):
        self.env = env
        self.path = os.path.join(env.state_dir, "engine.json")
        try:
            with open(self.path, "rb") as f:
                raw = f.read()
        except OSError:
            raw = None
        d = _load(self.path)
        self._bad = None
        if raw is not None and d.get("version") != STORE_VERSION:
            d = self._reset(d, raw)
        self.data = {"version": STORE_VERSION, "apps": d.get("apps") or {},
                     "games": d.get("games") or {}, "queue": d.get("queue") or []}
        self._saved = None if self._bad is not None else json.dumps(self.data, sort_keys=True)

    def _reset(self, d, raw):
        """engine.json unreadable or of another version: its bytes go to
        engine.json.bad at the next save; the games and the paused apps
        stay (from the old file when it reads, else from the plain/ markers):
        a reset never takes an app back to glass."""
        self._bad = raw
        apps, games = {}, {}
        old = d.get("apps") if isinstance(d.get("apps"), dict) else {}
        for k, a in old.items():
            if isinstance(a, dict) and isinstance(a.get("plain"), dict) and \
                    isinstance(a["plain"].get("reason"), str):
                apps[k] = {"plain": a["plain"]}
        if isinstance(d.get("games"), dict):
            games = {k: v for k, v in d["games"].items() if isinstance(v, str)}
        mdir = os.path.join(self.env.state_dir, "plain")
        try:
            names = sorted(os.listdir(mdir))
        except OSError:
            names = []
        for k in names:
            if k in apps or k.startswith("."):
                continue
            try:
                with open(os.path.join(mdir, k)) as f:
                    why = f.read().strip()
            except (OSError, UnicodeDecodeError):
                why = ""
            if why == WAITING:
                # an injected app waiting for its check: still waiting
                apps[k] = {"plain": {"fp": None, "why": "waiting", "reason": why}}
                continue
            # plain until this app's next fingerprint (refresh sets it)
            apps[k] = {"plain": {"fp": None, "why": "kept",
                                 "reason": why or "paused before engine.json was reset"}}
        return {"apps": apps, "games": games}

    def app(self, key):
        return self.data["apps"].setdefault(key, {})

    def get(self, key):
        return self.data["apps"].get(key) or {}

    @property
    def plain(self):
        return {k: a["plain"] for k, a in self.data["apps"].items() if a.get("plain")}

    def set_plain(self, key, fp, reason, why=None):
        a = self.app(key)
        p = a.get("plain") or {}
        if p.get("fp") != fp or p.get("reason") != reason or p.get("why") != why:
            a["plain"] = {"fp": fp, "reason": reason}
            if why:
                a["plain"]["why"] = why

    def clear_plain(self, key):
        self.data["apps"].get(key, {}).pop("plain", None)

    def queue(self, key):
        if key not in self.data["queue"]:
            self.data["queue"].append(key)

    def dequeue(self, key):
        if key in self.data["queue"]:
            self.data["queue"].remove(key)

    def dirty(self):
        return json.dumps(self.data, sort_keys=True) != self._saved

    def save(self, dry=False):
        """Write engine.json and the plain/ markers (only when changed)."""
        if dry or not self.dirty():
            return False
        env = self.env
        empty = not (self.data["games"] or self.data["queue"] or
                     any(self.data["apps"].values()))
        if empty and not os.path.exists(self.path):
            return False
        if self._bad is not None:
            from .core import _atomic_write
            env.guard(self.path + ".bad")
            _atomic_write(self.path + ".bad", self._bad)
            self._bad = None
        _write(env, self.path, self.data)
        self._saved = json.dumps(self.data, sort_keys=True)
        self.sync_markers()
        return True

    def sync_markers(self):
        env = self.env
        d = os.path.join(env.state_dir, "plain")
        want = set(self.plain)
        try:
            have = set(os.listdir(d))
        except OSError:
            have = set()
        for k in have - want:
            p = os.path.join(d, k)
            env.guard(p)
            try:
                os.remove(p)
            except OSError:
                pass
        if want - have:
            env.guard(d)
            os.makedirs(d, exist_ok=True)
        for k in want - have:
            if "/" in k or k.startswith("."):
                continue
            p = os.path.join(d, k)
            env.guard(p)
            with open(p, "w") as f:
                f.write(self.plain[k]["reason"] + "\n")


def marker(env, key):
    return os.path.join(env.state_dir, "plain", key)


# ---------------------------------------------------------------- per app

def store(app):
    s = getattr(app, "_engine_store", None)
    if s is None:
        s = app._engine_store = Store(app.env)
    return s


def records(app, write=None):
    """The detect records (cached) with learned.json merged and the sticky
    game class applied. Memoised per run."""
    from . import learn
    recs = getattr(app, "_engine_records", None)
    if recs is not None:
        return recs
    if write is None:
        write = bool(getattr(app, "from_hook", False)) and not getattr(app, "dry_run", False)
    recs, changed = scan(app.env, write=write, owned=owned_files(app.state))
    recs = learn.merge(recs, learn.load(app.env))
    seen_ids(app, recs)
    sticky(app, recs, save=write)
    app._engine_records, app._engine_changed = recs, changed
    return recs


def seen_ids(app, recs):
    """The app-id a check saw for an app (its window is often named after
    its binary, not its launcher): one more app-id regex of its record, for
    the niri rule, the launch check and the game guard (E2)."""
    st = store(app)
    for r in recs:
        seen = ((st.get(r["key"]).get("verify") or {}).get("app_id"))
        if not isinstance(seen, str) or not re.match(r"^[\w.+-]{1,200}$", seen):
            continue
        ids = r.setdefault("app_ids", [])
        if not any(re.search(rx, seen) for rx in ids):
            ids.append(detect._rx(seen))


def sticky(app, recs, save=False):
    """A game signal once seen wins forever (spec 1.3)."""
    st = store(app)
    games = st.data["games"]
    for r in recs:
        cls = r.setdefault("classes", {})
        if r.get("toolkit") == "game" or "game" in cls:
            if r["key"] not in games:
                games[r["key"]] = cls.get("game") or "game"
        if r["key"] in games:
            cls.setdefault("game", "game seen before (%s): never touched" % games[r["key"]])
            cls.pop("game-launcher", None)
            if r.get("toolkit") != "game":
                r["toolkit_static"] = r.get("toolkit")
                r["toolkit"] = "game"


def record_for(app, key):
    for r in records(app):
        if r["key"] == key:
            return r
    return None


def gate(st, rec, injected, explicit):
    """(state, reason): glass | waiting | stale | opaque."""
    key, fp = rec.get("key"), rec.get("fp")
    a = st.get(key)
    p = a.get("plain")
    if p and not injected and (p.get("reason") or "").startswith("check failed"):
        p = None        # a Native route is never paused by its check (refresh drops it)
    if p and (p.get("fp") == fp and p.get("why") not in UNJUDGED or p.get("why") == "kept"):
        return "opaque", p["reason"]
    v = a.get("verify")
    if v:
        if v.get("fp") == fp:
            if v.get("result") == "pass":
                return "glass", "checked (%s)" % v.get("at", "")
            if v.get("result") == "unverifiable":
                # spec 1.7: an injected route stays off, a theme route on;
                # the user's own on stays on (verify tells them, once)
                if injected and explicit:
                    return "glass", "enabled by you (could not be checked: %s)" % v.get(
                        "reason", "?")
                if injected:
                    return "opaque", "could not be checked: %s" % v.get("reason", "?")
                return "glass", None
            if not injected:
                # a Native route is never held opaque by its check
                return "glass", "check failed, glass kept (Native): %s" % v.get("reason", "?")
            return "opaque", "check failed: %s" % v.get("reason", "?")
        if injected:
            return "stale", "updated since the last check: opaque until it is checked again"
    if injected:
        if explicit:
            return "glass", "enabled by you (not checked yet)"
        return "waiting", WAITING
    return "glass", None


def Gate(app):
    """resolve()'s gate for this run: fn(rec, injected, explicit)."""
    st = store(app)
    return lambda rec, injected, explicit: gate(st, rec, injected, explicit)


# ---------------------------------------------------------------- engine pass

def family_keys(app, name):
    fam = app.families.get(name)
    return list(getattr(fam, "KEYS", ()) or ())


def explicit(app, key):
    own = (app.settings.get("apps", {}) or {}).get(key)
    if isinstance(own, dict) and "enabled" in own:
        return bool(own["enabled"])
    return None


def explicit_on(app, fam, key):
    """The user switched this injected route on themselves (the family's
    own switch, else the app's; a generic family: the app's): what
    adapters.resolve calls explicit (adapters.switch)."""
    from . import adapters
    apps = app.settings.get("apps", {}) or {}
    generic = getattr(app.families.get(fam), "GENERIC", False)
    return adapters.switch(apps.get(fam), apps.get(key), generic) is True


def family_gate(app, name):
    """None when an OPT_IN (injected) family may go live, else (state,
    reason). Its keys come from its KEYS; a key with no launcher found is
    judged without a fingerprint."""
    fam = app.families.get(name)
    if not getattr(fam, "OPT_IN", False):
        return None
    if getattr(fam, "GENERIC", False) and not family_keys(app, name):
        # a generic injected family (webkit): the gate is per app, its
        # ctx.records() are the apps that passed (or that you switched on)
        return None
    st = store(app)
    fam_on = explicit(app, name)
    results = []
    for key in family_keys(app, name):
        rec = record_for(app, key) or {"key": key, "fp": None}
        on = explicit(app, key)
        on = fam_on if on is None else on
        results.append(gate(st, rec, True, bool(on)))
    if not results:
        return None if fam_on else ("waiting", "waiting for a check (injected route)")
    if any(s == "glass" for s, _ in results):
        return None
    return results[0]


def refresh(app, dry=False, families=None):
    """One engine pass over the records: the verify queue and the plain
    markers follow the gate. families: a typed apply queues checks only
    for the families it applied (None: every family, the hook run).
    Returns the keys whose state changed."""
    from . import adapters
    st = store(app)
    recs = records(app)
    g = Gate(app)
    changed = []
    for r in recs:
        if not r.get("installed") or r.get("nodisplay"):
            continue
        key, fp = r["key"], r.get("fp")
        kept = st.get(key).get("plain")
        if kept and kept.get("why") == "kept" and not dry:
            # a marker kept over an engine.json reset: plain for this
            # fingerprint, glass again at the next one (S7)
            kept["fp"] = fp
            kept.pop("why")
        route = adapters.resolve(r, app.families, app.settings, gate=g)
        if families is not None and route.get("family") not in families:
            continue
        if route.get("family") and not route.get("injected") and not dry and \
                ((st.get(key).get("plain") or {}).get("reason") or "").startswith("check failed"):
            # a Native route is never paused by its check: a marker an
            # older failed check left goes (on at once, README)
            st.clear_plain(key)
            changed.append(key)
        a = st.get(key)
        state = route.get("state")
        injected = route.get("injected")
        if state == "stale":
            if (a.get("plain") or {}).get("fp") != fp:
                st.set_plain(key, fp, "updated: opaque until it is checked again", why="stale")
                changed.append(key)
            st.queue(key)
        elif state == "glass" and injected:
            if (a.get("plain") or {}).get("why") in UNJUDGED:
                st.clear_plain(key)
                changed.append(key)
            # on by the user's own switch: consent, not a check (S4). It is
            # checked like any other, so the next update makes it stale
            v = a.get("verify")
            if not v or v.get("fp") != fp:
                st.queue(key)
        elif state == "waiting" and route.get("enabled") is not False:
            st.queue(key)
            if injected and route.get("family") in app.state.owners:
                # its wrapper is on disk (a check record lost, an engine.json
                # reset): it starts the plain app and niri keeps the window
                # opaque until the check passes (E3)
                had = a.get("plain") or {}
                if had.get("fp") != fp or had.get("why") != "waiting":
                    st.set_plain(key, fp, WAITING, why="waiting")
                    changed.append(key)
        elif state == "opaque" and injected and route.get("family") in app.state.owners \
                and not a.get("plain"):
            # could not be checked (and not switched on by you): the same,
            # plain for this fingerprint
            st.set_plain(key, fp, route.get("reason") or "opaque")
            changed.append(key)
        elif state == "glass" and route.get("family") and not injected:
            if a.get("plain") and a["plain"].get("fp") != fp:
                st.clear_plain(key)      # plain until the next fingerprint (S7)
                changed.append(key)
            v = a.get("verify")
            if not v or v.get("fp") != fp:
                st.queue(key)
    st.data["queue"] = [k for k in st.data["queue"] if record_for(app, k)]
    st.save(dry=dry)
    return changed


# ---------------------------------------------------------------- fail / notify

def notify(app, key, title, body):
    """One desktop notification (DMS shows it). In a sandbox only the stub
    named by APPGLASS_NOTIFY runs."""
    env = app.env
    if env.sandbox:
        cmd = env.environ.get("APPGLASS_NOTIFY")
        if not cmd:
            return False
    else:
        cmd = env.which("notify-send")
        if not cmd:
            return False
    try:
        env.run([cmd, "-a", "appGlass", title, body], timeout=10)
    except Exception:
        return False
    return True


def app_name(app, key):
    r = record_for(app, key)
    return (r or {}).get("name") or key


def fail(app, key, reason, fp=None):
    """One failed launch or check for key. Two in a row on the same
    fingerprint: plain until the next fingerprint, one notification."""
    st = store(app)
    if fp is None:
        r = record_for(app, key)
        fp = r.get("fp") if r else None
    a = st.app(key)
    f = a.get("fails") or {}
    if f.get("fp") != fp or not isinstance(f.get("count"), int):
        f = {"fp": fp, "count": 0}
    f["count"] += 1
    f["reason"] = reason
    a["fails"] = f
    paused = False
    if f["count"] >= 2:
        paused = _pause(app, key, fp, "two failed launches: %s" % reason, "launch")
    st.save()
    return f["count"], paused


def ok(app, key, fp=None):
    st = store(app)
    a = st.get(key)
    if a.get("fails"):
        st.app(key).pop("fails", None)
        st.save()


PAUSED = {
    "update": "%s: glass paused after an update",
    "check": "%s: glass paused, its glass check failed",
    "launch": "%s: glass paused after two failed launches",
}


def _pause(app, key, fp, reason, cause):
    """Plain for this fingerprint, one notification. cause: update (a check
    failed on a new version of an app checked before), check (its first
    check failed), launch (two launches with no window)."""
    st = store(app)
    a = st.app(key)
    st.set_plain(key, fp, reason)
    return notify_once(app, key, fp, PAUSED[cause] % app_name(app, key),
                       "%s starts without glass from its next launch until its next "
                       "update. %s" % (app_name(app, key), reason))


def notify_once(app, key, fp, title, body, tag=""):
    a = store(app).app(key)
    sent = a.setdefault("notified", [])
    if tag + (fp or "") in sent:
        return True
    sent.append(tag + (fp or ""))
    del sent[:-5]
    notify(app, key, title, body)
    return True


def verified(app, key, fp, result, reason="", app_id=None, injected=True):
    """Record a check result for (key, fp). app_id: the app-id of the
    window the check found (records() adds it to the app's app-ids).
    injected False (a Native route: on at once, README): a FAIL is recorded
    and shown, never paused (no plain marker, no notification), and a plain
    marker an earlier failed check left goes."""
    st = store(app)
    a = st.app(key)
    prev = a.get("verify")
    a["verify"] = {"fp": fp, "result": result, "reason": reason, "route": ROUTE_VERSION,
                   "at": time.strftime("%Y-%m-%d %H:%M")}
    seen = app_id or (prev or {}).get("app_id")
    if seen:
        a["verify"]["app_id"] = seen
    st.dequeue(key)
    if result == "pass":
        if (a.get("plain") or {}).get("fp") in (fp, None) or \
                (a.get("plain") or {}).get("why") in UNJUDGED:
            st.clear_plain(key)
        a.pop("fails", None)
    elif not injected:
        if ((a.get("plain") or {}).get("reason") or "").startswith("check failed"):
            st.clear_plain(key)
    else:
        _pause(app, key, fp, "check failed: %s" % reason,
               "update" if prev and prev.get("fp") != fp else "check")
    st.save()


def destroy(env):
    """remove (everything): the engine cache goes with the state dir."""
    import shutil
    p = cache_path(env)
    # the toolchain versions (shims._cached) and the hook digest (inputs.py)
    # are caches of the same kind
    for f in (p, os.path.join(os.path.dirname(p), "toolchain.json"), inputs.path(env)):
        if os.path.exists(f):
            env.guard(f)
            os.remove(f)
    for k in (os.path.join(os.path.dirname(p), "keys"), os.path.dirname(inputs.path(env))):
        if os.path.isdir(k):
            env.guard(k)
            shutil.rmtree(k)
    try:
        os.rmdir(os.path.dirname(p))
    except OSError:
        pass
