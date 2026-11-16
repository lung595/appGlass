import QtQuick
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Services
import "components/logic.js" as Logic

// AppGlassDaemon.qml: what it runs (Proc records the argv and answers with
// canned output), when, and what it shares. Covers the first-start seed
// from `appglass get`, the settings file of each sync, the debounce, one
// sync at a time, errors, the status, the IPC commands and the teardown.
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

    property var defaults: ({})
    property string statusText: ""
    property var d: null
    property int mark: 0

    Component {
        id: daemonComponent
        AppGlassDaemon {
            pluginId: "appGlass"
            pluginService: PluginService
        }
    }

    // A clean shell, then a daemon. Nothing launches until Proc.flush().
    function fresh(seeded, getAnswer) {
        if (root.d) {
            root.d.destroy();
            root.d = null;
        }
        Proc.reset();
        Proc.autoRun = false;
        ToastService.reset();
        Quickshell.reset();
        Quickshell.environment = {
            "HOME": "/tmp/fakehome",
            "USER": "alice",
            "XDG_RUNTIME_DIR": "/tmp/fakehome/run"
        };
        PluginService.reset();
        SettingsData.reset();
        const data = {
            "enabled": true
        };
        if (seeded)
            data.seeded = true;
        SettingsData.pluginSettings = {
            "appGlass": data
        };
        FileViewLog.reset();
        FileViewLog.put(root.rulesPath, "window-rule {\n    opacity 0.8\n}\n");
        PluginService.pluginPaths = {
            "appGlass": root.dir + "/"
        };
        Proc.setResult(Logic.SEED_ID, getAnswer === undefined ? JSON.stringify(root.defaults) : getAnswer, 0);
        Proc.setResult(Logic.SYNC_ID, "apps: 7 glass\n", 0);
        Proc.setResult(Logic.STATUS_ID, root.statusText, 0);
        root.d = daemonComponent.createObject(root);
        return root.d;
    }

    function syncs() {
        return Proc.launched.filter(l => l.id === Logic.SYNC_ID);
    }
    function lastSyncSettings() {
        const l = root.syncs();
        return l.length ? JSON.parse(l[l.length - 1].settingsFile) : null;
    }
    function vars() {
        return PluginService.globalVars["appGlass"] || {};
    }
    function pdata() {
        return SettingsData.getPluginSettingsForPlugin("appGlass");
    }

    Component.onCompleted: {
        root.defaults = JSON.parse(t.readFile("contract/defaults.json"));
        root.statusText = t.readFile("contract/status.json");
        t.steps([
            {
                // --- first start: the plugin data is seeded from `appglass get`
                "run": () => {
                    const cli = JSON.parse(JSON.stringify(root.defaults));
                    cli.levels.content = 0.8;
                    cli.inactive.factor = 0.85;
                    cli.apps = {
                        "steam": {
                            "enabled": true,
                            "route": "cdp"
                        }
                    };
                    root.fresh(false, JSON.stringify(cli));
                    t.check("first start asks appglass get", Proc.calls.map(c => c.command), [[root.bin, "get"]]);
                    t.check("nothing synced before the seed", root.syncs().length, 0);
                    Proc.flush();       // get
                    const pd = root.pdata();
                    t.check("seeded", [pd.seeded, pd.inactiveMorePct, pd.levels.content, pd.apps], [true, 15, 0.8, {
                            "steam": {
                                "enabled": true,
                                "route": "cdp"
                            }
                        }]);
                    t.ok("syncing shared", root.vars().syncing === true);
                    Proc.flush();       // sync
                    t.check("one sync, with the settings appglass had", root.lastSyncSettings(), cli);
                    t.check("sync argv", root.syncs()[0].command, Logic.syncArgv(root.bin, root.runFile));
                    Proc.flush();       // status
                    t.check("status shared", root.vars().status.version, 1);
                    t.check("syncing done", root.vars().syncing, false);
                    t.ok("last sync stamped", root.vars().lastSync !== "");
                    t.check("no toast", ToastService.log, []);
                }
            },
            {
                // --- seeded: no get, a sync at once
                "run": () => {
                    root.fresh(true);
                    t.check("seeded start syncs", Proc.calls.map(c => c.id), [Logic.SYNC_ID]);
                    Proc.flush();
                    t.check("the defaults", root.lastSyncSettings(), root.defaults);
                    Proc.flush();
                    root.mark = root.syncs().length;
                    // the same settings saved again: nothing to do
                    PluginService.savePluginData("appGlass", "inactiveMorePct", 10);
                    // two changes close together: one sync
                    PluginService.savePluginData("appGlass", "inactiveDurationMs", 250);
                    PluginService.savePluginData("appGlass", "inactiveMorePct", 20);
                }
            },
            {
                "wait": 700,
                "run": () => {
                    t.check("debounced into one launch request", Proc.pendingIds(), [Logic.SYNC_ID]);
                    // a change while it runs: one more sync after it
                    PluginService.savePluginData("appGlass", "inactiveEnabled", false);
                    Proc.flush();
                    t.check("first sync read both changes", [root.syncs().length - root.mark, root.lastSyncSettings().inactive.durationMs, root.lastSyncSettings().inactive.factor, root.lastSyncSettings().inactive.enabled], [1, 250, 0.8, true]);
                    t.check("the next one waits for nothing more", Proc.pendingIds(), [Logic.SYNC_ID]);
                    Proc.flush();
                    t.check("then the change made meanwhile", [root.syncs().length - root.mark, root.lastSyncSettings().inactive.enabled], [2, false]);
                    t.check("one status after the run", Proc.pendingIds(), [Logic.STATUS_ID]);
                    Proc.flush();
                }
            },
            {
                "wait": 700,
                "run": () => {
                    t.check("no sync for a value saved back", Proc.pendingIds(), []);
                    // --- a failed sync: the appglass line shown and toasted
                    Proc.setResult(Logic.SYNC_ID, "apps: 1 glass\nappglass: sync: x rejected, nothing saved: bad\n", 1);
                    t.check("IPC sync", IpcRegistry.call("appGlass", "sync"), "OK");
                    Proc.flush();
                    t.check("error shared", root.vars().lastError, "appglass: sync: x rejected, nothing saved: bad");
                    t.check("error toast", ToastService.ofLevel("error").map(x => x.message), ["appGlass: appglass: sync: x rejected, nothing saved: bad"]);
                    Proc.flush();
                    // the next good one clears it, and Re-apply toasts
                    Proc.setResult(Logic.SYNC_ID, "", 0);
                    root.d.requestSync("reapply", 0);
                    Proc.flush();
                    t.check("error cleared", root.vars().lastError, "");
                    t.check("re-applied toast", ToastService.ofLevel("info").map(x => x.message), ["appGlass: re-applied"]);
                    Proc.flush();
                }
            },
            {
                // --- IPC
                "run": () => {
                    t.check("toggle off", IpcRegistry.call("appGlass", "toggle"), "glass off");
                    t.check("saved", root.pdata().glassEnabled, false);
                    t.check("app off", IpcRegistry.call("appGlass", "app", "Alacritty", "off"), "Alacritty off");
                    t.check("app usage", IpcRegistry.call("appGlass", "app", "Alacritty", "maybe"), "usage: app <key> on|off");
                    t.check("apps saved", root.pdata().apps, {
                        "Alacritty": {
                            "enabled": false
                        }
                    });
                    t.ok("status answers JSON", JSON.parse(IpcRegistry.call("appGlass", "status")).version === 1);
                }
            },
            {
                "wait": 700,
                "run": () => {
                    Proc.flush();
                    const s = root.lastSyncSettings();
                    t.check("the sync carries both", [s.enabled, s.apps], [false, {
                            "Alacritty": {
                                "enabled": false
                            }
                        }]);
                    Proc.flush();
                    t.check("toggle on", IpcRegistry.call("appGlass", "toggle"), "glass on");
                }
            },
            {
                "wait": 700,
                "run": () => {
                    Proc.flush();       // the toggle's sync
                    Proc.flush();       // its status
                    t.check("glass back on", root.lastSyncSettings().enabled, true);
                    // --- the DMS window rules changed: only the status again
                    root.mark = root.syncs().length;
                    FileViewLog.change(root.rulesPath, "window-rule {\n    opacity 0.9\n}\n");
                }
            },
            {
                "wait": 700,
                "run": () => {
                    t.check("window rules: status only", Proc.pendingIds(), [Logic.STATUS_ID]);
                    Proc.flush();
                    t.check("no sync for them", root.syncs().length, root.mark);
                    root.d.destroy();
                    root.d = null;
                }
            },
            {
                // --- appglass get fails: nothing synced over the CLI settings
                "run": () => {
                    root.fresh(false, "appglass: boom\n");
                    Proc.setResult(Logic.SEED_ID, "appglass: boom\n", 1);
                    Proc.flush();
                    t.check("no sync", Proc.pendingIds(), []);
                    t.check("not seeded", root.pdata().seeded, undefined);
                    t.check("error shown", root.vars().lastError, "cannot read the appglass settings: appglass: boom");
                    // the next request tries the seed again
                    Proc.setResult(Logic.SEED_ID, JSON.stringify(root.defaults), 0);
                    t.check("IPC sync before the seed", IpcRegistry.call("appGlass", "sync"), "not ready");
                    t.check("seed retried", Proc.pendingIds(), [Logic.SEED_ID]);
                    Proc.flush();
                    Proc.flush();
                    t.check("then synced", root.syncs().length, 1);
                    Proc.flush();
                }
            },
            {
                // --- teardown
                "run": () => {
                    root.d.destroy();
                    root.d = null;
                }
            },
            {
                "run": () => {
                    t.check("a shell quit removes nothing", Quickshell.detached, []);
                    root.fresh(true);
                    Proc.flush();
                    Proc.flush();
                    SettingsData.setPluginSetting("appGlass", "enabled", false);
                    root.d.destroy();
                    root.d = null;
                }
            },
            {
                "run": () => {
                    // disable / re-enable in DMS Settings > Plugins must leave the
                    // glass files and the units alone: only `appglass remove` uninstalls
                    t.check("disabling the plugin removes nothing", Quickshell.detached, []);
                    t.check("and toasts nothing", ToastService.ofLevel("info").map(x => x.message), []);
                }
            }
        ]);
    }
}
