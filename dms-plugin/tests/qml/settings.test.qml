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
    property real searchHeight: 0
    property int saveMark: 0

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
            function reinstall() {
                calls = calls.concat([["reinstall"]]);
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
    function focusedIn(item) {
        let it = root.page ? root.page.Window.activeFocusItem : null;
        for (; it; it = it.parent)
            if (it === item)
                return true;
        return false;
    }
    function saved(key) {
        return SettingsData.getPluginSetting("appGlass", key, undefined);
    }

    readonly property var glassIds: ["glassToggle", "levelInfo", "summaryInfo", "reapplyButton"]
    readonly property var fadeIds: ["inactiveToggle", "inactiveLevel", "inactiveDuration", "inactiveEasing", "instantFallback"]
    readonly property var advancedIds: ["learnButton", "adoptButton", "reportButton", "uninstallButton"]

    Component.onCompleted: {
        root.status = JSON.parse(t.readFile("contract/status.json"));
        // discord with two routes to pick from (the fixture world leaves out
        // the routes that cannot work, so it offers one): a world where a
        // forced adapter lists the Vencord family too
        root.status.apps.find(a => a.key === "discord").routes = ["electron-vencord", "electron-hook"];
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
                    t.ok("the fade says a change reaches an open app on its restart", root.find(p, "inactiveToggle").description.indexOf("when they restart") > 0);
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
                    t.check("rail counts", [root.find(p, "railCount-fade").visible, root.find(p, "railIcon-about").opacity < 1], [true, true]);
                    t.check("a dimmed entry: its background and icon fade, the entry itself does not", [root.find(p, "rail-about").opacity, root.find(p, "railBg-about").opacity < 1, root.find(p, "railName-about").opacity < 1], [1, true, true]);
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
                    t.check("statuses", ["Alacritty", "vlc", "Pinball", "org.mozilla.firefox", "steam", "discord"].map(k => root.find(p, "status-" + k).text), ["Glass", "Conflict", "Game: never touched", "Delegated", "Fallback", "Waiting for check"]);
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
                    // discord: on by default (the engine's gate), its route a mod
                    t.check("routes to pick from", [root.findAll(p, "route-discord-", []).map(x => [x.objectName, x.variant]), root.findAll(p, "route-steam-", []).filter(x => x.visible).length], [[["route-discord-electron-vencord", "tonal"], ["route-discord-electron-hook", "outlined"]], 0]);
                    const disc = root.find(p, "appToggle-discord");
                    t.check("discord auto", disc.checked, true);
                    t.tap(disc);
                    t.check("off never asks", [root.shown("confirm-discord"), root.saved("apps").discord, disc.checked], [false, {
                            "enabled": false
                        }, false]);
                    t.tap(disc);
                    t.check("a mod route asks first", [root.shown("confirm-discord"), root.saved("apps").discord], [true, {
                            "enabled": false
                        }]);
                    t.ok("the sheet says what it is", root.find(p, "confirm-discord").title.indexOf("electron-vencord (a mod)") > 0 && root.find(p, "confirm-discord").risk !== "");
                    t.check("in sentences, the risk first", [root.find(p, "confirm-discord").text, root.find(p, "confirm-discord").risk], ["A Vencord theme with transparency (Discord).", "Medium. Client mods break Discord's terms of service."]);
                    t.press(root.find(p, "confirm-discord-no"));
                    t.check("cancel: nothing saved", [root.shown("confirm-discord"), root.saved("apps").discord, disc.checked], [false, {
                            "enabled": false
                        }, false]);
                    // a route picked while off: saved, no question
                    t.press(root.find(p, "route-discord-electron-hook"));
                    t.check("route saved while off", [root.saved("apps").discord, root.shown("confirm-discord")], [{
                            "enabled": false,
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
                    t.check("the level follows the DMS rule: no reset offered", root.shown("followDmsButton"), false);
                    root.type("reset");
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("a search for the row not offered finds nothing", [root.shown("noResults"), root.find(p, "railCount-glass").visible], [true, false]);
                    root.type("");
                    // a level set from the CLI before the plugin took the
                    // settings: said so, and one click puts it back on the rule
                    root.fresh(true, undefined, {
                        "levels": {
                            "content": 0.8,
                            "bar": null
                        }
                    });
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.ok("the level says where it comes from", root.find(p, "levelInfo").text.indexOf("set in appglass's own settings") > 0);
                    t.check("follow the DMS rule offered", root.shown("followDmsButton"), true);
                    t.press(root.find(p, "followDmsButton"));
                    t.check("the levels cleared", root.saved("levels"), {
                        "content": null,
                        "bar": null
                    });
                    t.check("what the daemon will sync", Logic.settingsFromPluginData(SettingsData.getPluginSettingsForPlugin("appGlass")).levels, {
                        "content": null,
                        "bar": null
                    });
                    t.check("no reset offered any more", root.shown("followDmsButton"), false);
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
                    t.check("the value label follows the saved value", root.find(p, "inactiveLevel").label, "Fade amount: 20%");
                    t.check("opening the page saves nothing", PluginService.saves, []);
                    t.press(root.find(p, "reapplyButton"));
                    t.press(root.find(p, "rail-advanced"));
                    t.press(root.find(p, "reportButton"));
                    t.check("no daemon: a warning toast", ToastService.ofLevel("warning").map(x => x.message), ["appGlass: the plugin daemon is not running", "appGlass: the plugin daemon is not running"]);
                    root.page.width = 380;
                    t.check("narrow: the rail keeps its icons", root.find(p, "rail").width, 48);
                    root.fresh();
                }
            },
            {
                "wait": 20,
                "run": () => {
                    const p = root.page;
                    // --- the layout: the search first, as in the DMS hubs
                    const y = n => root.find(p, n).mapToItem(p, 0, 0).y;
                    t.ok("the search field above the status and Pause", y("searchField") < y("headerStatus") && y("searchField") < y("pauseButton"));
                    t.check("the key hint at rest", root.find(p, "searchHint").text, "Ctrl+F or /");
                    root.searchHeight = root.find(p, "search").height;
                    t.check("the category title: icon and name", [root.find(p, "pageIcon-glass").name, root.find(p, "pageTitle-glass").text], ["blur_on", "Glass"]);
                    t.check("About says it once", root.find(p, "neverInfo").text.indexOf("Never touched"), -1);
                    t.check("the fallback opacity says what it is, with its value", root.find(p, "fallbackValue").label, "Fallback opacity: 70%");
                    t.check("the fade sliders show their value at rest", [root.find(p, "inactiveLevel").label, root.find(p, "inactiveDuration").label], ["Fade amount: 10%", "Fade duration: 180 ms"]);
                    root.type("fade");
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("the key hint while typing", root.find(p, "searchHint").text, "Esc clears");
                    t.check("typing does not move the page", root.find(p, "search").height, root.searchHeight);
                    root.type("");
                    // --- the confirm sheets close when the page changes
                    t.press(root.find(p, "rail-advanced"));
                    t.press(root.find(p, "adoptButton"));
                    t.check("adopt armed", root.shown("confirmAdopt"), true);
                    t.press(root.find(p, "rail-apps"));
                    t.press(root.find(p, "rail-advanced"));
                    t.check("left and back: adopt no longer armed", root.shown("confirmAdopt"), false);
                    t.press(root.find(p, "uninstallButton"));
                    t.check("uninstall armed", root.shown("confirmUninstall"), true);
                    root.type("uninst");
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("a search disarms it", [root.shown("uninstallButton"), root.shown("confirmUninstall")], [true, false]);
                    root.find(p, "searchField").accepted();
                    t.check("still disarmed back on its page", [root.shown("page-advanced"), root.shown("confirmUninstall")], [true, false]);
                    t.press(root.find(p, "rail-apps"));
                    t.tap(root.find(p, "appToggle-discord"));        // auto -> off: no question
                    t.tap(root.find(p, "appToggle-discord"));
                    t.check("discord asks", root.shown("confirm-discord"), true);
                    t.press(root.find(p, "rail-glass"));
                    t.press(root.find(p, "rail-apps"));
                    t.check("left and back: the app question is gone", root.shown("confirm-discord"), false);
                    t.tap(root.find(p, "appToggle-discord"));
                    root.type("discord");
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("a search drops the app question too", [root.shown("app:discord"), root.shown("confirm-discord")], [true, false]);
                    root.type("");
                    t.press(root.find(p, "rail-apps"));
                    // an app with no route to pick from: nothing forced is
                    // offered, the switch saves only the switch, the row says why
                    t.check("no routes listed", root.findAll(p, "route-md.example.Electron-", []).length, 0);
                    t.check("no route list: the reason shows", root.find(p, "reason-md.example.Electron").text, "family feishin does not list this app");
                    root.saveMark = PluginService.saves.length;
                    t.tap(root.find(p, "appToggle-md.example.Electron"));
                    t.check("a forced app with no route list does not ask", root.shown("confirm-md.example.Electron"), false);
                    t.check("and saves the switch only (no route)", root.saved("apps")["md.example.Electron"], {
                        "enabled": true
                    });
                    t.tap(root.find(p, "appToggle-md.example.Electron"));
                    t.check("off again", root.saved("apps")["md.example.Electron"], {
                        "enabled": false
                    });
                    // --- Pause: one write
                    root.saveMark = PluginService.saves.length;
                    t.press(root.find(p, "pauseButton"));
                }
            },
            {
                "wait": 20,
                "run": () => {
                    const p = root.page;
                    t.check("Pause writes glassEnabled once", PluginService.saves.slice(root.saveMark), [["appGlass", "glassEnabled", false]]);
                    t.press(root.find(p, "pauseButton"));
                    // --- the rail by keyboard: the focus moves with the arrows
                    t.press(root.find(p, "rail-glass"));
                    root.find(p, "rail-glass").forceActiveFocus();
                    root.find(p, "rail-glass").Keys.downPressed(null);
                    root.find(p, "rail-apps").Keys.downPressed(null);
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("two downs: Fade open and focused", [root.shown("page-fade"), root.find(p, "rail-fade").activeFocus], [true, true]);
                    root.find(p, "rail-fade").Keys.returnPressed(null);
                    t.check("Enter keeps Fade", [root.shown("page-fade"), root.shown("page-glass")], [true, false]);
                    root.find(p, "rail-fade").Keys.upPressed(null);
                    t.check("up: Apps focused", [root.shown("page-apps"), root.find(p, "rail-apps").activeFocus], [true, true]);
                    // Tab moves the focus without opening: the arrows step from the focused entry
                    root.find(p, "rail-advanced").forceActiveFocus();
                    root.find(p, "rail-advanced").Keys.downPressed(null);
                    t.check("down from a focused entry that is not open", [root.shown("page-about"), root.find(p, "rail-about").activeFocus], [true, true]);
                    root.find(p, "rail-glass").forceActiveFocus();
                    root.find(p, "rail-glass").Keys.upPressed(null);
                    t.check("up from the first wraps to the last", [root.shown("page-about"), root.find(p, "rail-about").activeFocus], [true, true]);
                    // a click takes the focus too: the arrows then step from there
                    root.find(p, "rail-apps").clicked();
                    t.check("a click focuses the entry", [root.shown("page-apps"), root.find(p, "rail-apps").activeFocus], [true, true]);
                    // --- the narrow rail: the badge stays a dot, the name shows on focus
                    root.page.width = 380;
                    root.type("fade");
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    const badge = root.find(p, "railCount-fade");
                    const entry = root.find(p, "rail-fade");
                    t.check("narrow badge size", [badge.visible, badge.width, badge.height], [true, 20, 20]);
                    t.ok("narrow badge inside its entry", badge.y >= 0 && badge.y + badge.height <= entry.height && badge.x + badge.width <= entry.width);
                    t.check("no name tip at rest", root.find(p, "railTip-fade").visible, false);
                    entry.forceActiveFocus();
                    t.check("the name beside a focused icon", [root.find(p, "railTip-fade").visible, root.find(p, "railTip-fade").text], [true, "Fade"]);
                    const about = root.find(p, "rail-about");
                    about.forceActiveFocus();
                    t.check("a dimmed entry's tip is not see-through", [about.dim, root.find(p, "railTip-about").visible, about.opacity, root.find(p, "railTip-about").opacity], [true, true, 1, 1]);
                    root.type("xyz");
                }
            },
            {
                "run": () => {
                    const q = root.find(root.page, "noResultsQuery");
                    t.check("a long query wraps, then elides", [q.wrapMode, q.elide, q.maximumLineCount], [Text.Wrap, Text.ElideRight, 2]);
                    // --- Esc in two stages: the first clears, the second lets go
                    const f = root.find(root.page, "searchField");
                    f.forceActiveFocus();
                    t.ok("the field has the focus", root.focusedIn(f));
                    f.Keys.escapePressed(null);
                    t.check("first Esc: cleared, still in the field", [root.find(root.page, "searchField").text, root.focusedIn(f)], ["", true]);
                    f.Keys.escapePressed(null);
                    t.check("second Esc: the focus leaves the field", root.focusedIn(f), false);
                    // --- a saved route the status no longer lists: the chips show
                    root.fresh(true, undefined, {
                        "apps": {
                            "vlc": {
                                "enabled": true,
                                "route": "no-such-route"
                            }
                        }
                    });
                }
            },
            {
                "wait": 20,
                "run": () => {
                    const p = root.page;
                    t.press(root.find(p, "rail-apps"));
                    t.check("one route, saved one stale: its chip shows", [root.shown("route-vlc-qt-style"), root.shown("route-solaar-gtk3")], [true, false]);
                    t.press(root.find(p, "route-vlc-qt-style"));
                    t.check("picking it saves it over the stale one", root.saved("apps").vlc.route, "qt-style");
                }
            },
            {
                "run": () => {
                    t.check("then the chips go", root.shown("route-vlc-qt-style"), false);
                    t.check("uninstall offered, no link hint", [root.find(root.page, "uninstallButton").enabled, root.shown("uninstallLinkHint")], [true, false]);
                    // --- the files are back but the plugin link stays
                    root.fresh(true, {
                        "status": root.status,
                        "lastError": "",
                        "syncing": false,
                        "action": "",
                        "uninstallState": "linkStays"
                    });
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.press(root.find(p, "rail-advanced"));
                    t.check("the link stays: Uninstall stays off", root.find(p, "uninstallButton").enabled, false);
                    t.check("and says how to finish", [root.shown("uninstallLinkHint"), root.find(p, "uninstallLinkHint").text.indexOf("appglass plugin remove") >= 0], [true, true]);
                    t.check("not the outside-link hint", root.shown("uninstallExternalHint"), false);
                    root.type("learn");
                }
            },
            {
                "run": () => {
                    t.check("a search for something else: no link hint", [root.shown("learnButton"), root.shown("uninstallLinkHint")], [true, false]);
                    // --- DMS loads the plugin from outside appglass's link:
                    // `appglass plugin remove` can do nothing there
                    root.fresh(true, {
                        "status": root.status,
                        "lastError": "",
                        "syncing": false,
                        "action": "",
                        "uninstallState": "external"
                    });
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.press(root.find(p, "rail-advanced"));
                    t.check("outside the link: Uninstall stays off", root.find(p, "uninstallButton").enabled, false);
                    t.check("no plugin remove hint", root.shown("uninstallLinkHint"), false);
                    t.check("says to turn it off in DMS", [root.shown("uninstallExternalHint"), root.find(p, "uninstallExternalHint").text.indexOf("DMS Settings > Plugins") >= 0], [true, true]);
                    t.check("set up again offered", root.shown("reinstallButton"), true);
                    t.check("the header says it", root.find(p, "headerStatus").text.indexOf("Uninstalled") === 0, true);
                    root.type("learn");
                }
            },
            {
                "run": () => {
                    t.check("a search for something else: no outside-link hint", [root.shown("learnButton"), root.shown("uninstallExternalHint"), root.shown("reinstallButton")], [true, false, false]);
                    root.fresh(true, {
                        "status": root.status,
                        "lastError": "",
                        "syncing": false,
                        "action": "",
                        "uninstallState": "removed"
                    });
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.press(root.find(p, "rail-advanced"));
                    t.check("uninstalled: Uninstall off, no hint", [root.find(p, "uninstallButton").enabled, root.shown("uninstallLinkHint")], [false, false]);
                    // nothing says glass is on, nothing offers a change the
                    // daemon would not sync
                    t.check("the header says it", root.find(p, "headerStatus").text.indexOf("Uninstalled") === 0, true);
                    t.check("no pause, learn or adopt", [root.find(p, "pauseButton").enabled, root.find(p, "learnButton").enabled, root.find(p, "adoptButton").enabled, root.find(p, "reportButton").enabled], [false, false, false, true]);
                    t.press(root.find(p, "rail-glass"));
                    t.check("no re-apply, no glass switch", [root.find(p, "reapplyButton").enabled, root.find(p, "glassToggle").enabled], [false, false]);
                    t.press(root.find(p, "rail-apps"));
                    const toggles = root.findAll(p, "appToggle-", []).filter(x => x.visible);
                    t.ok("the app switches are off limits", toggles.length > 0 && toggles.every(x => !x.enabled));
                    // the fade and the fallback too: a save there would be
                    // lost to the next Set up again, or never synced
                    t.press(root.find(p, "rail-fade"));
                    t.check("no fade setting", root.fadeIds.map(id => root.find(p, id).enabled), root.fadeIds.map(id => false));
                    t.press(root.find(p, "rail-fallback"));
                    t.check("no fallback setting", ["fallbackMode", "fallbackValue"].map(id => root.find(p, id).enabled), [false, false]);
                    const before = root.saved("inactiveDurationMs");
                    root.find(p, "page-fade").saveValue("inactiveDurationMs", 333);
                    t.check("a save while uninstalled is dropped", root.saved("inactiveDurationMs"), before);
                    // set up again: the user's click asks the daemon
                    t.press(root.find(p, "rail-advanced"));
                    t.check("set up again offered", root.shown("reinstallButton"), true);
                    t.press(root.find(p, "reinstallButton"));
                    t.check("set up again asks the daemon", root.daemon.calls, [["reinstall"]]);
                    // --- a failed remove: its error stays on the page
                    root.fresh(true, {
                        "status": root.status,
                        "lastError": "",
                        "syncing": false,
                        "action": "",
                        "uninstallState": "",
                        "uninstallError": "Uninstall stopped: boom. Glass is set up again from the current settings"
                    });
                }
            },
            {
                "run": () => {
                    const p = root.page;
                    t.press(root.find(p, "rail-advanced"));
                    t.check("the remove error shows", [root.shown("uninstallErrorInfo"), root.find(p, "uninstallErrorInfo").text.indexOf("boom") >= 0], [true, true]);
                    t.check("glass on: no set up again", root.shown("reinstallButton"), false);
                    t.check("the header as before", root.find(p, "headerStatus").text, "Glass on, 7 apps on glass");
                }
            }
        ]);
    }
}
