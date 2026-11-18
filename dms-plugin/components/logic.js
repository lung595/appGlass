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
// = plugin.json "version" (logic.test.qml checks)
var VERSION = "0.2.0";
var SYNC_ID = "appGlass.sync";
var STATUS_ID = "appGlass.status";
var SEED_ID = "appGlass.seed";
var SYNC_DEBOUNCE_MS = 400;
var SYNC_TIMEOUT_MS = 120000;
var STATUS_TIMEOUT_MS = 30000;
var ACTION_TIMEOUT_MS = 180000;
// Settings > Advanced: one command each, run by the daemon (one at a time)
var ACTION_IDS = {
    "learn": "appGlass.learn",
    "adopt": "appGlass.adopt",
    "uninstall": "appGlass.uninstall"
};
// The second step of the uninstall (unlinkArgv)
var UNLINK_ID = "appGlass.unlink";

var FALLBACK_MODES = ["opaque", "value", "off"];
var EASINGS = ["ease-out-cubic", "ease-in-out", "linear"];
var KEY_RE = /^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$/;
var ROUTE_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;

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

// The status chip of an app row
var STATUS_LABELS = {
    "glass": "Glass",
    "fallback": "Fallback",
    "delegated": "Delegated",
    "opaque": "Opaque",
    "paused": "Paused",
    "conflict": "Conflict",
    "waiting": "Waiting for check",
    "stale": "Stale",
    "game": "Game: never touched"
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

// DMS hands a callback stdout only: the CLI's messages go to stdout too
function cliArgv(bin, args) {
    return ["sh", "-c", "exec \"$0\" \"$@\" 2>&1", bin].concat(args);
}

// noSwitch: the start sync (the stored plugin data, which may have drifted
// from settings.json, counts as no switch of the user's: nothing taken out)
function syncArgv(bin, file, noSwitch) {
    return cliArgv(bin, ["sync", "--settings-file", file].concat(noSwitch ? ["--no-switch"] : []));
}

// Record the toolkit of each open window
function learnArgv(bin) {
    return cliArgv(bin, ["learn"]);
}

// Hand the known hand-made files to appglass (each one backed up)
function adoptArgv(bin) {
    return cliArgv(bin, ["adopt"]);
}

// Uninstall, step one: every file appglass touched restored, the hook and
// units out
function uninstallArgv(bin) {
    return cliArgv(bin, ["remove"]);
}

// Uninstall, step two (after `remove` worked): the plugin link (DMS drops
// the plugin)
function unlinkArgv(bin) {
    return cliArgv(bin, ["plugin", "remove"]);
}

// The argv of a Settings > Advanced action, null for any other name
function actionArgv(name, bin) {
    if (name === "learn")
        return learnArgv(bin);
    if (name === "adopt")
        return adoptArgv(bin);
    if (name === "uninstall")
        return uninstallArgv(bin);
    return null;
}

function statusArgv(bin) {
    return [bin, "status", "--json"];
}

function getArgv(bin) {
    return [bin, "get"];
}

// The last non-empty line of a command's output ("" for none)
function lastLine(output) {
    var lines = String(output || "").split("\n").map(function (l) {
        return l.trim();
    }).filter(function (l) {
        return l.length > 0;
    });
    return lines.length ? lines[lines.length - 1] : "";
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

// The adapter `name` of the status catalogue: {name, tier, risk, why,
// summary}; tier "" when the status does not know it
function routeInfo(status, name) {
    var list = status && Array.isArray(status.adapters) ? status.adapters : [];
    for (var i = 0; i < list.length; i++) {
        if (list[i] && list[i].name === name)
            return list[i];
    }
    return {
        "name": String(name || ""),
        "tier": "",
        "risk": "",
        "why": "",
        "summary": ""
    };
}

// The route chips of a row: more than one route to pick from, or a route in
// use (or saved) that is not among them
function showRoutes(row) {
    var routes = row && Array.isArray(row.routes) ? row.routes : [];
    if (routes.length > 1)
        return true;
    if (routes.length === 0)
        return false;
    return row.routeStale === true || !routes.some(function (r) {
        return r.name === row.route;
    });
}

function _sentence(s) {
    s = String(s || "").trim();
    if (!s)
        return "";
    s = s.charAt(0).toUpperCase() + s.slice(1);
    return /[.!?]$/.test(s) ? s : s + ".";
}

// The question before a mod or forced route: what it does, then its risk
// ("Medium. May break on app updates.")
function routeText(info) {
    return _sentence(info && info.summary);
}
function riskText(info) {
    var risk = info && info.risk ? String(info.risk) : "";
    if (!risk)
        return "";
    var why = _sentence(info.why);
    return risk.charAt(0).toUpperCase() + risk.slice(1) + "." + (why ? " " + why : "");
}

// Turning an app on with one of these routes asks first
function needsConfirm(tier) {
    return tier === "mod" || tier === "forced";
}

function _saved(saved, key) {
    var a = saved && typeof saved === "object" ? saved[key] : null;
    return a && typeof a === "object" ? a : {};
}

// No route and no family: its switch is saved but applies nothing, the app
// stays on the fallback whatever the switch says
function _routeless(a) {
    return !(Array.isArray(a.routes) && a.routes.length) && !a.family && a.effective !== "glass";
}

// glass | fallback | delegated | opaque | paused | conflict
//   paused: glass is off for every app, or the user switched off an app
//     that is on by default
//   conflict: a hand-made file appglass does not own is in the way
//   a row whose switch applies nothing (no route, or its family not
//   installed) and an opt-in app (a mod or forced route) that is off, its
//   default, read fallback: one state, one label, whatever the toggle history
function _familyMissing(a, status) {
    var fams = status && status.families && typeof status.families === "object" ? status.families : {};
    var f = a.family ? fams[a.family] : null;
    return !!(f && f.installed === false);
}

function appStatus(app, saved, glassOn, status) {
    var a = app || {};
    var eff = a.effective;
    if (eff === "delegated" || eff === "excluded")
        return "delegated";
    // the engine's gate (status "state"): a game is never touched
    if (a.state === "excluded")
        return "game";
    if (typeof a.enabled !== "boolean")
        return eff === "glass" ? "glass" : "opaque";
    if (glassOn === false)
        return "paused";
    if (Array.isArray(a.conflicts) && a.conflicts.length)
        return "conflict";
    if (_routeless(a) || _familyMissing(a, status))
        return "fallback";
    var own = _saved(saved, a.key);
    var on = typeof own.enabled === "boolean" ? own.enabled : a.enabled;
    if (!on)
        return needsConfirm(a.tier) ? "fallback" : "paused";
    // an injected route waits for its check, a stale one for its re-check
    if (a.state === "waiting" || a.state === "stale")
        return a.state;
    if (eff === "glass" || eff === "opaque")
        return eff;
    return "fallback";
}

// One row per app of a status document, sorted by name. saved: the plugin
// data apps map (what the switches show until the next status has it);
// glassOn: the global switch.
function appRows(status, saved, glassOn) {
    var apps = status && Array.isArray(status.apps) ? status.apps : [];
    var rows = [];
    for (var i = 0; i < apps.length; i++) {
        var a = apps[i];
        if (!a || typeof a.key !== "string")
            continue;
        var ids = Array.isArray(a.app_ids) ? a.app_ids : [];
        var appId = ids.length ? String(ids[0]).replace(/^\^/, "").replace(/\$$/, "").replace(/\\(.)/g, "$1") : a.key;
        var own = _saved(saved, a.key);
        var names = Array.isArray(a.routes) ? a.routes : [];
        var routes = names.map(function (n) {
            var tier = routeInfo(status, n).tier;
            return {
                "name": n,
                "tier": tier,
                "kind": BADGES[tier] || ""
            };
        });
        var route = names.indexOf(own.route) >= 0 ? own.route : (names.indexOf(a.route) >= 0 ? a.route : String(a.adapter || ""));
        var savedRoute = typeof own.route === "string" ? own.route : "";
        var tier = routeInfo(status, route).tier || a.tier;
        var st = appStatus(a, saved, glassOn, status);
        var on = typeof own.enabled === "boolean" ? own.enabled : a.enabled === true;
        var reason = String(a.reason || "");
        // on, but nothing to apply: the switch saved, the app stays as it was
        if (on && typeof a.enabled === "boolean" && _routeless(a))
            reason = "No route yet: stays on the fallback" + (reason ? " (" + reason + ")" : "");
        rows.push({
            "key": a.key,
            "name": String(a.name || a.key),
            "appId": appId,
            "toolkit": String(a.toolkit || ""),
            "badge": badge(a),
            "kind": BADGES[tier] || "",
            "effective": String(a.effective || ""),
            "reason": reason,
            "risk": String(a.risk || ""),
            // delegated, excluded and games have no switch
            "switchable": typeof a.enabled === "boolean",
            "on": on,
            "route": route,
            "routes": routes,
            // a saved route the status does not list (the chips show, to pick again)
            "routeStale": savedRoute !== "" && savedRoute !== route,
            "status": st,
            "statusLabel": STATUS_LABELS[st],
            "conflicts": Array.isArray(a.conflicts) ? a.conflicts.map(String) : []
        });
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

// The plugin data apps map with one app's route picked
function withRoute(apps, key, route) {
    var out = _apps(apps);
    if (!KEY_RE.test(String(key)) || !ROUTE_RE.test(String(route)))
        return out;
    var e = Object.assign({}, out[key] || {});
    e.route = String(route);
    out[key] = e;
    return out;
}

// How many apps are on glass (0 while glass is off)
function glassCount(status, glassOn) {
    if (glassOn === false || !status || !status.summary)
        return 0;
    return Number(status.summary.glass) || 0;
}

// The bar pill's text: the count, "off", or nothing before a status
// unfinished: an uninstall a reload cut short (the files may all be there)
function pillText(status, glassOn, uninstalled, unfinished) {
    if (unfinished === true)
        return "unfinished";
    if (uninstalled === true)
        return "uninstalled";
    if (glassOn === false)
        return "off";
    if (!status)
        return "";
    return String(glassCount(status, glassOn));
}

// An error line as the page shows it: a capital first letter
// The first letter in upper case, but for the command's own name (an
// error that starts with "appglass:" or "appglass ...") kept as it is typed
function capitalise(text) {
    var s = String(text || "");
    if (/^appglass\b/.test(s))
        return s;
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : "";
}

// A plain-text report of the last status (Settings > Advanced > Copy report)
function reportText(status, saved, glassOn) {
    var out = ["appGlass " + VERSION];
    if (!status)
        return out.concat(["no status yet"]).join("\n") + "\n";
    out.push("glass: " + (glassOn === false ? "paused" : "on") + "; " + levelText(status));
    if (status.settings_error)
        out.push("settings error: " + status.settings_error);
    out.push("summary: " + summaryText(status));
    out.push("apps:");
    var rows = appRows(status, saved, glassOn);
    for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        out.push("  " + r.key + " " + [r.toolkit, r.route + (r.kind ? " (" + r.kind.toLowerCase() + ")" : ""), r.status, r.reason].join(" | "));
        for (var j = 0; j < r.conflicts.length; j++)
            out.push("    hand-made file in the way: " + r.conflicts[j]);
    }
    return out.join("\n") + "\n";
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
