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
        // discord with two routes (the fixture world leaves out the routes
        // that cannot work, so it offers one): a world where a forced
        // adapter lists the Vencord family too
        status.apps.find(a => a.key === "discord").routes = ["electron-vencord", "electron-hook"];

        // --- settings
        t.check("empty plugin data = the appglass defaults", Logic.settingsFromPluginData({}), defaults);
        t.check("the defaults round-trip", Logic.settingsFromPluginData(Logic.pluginDataFromSettings(defaults)), defaults);
        t.check("DEFAULTS give the defaults", Logic.settingsFromPluginData(Logic.DEFAULTS), defaults);
        // a visible unfocused fade by default: 10 % more -> factor 0.90 (0.80 -> 0.72), 180 ms, ease-out-cubic
        t.check("default fade", [Logic.DEFAULTS.inactiveEnabled, Logic.DEFAULTS.inactiveMorePct, Logic.factorFromPct(Logic.DEFAULTS.inactiveMorePct), Logic.DEFAULTS.inactiveDurationMs, Logic.DEFAULTS.inactiveEasing], [true, 10, 0.9, 180, "ease-out-cubic"]);
        t.check("default fade of 0.80", Math.round(0.8 * Logic.factorFromPct(Logic.DEFAULTS.inactiveMorePct) * 100) / 100, 0.72);
        t.check("no plugin data: the default fade", Logic.pluginDataFromSettings(defaults).inactiveMorePct, 10);

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
        t.check("capitalise free text", Logic.capitalise("cannot read the settings"), "Cannot read the settings");
        t.check("capitalise keeps the command name", [Logic.capitalise("appglass: sync: boom"), Logic.capitalise("appglass sync failed")], ["appglass: sync: boom", "appglass sync failed"]);
        t.check("start sync argv", Logic.syncArgv("/b/appglass", "/run/f.json", true), ["sh", "-c", "exec \"$0\" \"$@\" 2>&1", "/b/appglass", "sync", "--settings-file", "/run/f.json", "--no-switch"]);
        t.check("status argv", Logic.statusArgv("/b/appglass"), ["/b/appglass", "status", "--json"]);
        t.check("get argv", Logic.getArgv("a"), ["a", "get"]);
        t.check("error: the appglass line", Logic.errorText("apps: 3 glass\nappglass: sync: f rejected\n", 1), "appglass: sync: f rejected");
        t.check("error: the last line", Logic.errorText("one\ntwo\n\n", 1), "two");
        t.check("error: the exit code", Logic.errorText("", 2), "appglass exited with status 2");

        // --- status
        t.check("status parsed", Logic.parseStatus(JSON.stringify(status)).version, 1);
        t.check("junk status", [Logic.parseStatus("nope"), Logic.parseStatus("[]"), Logic.parseStatus("{\"version\": 2}")], [null, null, null]);
        const rows = Logic.appRows(status, {}, true);
        t.check("one row per app", rows.length, status.apps.length);
        const names = rows.map(r => r.name.toLowerCase());
        t.check("sorted by name", names, names.slice().sort());
        const alac = rows.filter(r => r.key === "Alacritty")[0];
        t.check("Alacritty row", alac, {
            "key": "Alacritty",
            "name": "Alacritty",
            "appId": "Alacritty",
            "toolkit": "terminal",
            "badge": "Native",
            "kind": "Native",
            "effective": "glass",
            "reason": "family alacritty",
            "risk": "none",
            "switchable": true,
            "on": true,
            "route": "terminal",
            "routes": [{
                    "name": "terminal",
                    "tier": "native",
                    "kind": "Native"
                }],
            "routeStale": false,
            "status": "glass",
            "statusLabel": "Glass",
            "conflicts": []
        });
        const byKey = {};
        for (const r of rows)
            byKey[r.key] = r;
        t.check("app-id unescaped", byKey["com.github.tchx84.Flatseal"].appId, "com.github.tchx84.Flatseal");
        const delegated = rows.filter(r => r.effective === "delegated");
        t.ok("a delegated row has no switch", delegated.length > 0 && delegated.every(r => !r.switchable && r.badge === "Delegated" && r.status === "delegated"));
        t.check("statuses", ["Alacritty", "vlc", "Pinball", "org.mozilla.firefox", "steam", "discord"].map(k => byKey[k].status), ["glass", "conflict", "game", "delegated", "opaque", "waiting"]);
        // Steam has no route: opaque, and no switch
        t.check("steam: opaque, no switch, no route", [byKey["steam"].switchable, byKey["steam"].routes.length], [false, 0]);
        t.check("the conflict names the file", byKey["vlc"].conflicts, ["~/.local/share/applications/vlc.desktop"]);
        t.check("discord: two routes, the mod first", byKey["discord"].routes, [{
                "name": "electron-vencord",
                "tier": "mod",
                "kind": "Mod"
            }, {
                "name": "electron-hook",
                "tier": "forced",
                "kind": "Forced"
            }]);
        t.check("games have no route", byKey["Pinball"].routes, []);
        // a family that says where it renders (ArtCraft: GPU or CPU route): the row's reason says it
        const art = JSON.parse(JSON.stringify(status));
        art.apps = [{
                "key": "ai.storyteller.artcraft-launcher",
                "name": "ArtCraft Launcher",
                "toolkit": "egui",
                "app_ids": ["^ai\\.storyteller\\.artcraft-launcher$"],
                "adapter": "ck-shim",
                "tier": "forced",
                "family": "artcraft",
                "enabled": true,
                "effective": "glass",
                "render": "cpu",
                "reason": "family artcraft, renders on the CPU: no Vulkan headers (vulkan-headers)",
                "routes": ["ck-shim"]
            }];
        art.families.artcraft = {
            "installed": true,
            "enabled": true,
            "applied": ["~/.local/bin/appglass-artcraft"],
            "render": "cpu",
            "render_why": "no Vulkan headers (vulkan-headers)"
        };
        const artRow = Logic.appRows(art, {}, true)[0];
        t.check("render: the reason says the route", [artRow.status, artRow.reason], ["glass", "family artcraft, renders on the CPU: no Vulkan headers (vulkan-headers)"]);
        // an app with no route at all: switched on it stays on the fallback, and says so
        const routeless = Logic.appRows(status, {
            "md.example.Electron": {
                "enabled": true
            }
        }, true).filter(r => r.key === "md.example.Electron")[0];
        t.check("no route: on says it stays on the fallback", [routeless.on, routeless.reason], [true, "No route yet: stays on the fallback (family feishin does not list this app)"]);
        t.check("no route, off: the plain reason", byKey["md.example.Electron"].reason, "family feishin does not list this app");
        // its switch changes nothing on disk: one state, one label, on or off
        const routelessOff = Logic.appRows(status, {
            "md.example.Electron": {
                "enabled": false
            }
        }, true).filter(r => r.key === "md.example.Electron")[0];
        t.check("no route: the same label switched on, off or never", [routeless.statusLabel, routelessOff.statusLabel, byKey["md.example.Electron"].statusLabel], ["Fallback", "Fallback", "Fallback"]);
        // glass paused: every row says so, a routeless one too
        const pausedRows = {};
        for (const r of Logic.appRows(status, {}, false))
            pausedRows[r.key] = r;
        t.check("glass off: routeless rows paused too", ["md.example.Electron", "org.example.Flutter", "Alacritty", "discord"].map(k => pausedRows[k].statusLabel), ["Paused", "Paused", "Paused", "Paused"]);
        // a switch that applies nothing (its family not installed), or an
        // opt-in app off (its default): one label, whatever the toggle history
        const label = (key, saved) => Logic.appRows(status, saved, true).filter(r => r.key === key)[0].statusLabel;
        t.check("family not installed: the same label on, off or never", [label("herdr-app", {}), label("herdr-app", {
                    "herdr-app": {
                        "enabled": true
                    }
                }), label("herdr-app", {
                    "herdr-app": {
                        "enabled": false
                    }
                })], ["Fallback", "Fallback", "Fallback"]);
        // the engine's gate: an injected route waits for its check, a stale
        // one for its re-check; a game is never touched
        const stale = JSON.parse(JSON.stringify(status));
        stale.apps.find(a => a.key === "discord").state = "stale";
        t.check("gate states", [label("discord", {}), Logic.appRows(stale, {}, true).filter(r => r.key === "discord")[0].statusLabel, label("Pinball", {})], ["Waiting for check", "Stale", "Game: never touched"]);
        t.check("an opt-in app off: the same label switched off", [label("discord", {
                    "discord": {
                        "enabled": false
                    }
                }), label("discord", {
                    "discord": {
                        "enabled": false
                    }
                }), label("md.example.Electron", {
                    "md.example.Electron": {
                        "enabled": false
                    }
                })], ["Fallback", "Fallback", "Fallback"]);
        // the saved choices win until the next status has them
        const saved = {
            "Alacritty": {
                "enabled": false
            },
            "discord": {
                "enabled": true,
                "route": "electron-hook"
            },
            "vlc": {
                "route": "no-such-route"
            }
        };
        const rows2 = {};
        for (const r of Logic.appRows(status, saved, true))
            rows2[r.key] = r;
        t.check("switched off: paused", [rows2["Alacritty"].on, rows2["Alacritty"].status, rows2["Alacritty"].statusLabel], [false, "paused", "Paused"]);
        t.check("saved route", [rows2["discord"].on, rows2["discord"].route, rows2["discord"].kind], [true, "electron-hook", "Forced"]);
        t.check("an unknown saved route is ignored, but marked", [rows2["vlc"].route, rows2["vlc"].routeStale, rows2["discord"].routeStale], ["qt-style", true, false]);
        t.check("route chips: two routes, or a stale or unlisted one", [Logic.showRoutes(byKey["discord"]), Logic.showRoutes(byKey["vlc"]), Logic.showRoutes(rows2["vlc"]), Logic.showRoutes(byKey["Pinball"]), Logic.showRoutes({
                "route": "gtk4",
                "routes": [{
                        "name": "gtk3"
                    }]
            })], [true, false, true, false, true]);
        t.check("the question in sentences", [Logic.routeText(Logic.routeInfo(status, "electron-hook")), Logic.riskText(Logic.routeInfo(status, "electron-hook"))], ["A main-process hook (NODE_OPTIONS when the fuse allows it) plus CSS.", "Medium. May break on app updates."]);
        t.check("no why, no risk", [Logic.riskText(Logic.routeInfo(status, "webkit-shim")), Logic.riskText({}), Logic.routeText({})], ["Medium.", "", ""]);
        const off = {};
        for (const r of Logic.appRows(status, {}, false))
            off[r.key] = r;
        t.check("glass off: every switchable app paused", ["Alacritty", "vlc", "solaar", "steam", "Pinball", "org.mozilla.firefox"].map(k => off[k].status), ["paused", "paused", "paused", "opaque", "game", "delegated"]);
        t.check("badges", [Logic.badge({
                "effective": "glass",
                "tier": "forced"
            }), Logic.badge({
                "effective": "fallback",
                "tier": "native"
            }), Logic.badge({
                "effective": "opaque"
            }), Logic.badge({})], ["Forced", "Fallback", "Opaque", "Fallback"]);
        t.check("no status, no rows", Logic.appRows(null, {}, true), []);
        t.check("confirm for mod and forced only", ["mod", "forced", "native", "fallback", ""].map(Logic.needsConfirm), [true, true, false, false, false]);
        t.check("route info", [Logic.routeInfo(status, "electron-vencord").risk, Logic.routeInfo(status, "nope").tier], ["medium", ""]);
        t.check("withRoute", Logic.withRoute({
            "discord": {
                "enabled": true
            }
        }, "discord", "electron-hook"), {
            "discord": {
                "enabled": true,
                "route": "electron-hook"
            }
        });
        t.check("withRoute ignores a bad route", Logic.withRoute({}, "discord", "../x"), {});
        t.check("glass count", [Logic.glassCount(status, true), Logic.glassCount(status, false), Logic.glassCount(null, true)], [7, 0, 0]);
        t.check("pill text", [Logic.pillText(status, true), Logic.pillText(status, false), Logic.pillText(null, true)], ["7", "off", ""]);
        t.check("pill text after an uninstall, or one cut short", [Logic.pillText(status, true, true), Logic.pillText(status, true, true, true)], ["uninstalled", "unfinished"]);
        const report = Logic.reportText(status, saved, true);
        t.ok("report: header", report.indexOf("appGlass " + Logic.VERSION) === 0);
        t.ok("report: one line per app", status.apps.every(a => report.indexOf("\n  " + a.key + " ") >= 0));
        t.ok("report: the conflict", report.indexOf("vlc.desktop") > 0);
        t.check("report before a status", Logic.reportText(null, {}, true), "appGlass " + Logic.VERSION + "\nno status yet\n");
        t.check("version = plugin.json", Logic.VERSION, JSON.parse(t.readFile("plugin.json")).version);
        // the actions: the CLI's own commands, its messages on stdout
        t.check("learn argv", Logic.learnArgv("/b/appglass"), ["sh", "-c", "exec \"$0\" \"$@\" 2>&1", "/b/appglass", "learn"]);
        t.check("adopt argv", Logic.adoptArgv("/b/appglass"), ["sh", "-c", "exec \"$0\" \"$@\" 2>&1", "/b/appglass", "adopt"]);
        t.check("uninstall argv", Logic.uninstallArgv("/b/appglass"), ["sh", "-c", "exec \"$0\" \"$@\" 2>&1", "/b/appglass", "remove"]);
        t.check("unlink argv", Logic.unlinkArgv("/b/appglass"), ["sh", "-c", "exec \"$0\" \"$@\" 2>&1", "/b/appglass", "plugin", "remove"]);
        t.check("action argv by name", [Logic.actionArgv("learn", "b"), Logic.actionArgv("rm -rf", "b")], [Logic.learnArgv("b"), null]);
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
