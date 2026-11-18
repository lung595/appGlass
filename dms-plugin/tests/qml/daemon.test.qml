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
    function fresh(seeded, getAnswer, extra) {
        if (root.d) {
            // destroy() is deferred: the dying daemon would see the stub
            // reset below as a settings change (DMS never resets its data)
            if (root.d.body)
                root.d.body.ready = false;
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
        for (const k of Object.keys(extra || {}))
            data[k] = extra[k];
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

    // Ends a scenario: the old daemon's teardown releases the shared Proc
    // ids, so it must be gone before the next fresh() in a later step
    function drop() {
        if (root.d)
            root.d.destroy();
        root.d = null;
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
                    t.check("start sync argv: no switch", root.syncs()[0].command, Logic.syncArgv(root.bin, root.runFile, true));
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
                    t.check("seeded start: no switch", Proc.calls[0].command, Logic.syncArgv(root.bin, root.runFile, true));
                    Proc.flush();
                    t.check("the defaults", root.lastSyncSettings(), root.defaults);
                    Proc.flush();
                    root.mark = root.syncs().length;
                    // the same settings saved again: nothing to do
                    PluginService.savePluginData("appGlass", "inactiveMorePct", 10);
                    t.check("nothing owed after the start sync", PluginService.loadPluginData("appGlass", "syncPending", false), false);
                    // two changes close together: one sync
                    PluginService.savePluginData("appGlass", "inactiveDurationMs", 250);
                    PluginService.savePluginData("appGlass", "inactiveMorePct", 20);
                    // owed at once, before the debounce: a restart now keeps it
                    t.check("a change waiting for its sync is owed", PluginService.loadPluginData("appGlass", "syncPending", false), true);
                }
            },
            {
                // a shell restart within the debounce: the next start sync
                // applies the switch (not --no-switch), then nothing is owed
                "run": () => {
                    root.fresh(true, undefined, {
                        "syncPending": true,
                        "glassEnabled": false
                    });
                    t.check("an owed change: the start sync applies the switch", Proc.calls[0].command, Logic.syncArgv(root.bin, root.runFile, false));
                    Proc.flush();
                    t.check("synced off", root.lastSyncSettings().enabled, false);
                    t.check("then nothing owed", PluginService.loadPluginData("appGlass", "syncPending", false), false);
                    Proc.flush();
                    // back to the run above
                    root.fresh(true);
                    Proc.flush();
                    Proc.flush();
                    root.mark = root.syncs().length;
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
                    // a family key too (the documented way to take a Native family out)
                    t.check("family off", IpcRegistry.call("appGlass", "app", "gtk3", "off"), "gtk3 off");
                    t.check("apps saved", root.pdata().apps, {
                        "Alacritty": {
                            "enabled": false
                        },
                        "gtk3": {
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
                            },
                            "gtk3": {
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
                // --- pause / resume (the bar pill and the page do the same)
                "run": () => {
                    t.check("IPC pause", IpcRegistry.call("appGlass", "pause"), "glass off");
                    t.check("paused saved", root.pdata().glassEnabled, false);
                    t.check("IPC resume", IpcRegistry.call("appGlass", "resume"), "glass on");
                    t.check("resumed saved", root.pdata().glassEnabled, true);
                }
            },
            {
                "wait": 700,
                "run": () => {
                    t.check("pause then resume: one sync", Proc.pendingIds(), [Logic.SYNC_ID]);
                    Proc.flush();
                    t.check("synced on", root.lastSyncSettings().enabled, true);
                    Proc.flush();
                    // --- Settings > Advanced: the CLI's commands, one at a time
                    Proc.setResult(Logic.ACTION_IDS.learn, "Alacritty  terminal  libvte\nlearned 3 windows: ~/.cache/appglass/learned.json\n", 0);
                    t.check("learn starts", root.d.runAction("learn"), true);
                    t.check("one action at a time", root.d.runAction("adopt"), false);
                    t.check("action shared", root.vars().action, "learn");
                    Proc.flush();
                    t.check("learn argv", Proc.lastCommand(Logic.ACTION_IDS.learn), Logic.learnArgv(root.bin));
                    t.check("action done", root.vars().action, "");
                    t.check("learn toast", ToastService.ofLevel("info").map(x => x.message).slice(-1), ["appGlass: learned 3 windows: ~/.cache/appglass/learned.json"]);
                    t.check("learned apps get applied", Proc.pendingIds(), [Logic.SYNC_ID]);
                    Proc.flush();
                    Proc.flush();
                    t.check("an unknown action runs nothing", [root.d.runAction("rm -rf"), Proc.pendingIds()], [false, []]);
                    // a status asked while one runs: the newer answer is not lost
                    // (DMS's Proc keeps one callback per id and drops it after the first exit)
                    const statusRuns = () => Proc.calls.filter(c => c.id === Logic.STATUS_ID).length;
                    const s0 = statusRuns();
                    root.d.body.refreshStatus();
                    root.d.body.refreshStatus();
                    t.check("a status while one runs: one run now", [statusRuns() - s0, Proc.pendingIds()], [1, [Logic.STATUS_ID]]);
                    Proc.flush();
                    t.check("then one more for the newer answer", [statusRuns() - s0, Proc.pendingIds()], [2, [Logic.STATUS_ID]]);
                    Proc.flush();
                    t.check("and no more", Proc.pendingIds(), []);
                    Proc.setResult(Logic.ACTION_IDS.adopt, "appglass: adopt: ~/x changed since\n", 1);
                    root.d.runAction("adopt");
                    Proc.flush();
                    t.check("adopt argv", Proc.lastCommand(Logic.ACTION_IDS.adopt), Logic.adoptArgv(root.bin));
                    // adopt and remove are never killed half way (a timeout would cut them)
                    const timeouts = id => Proc.calls.filter(c => c.id === id).map(c => c.timeoutMs);
                    t.check("adopt has no timeout, learn has one", [timeouts(Logic.ACTION_IDS.adopt).pop(), timeouts(Logic.ACTION_IDS.learn).pop()], [Proc.noTimeout, Logic.ACTION_TIMEOUT_MS]);
                    t.check("adopt error shared", root.vars().lastError, "appglass: adopt: ~/x changed since");
                    t.check("a failed action: the status only", Proc.pendingIds(), [Logic.STATUS_ID]);
                    Proc.flush();
                    // --- the report: copied with DMS's own clipboard command
                    Quickshell.reset();
                    root.d.copyReport();
                    t.check("report copied", Quickshell.detached, [["dms", "cl", "copy", Logic.reportText(root.vars().status, root.pdata().apps, true)]]);
                    t.check("report toast", ToastService.ofLevel("info").map(x => x.message).slice(-1), ["appGlass: report copied"]);
                    Quickshell.reset();
                    // --- uninstall: everything out, then no sync
                    root.mark = root.syncs().length;
                    Proc.setResult(Logic.ACTION_IDS.uninstall, "settings: removed\n", 0);
                    Proc.setResult(Logic.UNLINK_ID, "plugin: removed ~/.config/DankMaterialShell/plugins/appGlass\n", 0);
                    root.d.runAction("uninstall");
                    Proc.flush();
                    t.check("uninstall argv", Proc.lastCommand(Logic.ACTION_IDS.uninstall), Logic.uninstallArgv(root.bin));
                    t.check("remove has no timeout", Proc.calls.filter(c => c.id === Logic.ACTION_IDS.uninstall).map(c => c.timeoutMs).pop(), Proc.noTimeout);
                    t.check("then the plugin link", [Proc.pendingIds(), root.d.uninstalled], [[Logic.UNLINK_ID], true]);
                    // a restart that kills the unlink must not hide that the link may stay
                    t.check("the unlink is kept before it runs", root.pdata().uninstallState, "unlinking");
                    Proc.flush();
                    t.check("unlink argv", Proc.lastCommand(Logic.UNLINK_ID), Logic.unlinkArgv(root.bin));
                    t.check("seed again on a new install", root.pdata().seeded, false);
                    t.check("the uninstall is kept in the plugin data", root.pdata().uninstallState, "removed");
                    t.check("uninstall toast", ToastService.ofLevel("info").map(x => x.message).slice(-1), ["appGlass: uninstalled, every file restored"]);
                    PluginService.savePluginData("appGlass", "inactiveMorePct", 5);
                    t.check("IPC sync after it", IpcRegistry.call("appGlass", "sync"), "uninstalled");
                    t.check("the other IPC changes after it", ["toggle", "pause", "resume"].map(c => IpcRegistry.call("appGlass", c)).concat([IpcRegistry.call("appGlass", "app", "Alacritty", "off")]), ["uninstalled", "uninstalled", "uninstalled", "uninstalled"]);
                    t.check("the page learns it is gone", root.vars().uninstallState, "removed");
                    t.check("no other action after it", root.d.runAction("learn"), false);
                }
            },
            {
                "wait": 700,
                "run": () => {
                    t.check("no sync after an uninstall", [Proc.pendingIds(), root.syncs().length - root.mark], [[], 0]);
                }
            },
            {
                "run": () => root.drop()
            },
            {
                // --- uninstall while a change waits for its debounce: the
                // change is dropped, no sync runs beside or after `remove`
                "run": () => {
                    root.fresh(true);
                    Proc.flush();
                    Proc.flush();
                    root.mark = root.syncs().length;
                    PluginService.savePluginData("appGlass", "inactiveMorePct", 5);
                    t.check("a sync waits", root.vars().syncing, true);
                    t.check("uninstall starts", root.d.runAction("uninstall"), true);
                    t.check("the waiting sync dropped", [Proc.pendingIds(), root.vars().syncing], [[Logic.ACTION_IDS.uninstall], false]);
                    // the page stays editable while it runs
                    PluginService.savePluginData("appGlass", "inactiveMorePct", 7);
                    t.check("IPC sync while it runs", IpcRegistry.call("appGlass", "sync"), "uninstalling");
                    const before = JSON.stringify(root.pdata());
                    t.check("the other IPC changes while it runs", ["toggle", "pause", "resume"].map(c => IpcRegistry.call("appGlass", c)).concat([IpcRegistry.call("appGlass", "app", "Alacritty", "off")]), ["uninstalling", "uninstalling", "uninstalling", "uninstalling"]);
                    t.check("and save nothing", JSON.stringify(root.pdata()), before);
                    t.check("no second action", root.d.runAction("learn"), false);
                }
            },
            {
                "wait": 700,
                "run": () => {
                    t.check("nothing beside the uninstall", Proc.pendingIds(), [Logic.ACTION_IDS.uninstall]);
                    Proc.flush();
                    Proc.flush();
                    t.check("no sync launched with it", root.syncs().length - root.mark, 0);
                    t.check("uninstalled", [root.d.uninstalled, Proc.pendingIds()], [true, []]);
                    root.drop();
                }
            },
            {
                "run": () => {
                    // --- uninstall while a sync runs, one more queued: held
                    // until that sync ends, the queued one dropped
                    root.fresh(true);
                    root.mark = root.syncs().length;
                    t.check("a sync running", Proc.pendingIds(), [Logic.SYNC_ID]);
                    PluginService.savePluginData("appGlass", "inactiveMorePct", 6);
                    t.check("uninstall accepted", root.d.runAction("uninstall"), true);
                    t.check("held: not launched beside the sync", Proc.pendingIds(), [Logic.SYNC_ID]);
                    t.check("the action shows at once", root.vars().action, "uninstall");
                    Proc.flush();
                    t.check("the sync ended: the uninstall runs, the queued sync does not", Proc.pendingIds(), [Logic.ACTION_IDS.uninstall]);
                    Proc.flush();
                    Proc.flush();
                    t.check("only the sync that ran already", [root.syncs().length - root.mark, root.d.uninstalled, Proc.pendingIds()], [1, true, []]);
                }
            },
            {
                "wait": 700,
                "run": () => {
                    t.check("still no sync", [Proc.pendingIds(), root.syncs().length - root.mark], [[], 1]);
                    root.drop();
                }
            },
            {
                "run": () => {
                    // --- `remove` worked, the plugin link did not: still
                    // uninstalled (no sync brings the glass back)
                    root.fresh(true);
                    Proc.flush();
                    Proc.flush();
                    root.mark = root.syncs().length;
                    Proc.setResult(Logic.UNLINK_ID, "appglass: plugin remove: ~/.config/DankMaterialShell/plugins/appGlass is not a link to this repository\n", 1);
                    root.d.runAction("uninstall");
                    Proc.flush();
                    Proc.flush();
                    t.check("uninstalled all the same", [root.d.uninstalled, root.vars().action], [true, ""]);
                    t.ok("the link error said", ToastService.ofLevel("error").slice(-1)[0].message.indexOf("not a link") > 0);
                    t.ok("with the command to finish it", ToastService.ofLevel("error").slice(-1)[0].message.indexOf("appglass plugin remove") > 0);
                    t.check("the page learns the link stays", root.vars().uninstallState, "linkStays");
                    t.check("and so does the plugin data", root.pdata().uninstallState, "linkStays");
                    t.check("no second uninstall", root.d.runAction("uninstall"), false);
                    PluginService.savePluginData("appGlass", "inactiveMorePct", 9);
                    t.check("IPC sync after it", IpcRegistry.call("appGlass", "sync"), "uninstalled");
                }
            },
            {
                "wait": 700,
                "run": () => {
                    t.check("no sync after a half uninstall", [Proc.pendingIds(), root.syncs().length - root.mark], [[], 0]);
                    root.drop();
                }
            },
            {
                "run": () => {
                    // --- a restart that killed `appglass plugin remove`:
                    // the files are back, the link loaded this body again
                    root.fresh(true, undefined, {
                        "uninstallState": "unlinking"
                    });
                    t.check("a cut unlink: uninstalled, the link stays", [root.d.uninstalled, root.vars().uninstallState, root.pdata().uninstallState, Proc.calls.map(c => c.id)], [true, "linkStays", "linkStays", []]);
                    root.drop();
                }
            },
            {
                "run": () => {
                    // --- a reload (or a shell restart) after it: still
                    // uninstalled, nothing seeds or syncs the glass back
                    root.fresh(true, undefined, {
                        "uninstallState": "linkStays"
                    });
                    t.check("a reload after an uninstall stays uninstalled", [root.d.uninstalled, root.vars().uninstallState], [true, "linkStays"]);
                    t.check("IPC after the reload", ["sync", "toggle", "pause", "resume"].map(c => IpcRegistry.call("appGlass", c)), ["uninstalled", "uninstalled", "uninstalled", "uninstalled"]);
                    t.check("no action after the reload", root.d.runAction("learn"), false);
                    PluginService.savePluginData("appGlass", "inactiveMorePct", 4);
                }
            },
            {
                "wait": 700,
                "run": () => {
                    t.check("no seed, no sync after the reload", Proc.calls.map(c => c.id), []);
                    // only an explicit set up again (the page's button) brings it back
                    t.check("set up again", root.d.reinstall(), true);
                    t.check("the uninstall forgotten", [root.d.uninstalled, root.pdata().uninstallState, root.vars().uninstallState], [false, "", ""]);
                    t.check("it seeds from appglass get", Proc.pendingIds(), [Logic.SEED_ID]);
                    Proc.flush();
                    t.check("then syncs", Proc.pendingIds(), [Logic.SYNC_ID]);
                    Proc.flush();
                    Proc.flush();
                    t.check("set up again only once", root.d.reinstall(), false);
                    root.drop();
                }
            },
            {
                "run": () => {
                    // --- `remove` failed: it stopped, syncing goes on
                    root.fresh(true);
                    Proc.flush();
                    Proc.flush();
                    root.mark = root.syncs().length;
                    Proc.setResult(Logic.ACTION_IDS.uninstall, "appglass: remove: boom\n", 1);
                    root.d.runAction("uninstall");
                    // a change while it runs: kept for after
                    PluginService.savePluginData("appGlass", "inactiveMorePct", 11);
                    t.check("not run beside the remove", Proc.pendingIds(), [Logic.ACTION_IDS.uninstall]);
                    Proc.flush();
                    t.check("a failed remove: not uninstalled, no unlink, a sync at once", [root.d.uninstalled, Proc.pendingIds(), root.vars().uninstallState || ""], [false, [Logic.SYNC_ID], ""]);
                    t.ok("the remove error said", ToastService.ofLevel("error").slice(-1)[0].message.indexOf("boom") > 0);
                    Proc.flush();
                    t.check("the sync carries the change made during the remove", root.lastSyncSettings().inactive.factor, 0.89);
                    t.ok("the remove error stays after that sync", (root.vars().uninstallError || "").indexOf("boom") >= 0);
                    // a remove that stops can have restored some files already:
                    // the text says it stopped, not that nothing was removed
                    t.check("the remove error says it stopped and glass is back", root.vars().uninstallError, "Uninstall stopped: " + Logic.errorText("appglass: remove: boom\n", 1) + ". Glass is set up again from the current settings");
                    t.check("the IPC works again", IpcRegistry.call("appGlass", "pause"), "glass off");
                    Proc.flush();
                }
            },
            {
                "wait": 700,
                "run": () => {
                    t.check("the pause syncs", Proc.pendingIds(), [Logic.SYNC_ID]);
                    Proc.flush();
                    Proc.flush();
                    // a new try: the old stop is not shown beside "Uninstalling..."
                    t.check("uninstall again", root.d.runAction("uninstall"), true);
                    t.check("a retry clears the old remove error", root.vars().uninstallError, "");
                    Proc.flush();
                    t.ok("its own stop is said again", (root.vars().uninstallError || "").indexOf("boom") >= 0);
                    Proc.flush();
                    Proc.flush();
                }
            },
            {
                "run": () => {
                    // --- a reload (or a shell restart) while `appglass remove`
                    // runs: the old body's callback never comes; the new one
                    // neither seeds nor syncs, and runs no remove on its own
                    root.drop();
                    root.fresh(true);
                    Proc.flush();
                    Proc.flush();
                    root.d.runAction("uninstall");
                    t.check("the uninstall is kept before it runs", root.pdata().uninstallState, "removing");
                    root.drop();
                }
            },
            {
                "run": () => {
                    root.mark = Proc.calls.length;
                    root.d = daemonComponent.createObject(root);
                    t.check("the new body runs nothing", Proc.calls.slice(root.mark).map(c => c.id), []);
                    t.check("it says the uninstall may not have finished", [root.vars().uninstallState, IpcRegistry.call("appGlass", "sync"), IpcRegistry.call("appGlass", "pause")], ["interrupted", "uninstalling", "uninstalling"]);
                    t.ok("and how to go on", (root.vars().uninstallError || "").indexOf("Uninstall again") >= 0);
                    t.ok("never that it surely stopped (the remove may have ended)", (root.vars().uninstallError || "").indexOf("may not have finished") >= 0);
                    PluginService.savePluginData("appGlass", "inactiveMorePct", 7);
                    t.check("no other action", root.d.runAction("learn"), false);
                }
            },
            {
                "wait": 700,
                "run": () => {
                    t.check("a change syncs nothing", Proc.calls.slice(root.mark).map(c => c.id), []);
                    // the user's own Uninstall finishes it
                    t.check("uninstall again", root.d.runAction("uninstall"), true);
                    t.check("it runs the remove", Proc.pendingIds(), [Logic.ACTION_IDS.uninstall]);
                    Proc.flush();       // remove
                    Proc.flush();       // unlink
                    t.check("then uninstalled", [root.d.uninstalled, root.pdata().uninstallState, root.pdata().seeded, root.vars().action, root.vars().uninstallError], [true, "removed", false, "", ""]);
                    t.check("and never synced", Proc.calls.slice(root.mark).map(c => c.id), [Logic.ACTION_IDS.uninstall, Logic.UNLINK_ID]);
                    root.drop();
                }
            },
            {
                "run": () => {
                    // the same reload, then Set up again: the glass goes on
                    root.fresh(true, undefined, {
                        "uninstallState": "removing"
                    });
                    t.check("a stored removing runs nothing", Proc.calls.map(c => c.id), []);
                    t.check("set up again", root.d.reinstall(), true);
                    t.check("the interrupted uninstall is forgotten", [root.pdata().uninstallState, root.vars().uninstallState, root.vars().uninstallError, Proc.pendingIds()], ["", "", "", [Logic.SEED_ID]]);
                    Proc.flush();
                    Proc.flush();
                    Proc.flush();
                    root.drop();
                }
            },
            {
                "run": () => {
                    // Set up again after a full remove: settings.json is gone,
                    // so `appglass get` answers the defaults; the stored
                    // choices stay (an app switched off stays off, no confirm
                    // skipped) and only the keys never stored are seeded
                    root.fresh(false, undefined, {
                        "uninstallState": "removed",
                        "apps": {
                            "gtk3": {
                                "enabled": false
                            }
                        },
                        "inactiveDurationMs": 250
                    });
                    t.check("set up again", root.d.reinstall(), true);
                    Proc.flush();       // get
                    const pd = root.pdata();
                    t.check("the stored choices survive", [pd.apps, pd.inactiveDurationMs, pd.seeded], [{
                            "gtk3": {
                                "enabled": false
                            }
                        }, 250, true]);
                    t.check("a key never stored is seeded", pd.inactiveEasing, Logic.pluginDataFromSettings(root.defaults).inactiveEasing);
                    Proc.flush();       // sync
                    const s = root.lastSyncSettings();
                    t.check("the sync carries them", [s.apps.gtk3.enabled, s.inactive.durationMs], [false, 250]);
                    Proc.flush();
                    root.drop();
                }
            },
            {
                "run": () => {
                    // a remove run again after the reload that fails: back to syncing
                    root.fresh(true, undefined, {
                        "uninstallState": "removing"
                    });
                    Proc.setResult(Logic.ACTION_IDS.uninstall, "appglass: remove: boom\n", 1);
                    t.check("uninstall again", root.d.runAction("uninstall"), true);
                    Proc.flush();
                    t.check("it stopped: back to syncing", [root.d.uninstalled, root.pdata().uninstallState, Proc.pendingIds()], [false, "", [Logic.SYNC_ID]]);
                    Proc.flush();
                    Proc.flush();
                    root.drop();
                }
            },
            {
                "run": () => {
                    root.fresh(true);
                    Proc.flush();
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
