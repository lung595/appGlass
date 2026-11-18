"""settings.json: the user's choices (levels, fallback, per-app switches).

$XDG_CONFIG_HOME/appglass/settings.json is written only by appglass itself
(``appglass set`` or ``appglass sync --settings-file F``), atomically and
validated. A missing file means the defaults below.

    {"version": 1, "enabled": true,
     "levels": {"content": null, "bar": null},
     "fallback": {"mode": "opaque", "value": 0.70, "inactive": null},
     "inactive": {"enabled": true, "factor": 0.90, "durationMs": 180,
                  "easing": "ease-out-cubic", "instantFallback": false},
     "apps": {"steam": {"enabled": false, "route": "cdp"}}}

levels.content  null = follow DMS (the Glass blur window rule opacity, then
                foregroundLayerTransparency, then 0.60); else 0.20..1.00
levels.bar      null = max(0.65, content); else content..1.00
fallback.mode   how niri treats windows appglass cannot glass:
                "opaque" (default): a catch-all opacity 1.0, text sharp;
                "value": a catch-all opacity fallback.value (0.50..1.00);
                "off": no rule, the DMS opacity applies to them
fallback.inactive
                null, or a niri opacity (0.30..1.00) for every glass window
                that is not focused (instant, text fades too; overrides
                inactive.instantFallback); while the inactive fade is on,
                the apps that fade their own background are left out
inactive        unfocused windows a little more transparent, faded
                (appglass/inactive.py): enabled, factor 0.80..1.00 (the
                content level is multiplied by it, never below 0.60),
                durationMs 0..400, easing ease-out-cubic/ease-in-out/linear,
                instantFallback (an instant niri rule for apps with no fade)
apps.<key>      {"enabled": bool, "route": str}: per app or family switch
                (key = a family/adapter name or a detected app key).
                Forced and Mod families are on by default and go live once
                their hidden check passes; enabled false switches one off.

When the DMS plugin is installed and enabled, its settings page is the one
writer: ``appglass set`` refuses (the plugin calls ``sync --settings-file``).
"""

import copy
import json
import os
import re

from . import inactive as _inactive

VERSION = 1
FALLBACK_MODES = ("opaque", "value", "off")
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
PLUGIN_ID = "appGlass"

DEFAULTS = {
    "version": VERSION,
    "enabled": True,
    "levels": {"content": None, "bar": None},
    "fallback": {"mode": "opaque", "value": 0.70, "inactive": None},
    "inactive": dict(_inactive.DEFAULTS),
    "apps": {},
}


class SettingsError(ValueError):
    pass


def path(env):
    return env.config_path("appglass", "settings.json")


def _num(v, what, lo, hi, nullable=False):
    if v is None and nullable:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SettingsError("%s must be a number%s, not %s"
                            % (what, " or null" if nullable else "", json.dumps(v)))
    v = float(v)
    if not (lo <= v <= hi):
        raise SettingsError("%s must be between %.2f and %.2f, not %s" % (what, lo, hi, v))
    return round(v, 4)


def _obj(v, what):
    if not isinstance(v, dict):
        raise SettingsError("%s must be an object" % what)
    return v


def _only(d, allowed, what):
    bad = sorted(k for k in d if k not in allowed)
    if bad:
        raise SettingsError("unknown key%s in %s: %s"
                            % ("s" if len(bad) > 1 else "", what, ", ".join(bad)))


