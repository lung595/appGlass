.pragma library

// The plugin's pure logic: plugin data <-> appglass settings.json, the
// command lines, the status read. No QML object, no I/O: unit-tested in
// tests/qml/logic.test.qml.
//
// Plugin data keys (DMS plugin_settings.json, "appGlass"):
//   glassEnabled              bool, default true (settings "enabled"; off
//                             takes every glass file out). Not "enabled":
//                             DMS keeps its own plugin switch under that key.
//   fallbackMode              "opaque" | "value" | "off"
//   fallbackValuePct          50..100 (fallback.value x 100)
//   inactiveEnabled           bool, default true
//   inactiveMorePct           0..20: how much more transparent an unfocused
//                             window gets (factor = 1 - pct/100), default 10
//   inactiveDurationMs        0..400, default 180
//   inactiveEasing            "ease-out-cubic" | "ease-in-out" | "linear"
//   inactiveInstantFallback   bool, default false
//   apps                      {key: {enabled, route?}} (the app list toggles)
//   levels, fallbackInactive  kept as appglass had them (the levels follow
//                             the DMS window rule unless set from the CLI)
//   seeded                    true once the data was taken from `appglass get`
//   appglassBin               optional path of the appglass command

var PLUGIN_ID = "appGlass";
var SYNC_ID = "appGlass.sync";
var STATUS_ID = "appGlass.status";
var SEED_ID = "appGlass.seed";
var SYNC_DEBOUNCE_MS = 400;
var SYNC_TIMEOUT_MS = 120000;
var STATUS_TIMEOUT_MS = 30000;

var FALLBACK_MODES = ["opaque", "value", "off"];
var EASINGS = ["ease-out-cubic", "ease-in-out", "linear"];
var KEY_RE = /^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$/;

var DEFAULTS = {
    "glassEnabled": true,
    "fallbackMode": "opaque",
    "fallbackValuePct": 70,
    "inactiveEnabled": true,
    "inactiveMorePct": 10,
    "inactiveDurationMs": 180,
    "inactiveEasing": "ease-out-cubic",
    "inactiveInstantFallback": false
};

// Every badge the app list shows, from a status route
var BADGES = {
    "native": "Native",
    "forced": "Forced",
    "mod": "Mod",
    "fallback": "Fallback",
    "opaque": "Opaque",
    "delegated": "Delegated",
    "excluded": "Excluded"
};

function _bool(v, dflt) {
    return typeof v === "boolean" ? v : dflt;
}

function _int(v, lo, hi, dflt) {
    var n = Number(v);
    if (v === null || v === undefined || v === "" || typeof v === "boolean" || !isFinite(n))
        return dflt;
    return Math.min(hi, Math.max(lo, Math.round(n)));
}

function _level(v, lo, hi) {
    if (typeof v !== "number" || !isFinite(v))
        return null;
    return Math.min(hi, Math.max(lo, Math.round(v * 10000) / 10000));
}

function _round2(x) {
    return Math.round(x * 100) / 100;
}

function factorFromPct(pct) {
    return _round2(1 - _int(pct, 0, 20, DEFAULTS.inactiveMorePct) / 100);
}

function pctFromFactor(factor) {
    if (typeof factor !== "number" || !isFinite(factor))
        return DEFAULTS.inactiveMorePct;
    return _int((1 - factor) * 100, 0, 20, DEFAULTS.inactiveMorePct);
}

function _apps(v) {
    var out = {};
    if (!v || typeof v !== "object" || Array.isArray(v))
        return out;
    var keys = Object.keys(v).sort();
    for (var i = 0; i < keys.length; i++) {
        var k = keys[i], a = v[k];
        if (!KEY_RE.test(k) || !a || typeof a !== "object" || Array.isArray(a))
            continue;
        var e = {};
        if (typeof a.enabled === "boolean")
            e.enabled = a.enabled;
        if (typeof a.route === "string" && a.route)
            e.route = a.route;
        if (Object.keys(e).length)
            out[k] = e;
    }
    return out;
}

