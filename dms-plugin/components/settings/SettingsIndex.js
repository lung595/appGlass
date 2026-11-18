.pragma library

// What the settings page holds, as data: the rail categories and one entry
// per setting (its id is the objectName of the item on the page). The pages
// take their labels and help lines from here, so what the search finds is
// what the page says. The app list joins it one entry per app (appEntries).

var CATEGORIES = [
    {
        "id": "glass",
        "icon": "blur_on",
        "name": "Glass",
        "help": "on or off, at the DMS level"
    },
    {
        "id": "apps",
        "icon": "apps",
        "name": "Apps",
        "help": "one switch and route per app"
    },
    {
        "id": "fade",
        "icon": "gradient",
        "name": "Fade",
        "help": "unfocused windows"
    },
    {
        "id": "fallback",
        "icon": "layers",
        "name": "Fallback",
        "help": "apps without glass"
    },
    {
        "id": "advanced",
        "icon": "build",
        "name": "Advanced",
        "help": "learn, adopt, report, uninstall"
    },
    {
        "id": "about",
        "icon": "info",
        "name": "About",
        "help": "what appGlass does and never does"
    }
];

var ENTRIES = [
    {
        "id": "glassToggle",
        "category": "glass",
        "label": "Glass for desktop apps",
        "help": "Off pauses the glass in every app; turning it on puts it back",
        "keywords": ["enable", "disable", "pause", "resume", "master", "switch", "on", "off"]
    },
    {
        "id": "levelInfo",
        "category": "glass",
        "label": "Glass level",
        "help": "Follows the DMS window opacity (your global window rule); text and icons stay opaque",
        "keywords": ["opacity", "transparency", "dms", "window", "rule", "blur", "level"]
    },
    {
        "id": "followDmsButton",
        "category": "glass",
        "label": "Follow the DMS rule",
        "help": "The level was set in appglass's own settings (appglass set levels.content): this clears it, and the glass follows the DMS window rule again",
        "keywords": ["opacity", "level", "dms", "rule", "reset", "levels"]
    },
    {
        "id": "summaryInfo",
        "category": "glass",
        "label": "Apps on glass",
        "help": "How many apps have glass, fall back or stay opaque",
        "keywords": ["count", "summary", "status"]
    },
    {
        "id": "reapplyButton",
        "category": "glass",
        "label": "Re-apply",
        "help": "Writes every glass file again from the current settings",
        "keywords": ["refresh", "sync", "apply", "again"]
    },
    {
        "id": "appList",
        "category": "apps",
        "label": "App list",
        "help": "Each app's status and route, with its own switch",
        "keywords": ["apps", "applications", "per", "app", "route", "switch", "toggle", "status"]
    },
    {
        "id": "inactiveToggle",
        "category": "fade",
        "label": "Fade unfocused windows",
        "help": "Unfocused windows get a little more transparent; only the background fades. Open apps pick up a change when they restart",
        "keywords": ["inactive", "unfocused", "focus", "dim", "fade"]
    },
    {
        "id": "inactiveLevel",
        "category": "fade",
        "label": "Fade amount",
        "help": "How much more transparent an unfocused window gets (never below 60%)",
        "keywords": ["amount", "strength", "percent", "inactive", "fade"]
    },
    {
        "id": "inactiveDuration",
        "category": "fade",
        "label": "Fade duration",
        "help": "How long the fade takes; 0 ms: no animation",
        "keywords": ["duration", "time", "animation", "speed", "ms", "fade"]
    },
    {
        "id": "inactiveEasing",
        "category": "fade",
        "label": "Fade easing",
        "help": "The curve of the fade animation",
        "keywords": ["easing", "curve", "animation", "linear", "ease", "fade"]
    },
    {
        "id": "instantFallback",
        "category": "fade",
        "label": "Dim apps that cannot fade",
        "help": "A niri rule for the other apps: instant, and the text dims too",
        "keywords": ["instant", "niri", "fallback", "fade", "dim"]
    },
    {
        "id": "fallbackMode",
        "category": "fallback",
        "label": "Apps without glass",
        "help": "What apps appglass cannot glass look like: opaque, translucent or the DMS opacity",
        "keywords": ["fallback", "opaque", "translucent", "opacity", "mode", "unsupported"]
    },
    {
        "id": "fallbackValue",
        "category": "fallback",
        "label": "Fallback opacity",
        "help": "The opacity of the translucent fallback (text fades too)",
        "keywords": ["fallback", "opacity", "value", "percent", "translucent"]
    },
    {
        "id": "learnButton",
        "category": "advanced",
        "label": "Learn open windows",
        "help": "Records the toolkit of each open window, so a new app gets the right route",
        "keywords": ["learn", "detect", "windows", "toolkit", "scan"]
    },
    {
        "id": "adoptButton",
        "category": "advanced",
        "label": "Adopt hand-made files",
        "help": "Hands the known hand-made glass files to appglass, each one backed up first",
        "keywords": ["adopt", "conflict", "hand", "made", "files", "backup"]
    },
    {
        "id": "reportButton",
        "category": "advanced",
        "label": "Copy report",
        "help": "Copies every app's status, route and reason as text",
        "keywords": ["report", "copy", "clipboard", "debug", "bug", "status"]
    },
    {
        "id": "uninstallButton",
        "category": "advanced",
        "label": "Uninstall appGlass",
        "help": "Restores every file appglass touched, byte for byte, removes its sync hook, then the plugin link",
        "keywords": ["uninstall", "remove", "restore", "sweep", "delete", "clean"]
    },
    {
        "id": "versionInfo",
        "category": "about",
        "label": "Version",
        "help": "appGlass for niri and DMS",
        "keywords": ["version", "about"]
    },
    {
        "id": "neverInfo",
        "category": "about",
        "label": "Never touched",
        "help": "Games, the windows DMS draws itself and the browsers browserGlass owns; nothing outside your home folder",
        "keywords": ["never", "games", "excluded", "safe", "browser", "root", "home", "backup"]
    },
    {
        "id": "cliInfo",
        "category": "about",
        "label": "Command line",
        "help": "appglass status, learn, adopt and remove do the same from a terminal",
        "keywords": ["cli", "terminal", "command", "ipc"]
    }
];

// One index entry per app row (Logic.appRows): found by name, app-id,
// toolkit, route and status
function appEntries(rows) {
    return (Array.isArray(rows) ? rows : []).map(function (r) {
        return {
            "id": "app:" + r.key,
            "category": "apps",
            "label": r.name,
            "help": r.reason,
            "keywords": [r.key, r.appId, r.toolkit, r.route, r.kind, r.statusLabel]
        };
    });
}