def validate(obj):
    """A full, normalised copy of obj (defaults filled in), or SettingsError."""
    obj = _obj(obj, "settings")
    _only(obj, DEFAULTS, "settings")
    out = copy.deepcopy(DEFAULTS)
    v = obj.get("version", VERSION)
    if v != VERSION:
        raise SettingsError("version must be %d, not %s" % (VERSION, json.dumps(v)))
    if "enabled" in obj:
        if not isinstance(obj["enabled"], bool):
            raise SettingsError("enabled must be true or false")
        out["enabled"] = obj["enabled"]
    lv = _obj(obj.get("levels", {}), "levels")
    _only(lv, DEFAULTS["levels"], "levels")
    c = _num(lv.get("content"), "levels.content", 0.2, 1.0, nullable=True)
    b = _num(lv.get("bar"), "levels.bar", 0.2, 1.0, nullable=True)
    if c is not None and b is not None and b < c:
        raise SettingsError("levels.bar (%s) must not be below levels.content (%s)" % (b, c))
    out["levels"] = {"content": c, "bar": b}
    fb = _obj(obj.get("fallback", {}), "fallback")
    _only(fb, DEFAULTS["fallback"], "fallback")
    mode = fb.get("mode", "opaque")
    if mode == "0.70":          # the design's name for the per-value mode
        mode = "value"
    if mode not in FALLBACK_MODES:
        raise SettingsError("fallback.mode must be one of %s, not %s"
                            % ("/".join(FALLBACK_MODES), json.dumps(mode)))
    out["fallback"] = {
        "mode": mode,
        "value": _num(fb.get("value", 0.70), "fallback.value", 0.5, 1.0),
        "inactive": _num(fb.get("inactive"), "fallback.inactive", 0.3, 1.0, nullable=True),
    }
    ia = _obj(obj.get("inactive", {}), "inactive")
    _only(ia, DEFAULTS["inactive"], "inactive")
    ina = dict(DEFAULTS["inactive"])
    for k in ("enabled", "instantFallback"):
        if k in ia:
            if not isinstance(ia[k], bool):
                raise SettingsError("inactive.%s must be true or false" % k)
            ina[k] = ia[k]
    if "factor" in ia:
        ina["factor"] = _num(ia["factor"], "inactive.factor", *_inactive.FACTOR_RANGE)
    if "durationMs" in ia:
        d = ia["durationMs"]
        lo, hi = _inactive.DURATION_RANGE
        if isinstance(d, float) and d.is_integer():
            d = int(d)
        if isinstance(d, bool) or not isinstance(d, int) or not lo <= d <= hi:
            raise SettingsError("inactive.durationMs must be a whole number of ms "
                                "between %d and %d, not %s" % (lo, hi, json.dumps(d)))
        ina["durationMs"] = d
    if "easing" in ia:
        if ia["easing"] not in _inactive.EASINGS:
            raise SettingsError("inactive.easing must be one of %s, not %s"
                                % ("/".join(_inactive.EASINGS), json.dumps(ia["easing"])))
        ina["easing"] = ia["easing"]
    out["inactive"] = ina
    apps = _obj(obj.get("apps", {}), "apps")
    for k, a in apps.items():
        if not _KEY.match(k):
            raise SettingsError("apps: bad app key %s" % json.dumps(k))
        a = _obj(a, "apps.%s" % k)
        _only(a, ("enabled", "route"), "apps.%s" % k)
        e = {}
        if "enabled" in a:
            if not isinstance(a["enabled"], bool):
                raise SettingsError("apps.%s.enabled must be true or false" % k)
            e["enabled"] = a["enabled"]
        if "route" in a:
            r = a["route"]
            if not isinstance(r, str) or not _KEY.match(r):
                raise SettingsError("apps.%s.route must be a short name" % k)
            e["route"] = r
        out["apps"][k] = e
    return out


def load(env):
    """(settings, error). A missing file gives the defaults; an unreadable or
    invalid one gives the defaults and the reason."""
    p = path(env)
    try:
        with open(p, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return copy.deepcopy(DEFAULTS), None
    except OSError as ex:
        return copy.deepcopy(DEFAULTS), "%s: %s" % (p, ex.strerror or ex)
    try:
        return validate(json.loads(raw.decode("utf-8"))), None
    except (ValueError, UnicodeDecodeError) as ex:
        return copy.deepcopy(DEFAULTS), "%s: %s" % (p, ex)


def dumps(s):
    return json.dumps(s, indent=2, sort_keys=True) + "\n"


def save(env, s):
    """Validate and write atomically. Returns True when the bytes changed."""
    from .core import _atomic_write, _missing_dirs
    s = validate(s)
    p = path(env)
    env.guard(p)
    for d in _missing_dirs(os.path.dirname(p)):
        env.guard(d)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    data = dumps(s).encode("utf-8")
    try:
        with open(p, "rb") as f:
            if f.read() == data:
                return False
    except FileNotFoundError:
        pass
    _atomic_write(p, data)
    return True


# ---- dotted keys (appglass get/set)

def get_key(s, key):
    cur = s
    for part in key.split(".") if key else []:
        if not isinstance(cur, dict) or part not in cur:
            raise SettingsError("no setting %s" % key)
        cur = cur[part]
    return cur


def set_key(s, key, value):
    """A validated copy of s with key set (apps.<key>.* created on demand)."""
    parts = key.split(".")
    if not key or not all(parts):
        raise SettingsError("bad key %r" % key)
    new = copy.deepcopy(s)
    cur = new
    for i, part in enumerate(parts[:-1]):
        if part not in cur:
            if parts[0] != "apps":
                raise SettingsError("no setting %s" % ".".join(parts[:i + 1]))
            cur[part] = {}
        cur = cur[part]
        if not isinstance(cur, dict):
            raise SettingsError("%s is not an object" % ".".join(parts[:i + 1]))
    if parts[-1] not in cur and parts[0] != "apps":
        raise SettingsError("no setting %s" % key)
    cur[parts[-1]] = value
    return validate(new)


def parse_value(text):
    """'0.7' -> 0.7, 'true' -> True, 'null' -> None, 'opaque' -> 'opaque'."""
    try:
        return json.loads(text)
    except ValueError:
        return text


# ---- the DMS plugin as the one writer

def plugin_dir(env):
    return env.config_path("dms", "plugins", PLUGIN_ID)


def plugin_active(env):
    """True when the appGlass DMS plugin is installed (its plugin.json exists)
    and DMS does not have it disabled (plugin_settings.json enabled false)."""
    if not os.path.isfile(os.path.join(plugin_dir(env), "plugin.json")):
        return False
    try:
        with open(env.config_path("dms", "plugin_settings.json"), "rb") as f:
            doc = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return True
    entry = doc.get(PLUGIN_ID) if isinstance(doc, dict) else None
    return not (isinstance(entry, dict) and entry.get("enabled") is False)


def app_enabled(s, key, default):
    a = s.get("apps", {}).get(key)
    if isinstance(a, dict) and "enabled" in a:
        return bool(a["enabled"])
    return default