// The settings.json object `appglass sync` gets, from the plugin data
function settingsFromPluginData(data) {
    var d = data || {};
    var lv = d.levels && typeof d.levels === "object" ? d.levels : {};
    var content = _level(lv.content, 0.2, 1.0);
    var bar = _level(lv.bar, 0.2, 1.0);
    if (content !== null && bar !== null && bar < content)
        bar = content;
    var mode = FALLBACK_MODES.indexOf(d.fallbackMode) >= 0 ? d.fallbackMode : DEFAULTS.fallbackMode;
    var easing = EASINGS.indexOf(d.inactiveEasing) >= 0 ? d.inactiveEasing : DEFAULTS.inactiveEasing;
    return {
        "version": 1,
        "enabled": _bool(d.glassEnabled, true),
        "levels": {
            "content": content,
            "bar": bar
        },
        "fallback": {
            "mode": mode,
            "value": _int(d.fallbackValuePct, 50, 100, DEFAULTS.fallbackValuePct) / 100,
            "inactive": _level(d.fallbackInactive, 0.3, 1.0)
        },
        "inactive": {
            "enabled": _bool(d.inactiveEnabled, true),
            "factor": factorFromPct(d.inactiveMorePct),
            "durationMs": _int(d.inactiveDurationMs, 0, 400, DEFAULTS.inactiveDurationMs),
            "easing": easing,
            "instantFallback": _bool(d.inactiveInstantFallback, false)
        },
        "apps": _apps(d.apps)
    };
}

// The plugin data keys for a settings.json object (`appglass get`)
function pluginDataFromSettings(s) {
    var o = s && typeof s === "object" ? s : {};
    var fb = o.fallback || {};
    var ia = o.inactive || {};
    var lv = o.levels || {};
    return {
        "glassEnabled": _bool(o.enabled, true),
        "levels": {
            "content": _level(lv.content, 0.2, 1.0),
            "bar": _level(lv.bar, 0.2, 1.0)
        },
        "fallbackMode": FALLBACK_MODES.indexOf(fb.mode) >= 0 ? fb.mode : DEFAULTS.fallbackMode,
        "fallbackValuePct": typeof fb.value === "number" ? _int(fb.value * 100, 50, 100, 70) : 70,
        "fallbackInactive": _level(fb.inactive, 0.3, 1.0),
        "inactiveEnabled": _bool(ia.enabled, true),
        "inactiveMorePct": pctFromFactor(ia.factor),
        "inactiveDurationMs": _int(ia.durationMs, 0, 400, DEFAULTS.inactiveDurationMs),
        "inactiveEasing": EASINGS.indexOf(ia.easing) >= 0 ? ia.easing : DEFAULTS.inactiveEasing,
        "inactiveInstantFallback": _bool(ia.instantFallback, false),
        "apps": _apps(o.apps)
    };
}

// Stable JSON (keys sorted): two settings compare by their text
function stableJson(v) {
    if (Array.isArray(v))
        return "[" + v.map(stableJson).join(",") + "]";
    if (v !== null && typeof v === "object")
        return "{" + Object.keys(v).sort().map(function (k) {
            return JSON.stringify(k) + ":" + stableJson(v[k]);
        }).join(",") + "}";
    return JSON.stringify(v);
}

function settingsText(data) {
    return JSON.stringify(settingsFromPluginData(data), null, 2) + "\n";
}

// --- commands ---------------------------------------------------------------

function _strip(p) {
    return String(p || "").replace(/\/+$/, "");
}

// The appglass command: pluginData.appglassBin, else bin/appglass of the
// repository the plugin folder belongs to (the folder is a symlink to
// <repo>/dms-plugin)
function appglassBin(pluginDir, override) {
    if (typeof override === "string" && override.trim())
        return override.trim();
    var dir = _strip(pluginDir);
    return dir ? dir + "/../bin/appglass" : "";
}

function settingsFilePath(runtimeDir) {
    var rt = _strip(runtimeDir);
    return rt ? rt + "/appglass-plugin-settings.json" : "";
}

// DMS hands a callback stdout only: the sync's messages go to stdout too
function syncArgv(bin, file) {
    return ["sh", "-c", "exec \"$0\" \"$@\" 2>&1", bin, "sync", "--settings-file", file];
}

function statusArgv(bin) {
    return [bin, "status", "--json"];
}

