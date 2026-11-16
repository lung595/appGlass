import QtQuick
import Quickshell
import qs.Common
import qs.Services
import "components/logic.js" as Logic

// AppGlassSettings.qml: what it shows from the daemon's shared status, what
// each widget saves, the app list switches, Re-apply (a fake daemon records
// it). The page runs no command.
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
    function saved(key) {
        return SettingsData.getPluginSetting("appGlass", key, undefined);
    }

    Component.onCompleted: {
        root.status = JSON.parse(t.readFile("contract/status.json"));
        t.steps([
            {
                "run": () => root.fresh()
            },
            {
                "run": () => {
                    const p = root.page;
                    t.check("level shown, read only", root.find(p, "levelInfo").text, "Glass level: 60% (bars 65%), from the DMS window rule opacity");
                    t.ok("inactive at the floor explained", root.find(p, "inactiveInfo").text.indexOf("no change") > 0);
                    t.ok("summary", root.find(p, "summaryInfo").text.indexOf("glass") >= 0);
                    t.check("no error shown", root.find(p, "errorInfo").visible, false);
                    t.check("defaults loaded", [root.find(p, "glassToggle").value, root.find(p, "inactiveToggle").value, root.find(p, "inactiveLevel").value, root.find(p, "inactiveDuration").value, root.find(p, "inactiveEasing").value, root.find(p, "instantFallback").value, root.find(p, "fallbackMode").value], [true, true, 10, 180, "ease-out-cubic", false, "opaque"]);
                    t.check("fallback opacity hidden unless translucent", root.find(p, "fallbackValue").visible, false);
                    // the widgets save their keys
                    root.find(p, "inactiveLevel").value = 15;
                    root.find(p, "inactiveDuration").value = 300;
                    root.find(p, "inactiveEasing").choose("Linear");
                    root.find(p, "fallbackMode").choose("Translucent (text too)");
                    root.find(p, "glassToggle").value = false;
                    t.check("saved", [root.saved("inactiveMorePct"), root.saved("inactiveDurationMs"), root.saved("inactiveEasing"), root.saved("fallbackMode"), root.saved("glassEnabled")], [15, 300, "linear", "value", false]);
                    t.check("fallback opacity shown", root.find(p, "fallbackValue").visible, true);
                    t.check("what the daemon will sync", Logic.settingsFromPluginData(SettingsData.getPluginSettingsForPlugin("appGlass")).inactive, {
                        "enabled": true,
                        "factor": 0.85,
                        "durationMs": 300,
                        "easing": "linear",
                        "instantFallback": false
                    });
                    root.find(p, "inactiveToggle").value = false;
                    t.check("inactive controls hidden when off", [root.find(p, "inactiveLevel").visible, root.find(p, "inactiveDuration").visible, root.find(p, "inactiveEasing").visible, root.find(p, "instantFallback").visible], [false, false, false, false]);
                    t.check("inactive off saved", root.saved("inactiveEnabled"), false);
                }
            },
            {
                // --- the app list
                "run": () => {
                    const p = root.page;
                    const toggles = root.findAll(p, "appToggle-", []);
                    const switchable = Logic.appRows(root.status, "").filter(r => r.switchable).length;
                    t.check("one switch per switchable row", toggles.filter(x => x.visible).length, switchable);
                    const alac = root.find(p, "appToggle-Alacritty");
                    t.check("Alacritty on", alac.checked, true);
                    t.tap(alac);
                    t.check("apps saved", root.saved("apps"), {
                        "Alacritty": {
                            "enabled": false
                        }
                    });
                    t.check("switch shows the saved choice", alac.checked, false);
                    t.tap(alac);
                    t.check("and back", [root.saved("apps"), alac.checked], [{
                            "Alacritty": {
                                "enabled": true
                            }
                        }, true]);
                    root.find(p, "search").text = "flatseal";
                }
            },
            {
                "run": () => {
                    const toggles = root.findAll(root.page, "appToggle-", []);
                    t.check("search filters the rows", toggles.map(x => x.objectName), ["appToggle-com.github.tchx84.Flatseal"]);
                    // --- Re-apply
                    t.press(root.find(root.page, "reapplyButton"));
                    t.check("re-apply asks the daemon", root.daemon.calls, [["reapply", 0]]);
                    t.check("the page runs nothing", Proc.calls, []);
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
                    t.check("before a status", root.find(p, "levelInfo").text, "Glass level: not known yet");
                    t.check("error shown", [root.find(p, "errorInfo").visible, root.find(p, "errorInfo").text], [true, "appglass: sync: boom"]);
                    const b = root.find(p, "reapplyButton");
                    t.check("busy button", [b.text, b.enabled], ["Applying...", false]);
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
                "run": () => {
                    const p = root.page;
                    t.check("saved values loaded", root.find(p, "inactiveLevel").value, 20);
                    t.press(root.find(p, "reapplyButton"));
                    t.check("no daemon: a warning toast", ToastService.ofLevel("warning").map(x => x.message), ["appGlass: the plugin daemon is not running"]);
                }
            }
        ]);
    }
}
