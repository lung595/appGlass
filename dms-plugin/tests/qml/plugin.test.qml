import QtQuick
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Services
import "components/logic.js" as Logic

// The plugin as DMS runs it: the real daemon, the settings page and the bar
// pill together (Proc records the commands). A switch on the page reaches
// `appglass sync` with the app in its settings file; the pill's pause too.
// Disabling the plugin (everything destroyed) and reloading it (everything
// built again) run nothing but sync, status and get, never with the glass
// off unless it was saved off, and never an Advanced action.
Item {
    id: root

    Harness {
        id: t
        timeoutMs: 60000
    }

    readonly property string dir: "/tmp/fakehome/.config/DankMaterialShell/plugins/appGlass"
    readonly property string bin: dir + "/../bin/appglass"
    readonly property string runFile: "/tmp/fakehome/run/appglass-plugin-settings.json"
    readonly property string rulesPath: "/tmp/fakehome/.config/niri/dms/windowrules.kdl"

    property string statusText: ""
    property var d: null
    property var page: null
    property var w: null
    property var pill: null
    property int mark: 0
    property int callsMark: 0

    Component {
        id: daemonComponent
        AppGlassDaemon {
            pluginId: "appGlass"
            pluginService: PluginService
        }
    }
    Component {
        id: pageComponent
        AppGlassSettings {
            width: 640
        }
    }
    Component {
        id: widgetComponent
        AppGlassWidget {
            pluginId: "appGlass"
            pluginService: PluginService
        }
    }

    // DMS loading the plugin: the daemon, then the page and the pill
    function load() {
        root.d = daemonComponent.createObject(root);
        PluginService.pluginDaemonInstances = {
            "appGlass": root.d
        };
        root.page = pageComponent.createObject(root, {
            "pluginService": PluginService
        });
        root.w = widgetComponent.createObject(root);
        root.pill = root.w.horizontalBarPill.createObject(root);
    }
    // DMS disabling it: everything goes
    function unload() {
        for (const o of [root.pill, root.w, root.page, root.d]) {
            if (o)
                o.destroy();
        }
        root.pill = root.w = root.page = root.d = null;
        PluginService.pluginDaemonInstances = {};
    }

    function fresh() {
        root.unload();
        Proc.reset();
        Proc.autoRun = false;
        ToastService.reset();
        Quickshell.reset();
        Quickshell.environment = {
            "HOME": "/tmp/fakehome",
            "USER": "alice",
            "XDG_RUNTIME_DIR": "/tmp/fakehome/run"
        };
        PopoutService.reset();
        PluginService.reset();
        SettingsData.reset();
        SettingsData.pluginSettings = {
            "appGlass": {
                "enabled": true,
                "seeded": true
            }
        };
        FileViewLog.reset();
        FileViewLog.put(root.rulesPath, "window-rule {\n    opacity 0.6\n}\n");
        PluginService.pluginPaths = {
            "appGlass": root.dir + "/"
        };
        Proc.setResult(Logic.SYNC_ID, "apps: 7 glass\n", 0);
        Proc.setResult(Logic.STATUS_ID, root.statusText, 0);
        root.load();
    }

    // Launch what is pending until nothing is
    function drain() {
        for (let i = 0; i < 10 && Proc.pendingIds().length; i++)
            Proc.flush();
    }
    function since(n) {
        return Proc.launched.slice(n);
    }
    function syncs(list) {
        return list.filter(l => l.id === Logic.SYNC_ID).map(l => JSON.parse(l.settingsFile));
    }
    function find(item, name) {
        if (!item)
            return null;
        if (item.objectName === name)
            return item;
        for (const kid of item.children || []) {
            const hit = root.find(kid, name);
            if (hit)
                return hit;
        }
        return null;
    }

    Component.onCompleted: {
        root.statusText = t.readFile("contract/status.json");
        t.steps([
            {
                "run": () => root.fresh()
            },
            {
                "wait": 700,
                "run": () => {
                    root.drain();
                    t.ok("the status reached the page", root.find(root.page, "status-Alacritty") !== null);
                    t.check("and the pill", root.find(root.pill, "pillText").text, "7");
                    root.mark = Proc.launched.length;
                    // the page's switch
                    t.press(root.find(root.page, "rail-apps"));
                    t.tap(root.find(root.page, "appToggle-Alacritty"));
                }
            },
            {
                "wait": 700,
                "run": () => {
                    root.drain();
                    const l = root.since(root.mark).filter(x => x.id === Logic.SYNC_ID);
                    t.check("one sync, the CLI's argv", l.map(x => x.command), [Logic.syncArgv(root.bin, root.runFile)]);
                    t.check("the app in its settings file", root.syncs(l)[0].apps, {
                        "Alacritty": {
                            "enabled": false
                        }
                    });
                    // a route on the page: in the next settings file
                    t.press(root.find(root.page, "route-discord-electron-hook"));
                    root.mark = Proc.launched.length;
                }
            },
            {
                "wait": 700,
                "run": () => {
                    root.drain();
                    t.check("the route synced", root.syncs(root.since(root.mark)).map(s => s.apps.discord), [{
                            "route": "electron-hook"
                        }]);
                    // the pill's pause
                    root.mark = Proc.launched.length;
                    root.w.pillRightClickAction();
                }
            },
            {
                "wait": 700,
                "run": () => {
                    root.drain();
                    t.check("pause synced", root.syncs(root.since(root.mark)).map(s => s.enabled), [false]);
                    t.check("the page shows it", root.find(root.page, "pauseButton").text, "Resume glass");
                    t.press(root.find(root.page, "pauseButton"));
                    root.mark = Proc.launched.length;
                }
            },
            {
                "wait": 700,
                "run": () => {
                    root.drain();
                    t.check("resume from the page", root.syncs(root.since(root.mark)).map(s => s.enabled), [true]);
                    t.check("nothing detached", Quickshell.detached, []);
                    // --- disable: everything destroyed
                    root.mark = Proc.launched.length;
                    root.callsMark = Proc.calls.length;
                    root.unload();
                }
            },
            {
                "wait": 700,
                "run": () => {
                    root.drain();
                    t.check("disabled: nothing asked, nothing run", [Proc.calls.length - root.callsMark, Proc.launched.length - root.mark], [0, 0]);
                    // --- reload: built again
                    root.load();
                }
            },
            {
                "wait": 700,
                "run": () => {
                    root.drain();
                    const l = root.since(root.mark);
                    const allowed = [Logic.SYNC_ID, Logic.STATUS_ID, Logic.SEED_ID];
                    t.check("reload: sync, status and get only", l.filter(x => allowed.indexOf(x.id) < 0).map(x => x.id), []);
                    t.ok("it syncs again", l.some(x => x.id === Logic.SYNC_ID));
                    t.check("with the glass on and the saved apps", root.syncs(l).map(s => [s.enabled, s.apps.Alacritty]), root.syncs(l).map(s => [true, {
                                "enabled": false
                            }]));
                    t.check("no Advanced action was ever asked", Proc.calls.filter(c => Object.values(Logic.ACTION_IDS).indexOf(c.id) >= 0), []);
                    t.check("no remove in any command", Proc.calls.filter(c => c.command.indexOf("remove") >= 0), []);
                    t.check("nothing detached", Quickshell.detached, []);
                    t.check("the pill is back", root.find(root.pill, "pillText").text, "7");
                    root.unload();
                }
            }
        ]);
    }
}