function getArgv(bin) {
    return [bin, "get"];
}

// The line to show for a failed command: its last "appglass: ..." line,
// else its last line, else the exit code
function errorText(output, exitCode) {
    var lines = String(output || "").split("\n").map(function (l) {
        return l.trim();
    }).filter(function (l) {
        return l.length > 0;
    });
    for (var i = lines.length - 1; i >= 0; i--) {
        if (lines[i].indexOf("appglass:") === 0)
            return lines[i];
    }
    if (lines.length)
        return lines[lines.length - 1];
    return "appglass exited with status " + exitCode;
}

// --- status -----------------------------------------------------------------

// `appglass status --json` output -> the document, or null
function parseStatus(text) {
    try {
        var doc = JSON.parse(String(text || ""));
        if (doc && typeof doc === "object" && !Array.isArray(doc) && doc.version === 1)
            return doc;
    } catch (e) {}
    return null;
}

function parseJson(text) {
    try {
        return JSON.parse(String(text || ""));
    } catch (e) {
        return undefined;
    }
}

function badge(app) {
    var a = app || {};
    var eff = a.effective;
    if (eff === "glass")
        return BADGES[a.tier] || "Native";
    return BADGES[eff] || "Fallback";
}

// One row per app of a status document, sorted by name
function appRows(status, filter) {
    var apps = status && Array.isArray(status.apps) ? status.apps : [];
    var q = String(filter || "").trim().toLowerCase();
    var rows = [];
    for (var i = 0; i < apps.length; i++) {
        var a = apps[i];
        if (!a || typeof a.key !== "string")
            continue;
        var ids = Array.isArray(a.app_ids) ? a.app_ids : [];
        var appId = ids.length ? String(ids[0]).replace(/^\^/, "").replace(/\$$/, "").replace(/\\(.)/g, "$1") : a.key;
        var row = {
            "key": a.key,
            "name": String(a.name || a.key),
            "appId": appId,
            "badge": badge(a),
            "effective": String(a.effective || ""),
            "reason": String(a.reason || ""),
            "risk": String(a.risk || ""),
            // delegated, excluded and games have no switch
            "switchable": typeof a.enabled === "boolean",
            "on": a.enabled === true
        };
        if (q && (row.name + " " + row.appId + " " + row.key).toLowerCase().indexOf(q) < 0)
            continue;
        rows.push(row);
    }
    rows.sort(function (x, y) {
        var a = x.name.toLowerCase(), b = y.name.toLowerCase();
        return a < b ? -1 : (a > b ? 1 : (x.key < y.key ? -1 : 1));
    });
    return rows;
}

// The plugin data apps map with one app switched
function withApp(apps, key, on) {
    var out = _apps(apps);
    if (!KEY_RE.test(String(key)))
        return out;
    var e = Object.assign({}, out[key] || {});
    e.enabled = !!on;
    out[key] = e;
    return out;
}

// "Glass level: 72% (follows the DMS window rule)" and the like
function levelText(status) {
    if (!status || !status.levels)
        return "Glass level: not known yet";
    var c = Math.round(Number(status.levels.content) * 100);
    var b = Math.round(Number(status.levels.bar) * 100);
    return "Glass level: " + c + "% (bars " + b + "%), from the DMS window rule opacity";
}

function inactiveText(status) {
    var ia = status && status.inactive;
    if (!ia)
        return "";
    if (!ia.enabled)
        return "Unfocused windows: off";
    if (!ia.active)
        return "Unfocused windows: no change at this glass level (it is at or under 60%)";
    return "Unfocused windows: " + Math.round(Number(ia.level) * 100) + "%";
}

function summaryText(status) {
    var s = status && status.summary;
    if (!s)
        return "";
    var parts = [];
    var keys = Object.keys(s).sort();
    for (var i = 0; i < keys.length; i++)
        parts.push(s[keys[i]] + " " + keys[i]);
    return parts.join(", ");
}

// --- the IPC "app" command --------------------------------------------------

function parseOnOff(word) {
    var w = String(word || "").toLowerCase();
    if (w === "on" || w === "true" || w === "1")
        return true;
    if (w === "off" || w === "false" || w === "0")
        return false;
    return null;
}
