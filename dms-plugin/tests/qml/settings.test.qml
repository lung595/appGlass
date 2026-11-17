import QtQuick
import Quickshell
import qs.Common
import qs.Services
import "components/logic.js" as Logic

// AppGlassSettings.qml: the rail, the search across every category, what it
// shows from the daemon's shared status, what each widget saves, the app
// switches and routes (with the confirm sheet for a mod or forced route),
// the pause, the Advanced actions (a fake daemon records them). The page
// runs no command.
Item {
    id: root

    Harness {
        id: t
    }

    property var page: null
    property var daemon: null
    property var status: ({})

    Component {
        id: pageComponent
        AppGlassSettings {
            width: 600
        }
    }
    Component {
        id: daemonComponent
        QtObject {
            property var calls: []
            function requestSync(reason, waitMs) {
                calls = calls.concat([[reason, waitMs]]);
                return true;
            }
            function runAction(name) {
                calls = calls.concat([["action", name]]);
                return true;
            }
            function copyReport() {
                calls = calls.concat([["report"]]);
                return true;
            }
        }
    }

    function fresh(withDaemon, vars, data) {
        if (root.page)
            root.page.destroy();
        root.page = null;
        root.daemon = null;
        Proc.reset();
        ToastService.reset();
        PluginService.reset();
        SettingsData.reset();
        SettingsData.pluginSettings = {
            "appGlass": Object.assign({
                "enabled": true,
                "seeded": true
            }, data || {})
        };
        PluginService.globalVars = {
            "appGlass": vars === undefined ? {
                "status": root.status,
                "lastError": "",
                "syncing": false
            } : vars
        };
        const instances = {};
        if (withDaemon !== false) {
            root.daemon = daemonComponent.createObject(root);
            instances["appGlass"] = root.daemon;
        }
        PluginService.pluginDaemonInstances = instances;
        root.page = pageComponent.createObject(root, {
            "pluginService": PluginService
        });
    }

    function find(item, name) {
        if (!item)
            return null;
        if (item.objectName === name)
            return item;
        const kids = item.children || [];
        for (let i = 0; i < kids.length; i++) {
            const hit = find(kids[i], name);
            if (hit)
                return hit;
        }
        return null;
    }
    function findAll(item, prefix, out) {
        if (!item)
            return out;
        if (String(item.objectName).indexOf(prefix) === 0)
            out.push(item);
        const kids = item.children || [];
        for (let i = 0; i < kids.length; i++)
            findAll(kids[i], prefix, out);
        return out;
    }
    function shown(name) {
        const it = root.find(root.page, name);
        return it ? it.visible : "missing " + name;
    }
    function shownAll(names) {
        return names.map(n => root.shown(n));
    }
    function view() {
        return root.find(root.page, "searchField");
    }
    function type(text) {
        root.find(root.page, "searchField").text = text;
    }
    function saved(key) {
        return SettingsData.getPluginSetting("appGlass", key, undefined);
    }

    readonly property var glassIds: ["glassToggle", "levelInfo", "summaryInfo", "reapplyButton"]
    readonly property var fadeIds: ["inactiveToggle", "inactiveLevel", "inactiveDuration", "inactiveEasing", "instantFallback"]
    readonly property var advancedIds: ["learnButton", "adoptButton", "reportButton", "uninstallButton"]

    Component.onCompleted: {
        root.status = JSON.parse(t.readFile("contract/status.json"));
        t.steps([
            {
                "run": () => root.fresh()
            },
            {
                // --- the rail: Glass opens first, one category at a time
                "run": () => {
                    const p = root.page;
                    t.check("rail entries", root.findAll(p, "rail-", []).map(x => x.objectName), ["rail-glass", "rail-apps", "rail-fade", "rail-fallback", "rail-advanced", "rail-about"]);
                    t.check("glass page open", root.shownAll(root.glassIds), [true, true, true, true]);
                    t.check("the others closed", root.shownAll(["page-apps", "page-fade", "page-fallback", "page-advanced", "page-about", "noResults"]), [false, false, false, false, false, false]);
                    t.check("header", [root.find(p, "headerStatus").text, root.find(p, "pauseButton").text], ["Glass on, 7 apps on glass", "Pause glass"]);
                    t.check("level shown, read only", root.find(p, "levelInfo").text, "Glass level: 60% (bars 65%), from the DMS window rule opacity");
                    t.ok("inactive at the floor explained", root.find(p, "inactiveInfo").text.indexOf("no change") > 0);
                    t.check("summary", root.find(p, "summaryInfo").text, "Apps on glass: 1 delegated, 5 fallback, 7 glass, 1 opaque");
                    t.check("no error shown", root.find(p, "errorInfo").visible, false);
                    t.press(root.find(p, "rail-fade"));
                    t.check("fade open", [root.shown("page-fade"), root.shown("page-glass")], [true, false]);
                    t.check("fade items", root.shownAll(root.fadeIds), [true, true, true, true, true]);
                    t.check("defaults loaded", [root.find(p, "glassToggle").value, root.find(p, "inactiveToggle").value, root.find(p, "inactiveLevel").value, root.find(p, "inactiveDuration").value, root.find(p, "inactiveEasing").value, root.find(p, "instantFallback").value, root.find(p, "fallbackMode").value], [true, true, 10, 180, "ease-out-cubic", false, "opaque"]);
                    // the widgets save their keys
                    root.find(p, "inactiveLevel").value = 15;
                    root.find(p, "inactiveDuration").value = 300;
                    root.find(p, "inactiveEasing").choose("Linear");
                    t.check("what the daemon will sync", Logic.settingsFromPluginData(SettingsData.getPluginSettingsForPlugin("appGlass")).inactive, {
                        "enabled": true,
                        "factor": 0.85,
                        "durationMs": 300,
                        "easing": "linear",
                        "instantFallback": false
                    });
                    root.find(p, "inactiveToggle").value = false;
                    t.check("the fade's settings hide when it is off", root.shownAll(root.fadeIds), [true, false, false, false, false]);
                    t.check("inactive off saved", root.saved("inactiveEnabled"), false);
                    // keyboard: down from Fade is Fallback
                    root.find(p, "rail-fade").Keys.downPressed(null);
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("arrow key: next category", [root.shown("page-fallback"), root.shown("page-fade")], [true, false]);
                    t.check("fallback opacity hidden unless translucent", root.shownAll(["fallbackMode", "fallbackValue"]), [true, false]);
                    root.find(p, "fallbackMode").choose("Translucent (text too)");
                    t.check("fallback saved, its opacity shown", [root.saved("fallbackMode"), root.shown("fallbackValue")], ["value", true]);
                    t.press(root.find(p, "rail-about"));
                    t.check("about", root.shownAll(["versionInfo", "neverInfo", "cliInfo"]), [true, true, true]);
                    t.ok("version", root.find(p, "versionInfo").text.indexOf("appGlass " + Logic.VERSION) === 0);
                    // --- search: every category at once
                    root.type("fade");
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("search: the fade settings, even those the switch hides", root.shownAll(root.fadeIds), [true, true, true, true, true]);
                    t.check("search: no other category's page", root.shownAll(["page-glass", "page-about", "page-advanced", "noResults"]), [false, false, false, false]);
                    t.check("rail counts", [root.find(p, "railCount-fade").visible, root.find(p, "rail-about").opacity < 1], [true, true]);
                    t.check("no rail entry is open while searching", root.find(p, "rail-about").on, false);
                    root.type("opacity");
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("opacity: across glass and fallback", [root.shown("levelInfo"), root.shown("fallbackMode"), root.shown("glassToggle"), root.shown("inactiveLevel")], [true, true, false, false]);
                    root.type("xyz");
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("no results", [root.shown("noResults"), root.find(p, "noResults").query], [true, "xyz"]);
                    t.check("nothing else", root.shownAll(["page-glass", "page-apps", "page-fade", "page-fallback", "page-advanced", "page-about"]), [false, false, false, false, false, false]);
                    root.type("flatseal");
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("an app by name", root.findAll(p, "app:", []).filter(x => x.visible).map(x => x.objectName), ["app:com.github.tchx84.Flatseal"]);
                    root.type("conflict");
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("an app by status", root.findAll(p, "app:", []).filter(x => x.visible).map(x => x.objectName), ["app:vlc"]);
                    t.check("the conflict line", [root.shown("conflict-vlc"), root.find(p, "status-vlc").text], [true, "Conflict"]);
                    root.type("uninst");
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("one match", root.shownAll(root.advancedIds), [false, false, false, true]);
                    root.find(p, "searchField").accepted();
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("Enter: the best match's category, search cleared", [root.find(p, "searchField").text, root.shownAll(root.advancedIds)], ["", [true, true, true, true]]);
                    t.check("advanced only", root.shownAll(["page-advanced", "page-apps", "page-glass"]), [true, false, false]);
                    // --- Advanced: through the daemon; adopt and uninstall ask first
                    t.press(root.find(p, "learnButton"));
                    t.press(root.find(p, "reportButton"));
                    t.check("learn and report", root.daemon.calls, [["action", "learn"], ["report"]]);
                    t.press(root.find(p, "uninstallButton"));
                    t.check("uninstall asks", [root.shown("confirmUninstall"), root.daemon.calls.length], [true, 2]);
                    t.press(root.find(p, "confirmUninstall-no"));
                    t.check("cancel: nothing", [root.shown("confirmUninstall"), root.daemon.calls.length], [false, 2]);
                    t.press(root.find(p, "adoptButton"));
                    t.ok("adopt names the file in the way", root.find(p, "confirmAdopt").risk.indexOf("~/.local/share/applications/vlc.desktop") > 0);
                    t.press(root.find(p, "confirmAdopt-yes"));
                    t.press(root.find(p, "uninstallButton"));
                    t.press(root.find(p, "confirmUninstall-yes"));
                    t.check("confirmed", root.daemon.calls.slice(2), [["action", "adopt"], ["action", "uninstall"]]);
                    t.check("the page runs nothing", [Proc.calls, Quickshell.detached], [[], []]);
                    root.fresh(true, {
                        "status": root.status,
                        "lastError": "",
                        "syncing": false,
                        "action": "learn"
                    });
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.press(root.find(p, "rail-advanced"));
                    t.check("an action running: the buttons wait", [root.find(p, "learnButton").busy, root.find(p, "learnButton").enabled, root.find(p, "uninstallButton").enabled, root.find(p, "reportButton").enabled], [true, false, false, true]);
                    // --- the app list
                    t.press(root.find(p, "rail-apps"));
                    const rows = root.findAll(p, "app:", []);
                    t.check("one row per app, all shown", [rows.length, rows.filter(x => x.visible).length], [14, 14]);
                    t.check("statuses", ["Alacritty", "vlc", "Pinball", "org.mozilla.firefox", "steam", "discord"].map(k => root.find(p, "status-" + k).text), ["Glass", "Conflict", "Opaque", "Delegated", "Fallback", "Fallback"]);
                    t.check("route shown", root.find(p, "route-Alacritty").text.indexOf("terminal · Native"), 0);
                    const toggles = root.findAll(p, "appToggle-", []);
                    t.check("one switch per switchable row", toggles.filter(x => x.visible).length, Logic.appRows(root.status, {}, true).filter(r => r.switchable).length);
                    const alac = root.find(p, "appToggle-Alacritty");
                    t.tap(alac);
                    t.check("a native app: no question, saved", [root.saved("apps"), alac.checked, root.shown("confirm-Alacritty")], [{
                            "Alacritty": {
                                "enabled": false
                            }
                        }, false, false]);
                    t.check("its status follows", root.find(p, "status-Alacritty").text, "Paused");
                    t.tap(alac);
                    t.check("and back", [root.saved("apps"), alac.checked], [{
                            "Alacritty": {
                                "enabled": true
                            }
                        }, true]);
                    // discord: off, its route a mod -> asks
                    t.check("routes to pick from", [root.findAll(p, "route-discord-", []).map(x => [x.objectName, x.variant]), root.findAll(p, "route-steam-", []).filter(x => x.visible).length], [[["route-discord-electron-vencord", "tonal"], ["route-discord-electron-hook", "outlined"]], 0]);
                    const disc = root.find(p, "appToggle-discord");
                    t.check("discord off", disc.checked, false);
                    t.tap(disc);
                    t.check("a mod route asks first", [root.shown("confirm-discord"), root.saved("apps").discord], [true, undefined]);
                    t.ok("the sheet says what it is", root.find(p, "confirm-discord").title.indexOf("electron-vencord (a mod)") > 0 && root.find(p, "confirm-discord").risk !== "");
                    t.press(root.find(p, "confirm-discord-no"));
                    t.check("cancel: nothing saved", [root.shown("confirm-discord"), root.saved("apps").discord, disc.checked], [false, undefined, false]);
                    // a route picked while off: saved, no question
                    t.press(root.find(p, "route-discord-electron-hook"));
                    t.check("route saved while off", [root.saved("apps").discord, root.shown("confirm-discord")], [{
                            "route": "electron-hook"
                        }, false]);
                    t.check("the chip follows", [root.find(p, "route-discord-electron-hook").variant, root.find(p, "route-discord").text.indexOf("electron-hook · Forced")], ["tonal", 0]);
                    t.tap(disc);
                    t.ok("forced asks too", root.find(p, "confirm-discord").title.indexOf("electron-hook (forced)") > 0);
                    t.press(root.find(p, "confirm-discord-yes"));
                    t.check("confirmed: on with its route", [root.saved("apps").discord, disc.checked, root.shown("confirm-discord")], [{
                            "enabled": true,
                            "route": "electron-hook"
                        }, true, false]);
                    // on: picking the mod route asks; off needs nothing
                    t.press(root.find(p, "route-discord-electron-vencord"));
                    t.check("a mod route while on asks", [root.shown("confirm-discord"), root.saved("apps").discord.route], [true, "electron-hook"]);
                    t.press(root.find(p, "confirm-discord-yes"));
                    t.check("route switched", root.saved("apps").discord, {
                        "enabled": true,
                        "route": "electron-vencord"
                    });
                    t.tap(disc);
                    t.check("turning off never asks", [root.saved("apps").discord.enabled, root.shown("confirm-discord")], [false, false]);
                    // --- pause: saved, the master switch and the rows follow
                    t.press(root.find(p, "pauseButton"));
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("paused", [root.saved("glassEnabled"), root.find(p, "pauseButton").text, root.find(p, "headerStatus").text], [false, "Resume glass", "Glass paused"]);
                    t.check("rows paused, switches wait", [root.find(p, "status-Alacritty").text, root.find(p, "appToggle-Alacritty").enabled, root.find(p, "status-org.mozilla.firefox").text], ["Paused", false, "Delegated"]);
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("the Glass switch (in its page) reloaded", root.find(p, "glassToggle").value, false);
                    root.find(p, "glassToggle").value = true;
                    t.check("and the switch resumes", [root.saved("glassEnabled"), root.find(p, "pauseButton").text], [true, "Pause glass"]);
                    t.press(root.find(p, "rail-glass"));
                    t.press(root.find(p, "reapplyButton"));
                    t.check("re-apply asks the daemon", root.daemon.calls, [["reapply", 0]]);
                    t.check("the page runs nothing", [Proc.calls, Quickshell.detached], [[], []]);
                    root.fresh(true, {
                        "status": null,
                        "lastError": "appglass: sync: boom",
                        "syncing": true
                    });
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("before a status", [root.find(p, "levelInfo").text, root.find(p, "headerStatus").text, root.shown("summaryInfo")], ["Glass level: not known yet", "Waiting for appglass", false]);
                    t.check("error shown", [root.find(p, "errorInfo").visible, root.find(p, "errorInfo").text], [true, "appglass: sync: boom"]);
                    const b = root.find(p, "reapplyButton");
                    t.check("busy button", [b.text, b.enabled], ["Applying...", false]);
                    t.press(root.find(p, "rail-apps"));
                    t.check("no rows yet", [root.findAll(p, "app:", []).length, root.shown("appListEmpty")], [0, true]);
                    root.fresh(false, {}, {
                        "inactiveMorePct": 20,
                        "apps": {
                            "Alacritty": {
                                "enabled": false
                            }
                        }
                    });
                }
            },
            {
                // the pages' widgets load once the page is built
                "wait": 20,
                "run": () => {
                    const p = root.page;
                    t.check("saved values loaded", [root.find(p, "inactiveLevel").value, root.find(p, "glassToggle").value], [20, true]);
                    t.check("opening the page saves nothing", PluginService.saves, []);
                    t.press(root.find(p, "reapplyButton"));
                    t.press(root.find(p, "rail-advanced"));
                    t.press(root.find(p, "reportButton"));
                    t.check("no daemon: a warning toast", ToastService.ofLevel("warning").map(x => x.message), ["appGlass: the plugin daemon is not running", "appGlass: the plugin daemon is not running"]);
                    root.page.width = 380;
                    t.check("narrow: the rail keeps its icons", root.find(p, "rail").width, 48);
                }
            }
        ]);
    }
}
