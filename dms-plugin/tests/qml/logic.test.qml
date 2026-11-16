import QtQuick
import "components/logic.js" as Logic

// components/logic.js: plugin data <-> settings.json (against the CLI's own
// defaults in contract/defaults.json), the command lines, the status rows.
Item {
    Harness {
        id: t
    }

    Component.onCompleted: {
        const defaults = JSON.parse(t.readFile("contract/defaults.json"));
        const status = JSON.parse(t.readFile("contract/status.json"));

        // --- settings
        t.check("empty plugin data = the appglass defaults", Logic.settingsFromPluginData({}), defaults);
        t.check("the defaults round-trip", Logic.settingsFromPluginData(Logic.pluginDataFromSettings(defaults)), defaults);
        t.check("DEFAULTS give the defaults", Logic.settingsFromPluginData(Logic.DEFAULTS), defaults);

        const s = Logic.settingsFromPluginData({
            "glassEnabled": false,
            "fallbackMode": "value",
            "fallbackValuePct": 85,
            "inactiveEnabled": false,
            "inactiveMorePct": 15,
            "inactiveDurationMs": 250,
            "inactiveEasing": "linear",
            "inactiveInstantFallback": true,
            "levels": {
                "content": 0.8,
                "bar": 0.7
            },
            "fallbackInactive": 0.5,
            "apps": {
                "Alacritty": {
                    "enabled": false
                },
                "steam": {
                    "enabled": true,
                    "route": "cdp"
                },
                "bad key!": {
                    "enabled": true
                },
                "junk": 3
            }
        });
        t.check("enabled", s.enabled, false);
        t.check("fallback", s.fallback, {
            "mode": "value",
            "value": 0.85,
            "inactive": 0.5
        });
        t.check("inactive", s.inactive, {
            "enabled": false,
            "factor": 0.85,
            "durationMs": 250,
            "easing": "linear",
            "instantFallback": true
        });
        t.check("levels kept, bar never under content", s.levels, {
            "content": 0.8,
            "bar": 0.8
        });
        t.check("apps: bad keys and junk dropped", s.apps, {
            "Alacritty": {
                "enabled": false
            },
            "steam": {
                "enabled": true,
                "route": "cdp"
            }
        });
        t.check("round trip", Logic.settingsFromPluginData(Logic.pluginDataFromSettings(s)), s);

        const clamped = Logic.settingsFromPluginData({
            "fallbackMode": "dim",
            "fallbackValuePct": 10,
            "inactiveMorePct": 90,
            "inactiveDurationMs": 9999,
            "inactiveEasing": "bounce",
            "glassEnabled": "yes",
            "levels": {
                "content": "0.8"
            }
        });
        t.check("out of range values clamped or defaulted", [clamped.fallback.mode, clamped.fallback.value, clamped.inactive.factor, clamped.inactive.durationMs, clamped.inactive.easing, clamped.enabled, clamped.levels.content], ["opaque", 0.5, 0.8, 400, "ease-out-cubic", true, null]);

        t.check("factor <-> percent", [Logic.factorFromPct(0), Logic.factorFromPct(10), Logic.factorFromPct(20), Logic.pctFromFactor(0.9), Logic.pctFromFactor(0.8), Logic.pctFromFactor(1)], [1, 0.9, 0.8, 10, 20, 0]);
        t.ok("settingsText ends with a newline", Logic.settingsText({}).endsWith("}\n"));
        t.check("stableJson sorts keys", Logic.stableJson({
            "b": 1,
            "a": [{
                    "d": 2,
                    "c": 3
                }]
        }), "{\"a\":[{\"c\":3,\"d\":2}],\"b\":1}");

        // --- commands
        t.check("bin from the plugin folder", Logic.appglassBin("/h/.config/dms/plugins/appGlass/", ""), "/h/.config/dms/plugins/appGlass/../bin/appglass");
        t.check("bin override", Logic.appglassBin("/x", " /opt/appglass "), "/opt/appglass");
        t.check("no folder, no bin", Logic.appglassBin("", undefined), "");
        t.check("settings file", Logic.settingsFilePath("/run/user/UID/"), "/run/user/UID/appglass-plugin-settings.json");
        t.check("no runtime dir", Logic.settingsFilePath(null), "");
        t.check("sync argv", Logic.syncArgv("/b/appglass", "/run/f.json"), ["sh", "-c", "exec \"$0\" \"$@\" 2>&1", "/b/appglass", "sync", "--settings-file", "/run/f.json"]);
        t.check("status argv", Logic.statusArgv("/b/appglass"), ["/b/appglass", "status", "--json"]);
        t.check("get / remove argv", [Logic.getArgv("a"), Logic.removeArgv("a")], [["a", "get"], ["a", "remove"]]);
        t.check("error: the appglass line", Logic.errorText("apps: 3 glass\nappglass: sync: f rejected\n", 1), "appglass: sync: f rejected");
        t.check("error: the last line", Logic.errorText("one\ntwo\n\n", 1), "two");
        t.check("error: the exit code", Logic.errorText("", 2), "appglass exited with status 2");

        // --- status
        t.check("status parsed", Logic.parseStatus(JSON.stringify(status)).version, 1);
        t.check("junk status", [Logic.parseStatus("nope"), Logic.parseStatus("[]"), Logic.parseStatus("{\"version\": 2}")], [null, null, null]);
        const rows = Logic.appRows(status, "");
        t.check("one row per app", rows.length, status.apps.length);
        const names = rows.map(r => r.name.toLowerCase());
        t.check("sorted by name", names, names.slice().sort());
        const alac = rows.filter(r => r.key === "Alacritty")[0];
        t.check("Alacritty row", alac, {
            "key": "Alacritty",
            "name": "Alacritty",
            "appId": "Alacritty",
            "badge": "Native",
            "effective": "glass",
            "reason": "family alacritty",
            "risk": "none",
            "switchable": true,
            "on": true
        });
        const flatseal = rows.filter(r => r.key === "com.github.tchx84.Flatseal")[0];
        t.check("app-id unescaped", flatseal.appId, "com.github.tchx84.Flatseal");
        const delegated = rows.filter(r => r.effective === "delegated");
        t.ok("a delegated row has no switch", delegated.length > 0 && delegated.every(r => !r.switchable && r.badge === "Delegated"));
        t.check("badges", [Logic.badge({
                "effective": "glass",
                "tier": "forced"
            }), Logic.badge({
                "effective": "fallback",
                "tier": "native"
            }), Logic.badge({
                "effective": "opaque"
            }), Logic.badge({})], ["Forced", "Fallback", "Opaque", "Fallback"]);
        t.check("filter", Logic.appRows(status, "flatSEAL").map(r => r.key), ["com.github.tchx84.Flatseal"]);
        t.check("no status, no rows", Logic.appRows(null, ""), []);
        t.check("withApp", Logic.withApp({
            "steam": {
                "enabled": false,
                "route": "cdp"
            }
        }, "steam", true), {
            "steam": {
                "enabled": true,
                "route": "cdp"
            }
        });
        t.check("withApp ignores a bad key", Logic.withApp({}, "../x", true), {});
        t.ok("level text", Logic.levelText(status).indexOf("60%") > 0);
        t.check("level text before a status", Logic.levelText(null), "Glass level: not known yet");
        t.ok("inactive text at the floor", Logic.inactiveText(status).indexOf("no change") > 0);
        t.check("inactive text", Logic.inactiveText({
            "inactive": {
                "enabled": true,
                "active": true,
                "level": 0.72
            }
        }), "Unfocused windows: 72%");
        t.ok("summary text", Logic.summaryText(status).indexOf("glass") >= 0);
        t.check("on/off words", ["on", "OFF", "true", "0", "maybe"].map(Logic.parseOnOff), [true, false, true, false, null]);
        t.finish();
    }
}
