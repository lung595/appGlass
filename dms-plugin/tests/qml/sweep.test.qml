import QtQuick
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Services
import "components"
import "components/logic.js" as Logic
import "components/keeper.js" as Keeper

// components/UninstallSweep.qml: the deleted-folder uninstaller. Once
// plugin.json is gone at unload (a DMS uninstall deleted the clone), it
// starts the rescue copy of the CLI with `remove --if-gone <plugin.json>`,
// through keeper.js so the process outlives the plugin. The CLI waits its
// grace period and exits EXIT_KEPT when plugin.json is back (an update);
// else, once it exits 0, the plugin's plugin_settings.json entry is dropped.
// Plain destruction (disable, reload, shell quit) runs nothing.
Item {
    id: root

    Harness {
        id: t
    }

    readonly property string dir: "/tmp/fakehome/.config/DankMaterialShell/plugins/appGlass"
    readonly property string manifest: dir + "/plugin.json"
    readonly property string dataDir: "/tmp/fakehome/.local/share"
    readonly property string rescue: dataDir + "/appglass/cli/bin/appglass"
    property var sweep: null

    Component {
        id: sweepComponent
        UninstallSweep {
            pluginDir: root.dir
            dataHome: root.dataDir
        }
    }

    function fresh(armed) {
        ProcessLog.reset();
        ToastService.reset();
        SettingsData.reset();
        SettingsData.pluginSettings = {
            "appGlass": {
                "enabled": true,
                "seeded": true
            },
            "otherPlugin": {
                "enabled": true
            }
        };
        FileViewLog.reset();
        FileViewLog.put(root.manifest, "{\"id\": \"appGlass\"}\n");
        FileViewLog.put(root.rescue, "#!/usr/bin/env python3\n");
        root.sweep = sweepComponent.createObject(root, {
            "armed": armed !== false
        });
    }

    // The sweep's process outlives its creation context: raise the signal
    // itself, as the real one would
    function exitLive(code) {
        const live = ProcessLog.alive().filter(p => p.running);
        for (const p of live)
            p.exited(code, 0);
        return live.length;
    }

    function deleteFolder() {
        root.fresh();
        FileViewLog.remove(root.manifest);
        root.sweep.destroy();
    }

    Component.onCompleted: {
        t.steps([
            {
                "run": () => {
                    // 1. Disable / reload / quit: the folder stays, nothing runs
                    root.fresh();
                    t.check("paths", [root.sweep.manifest, root.sweep.rescue], [root.manifest, root.rescue]);
                    t.ok("nothing runs at load", ProcessLog.runs.length === 0);
                    root.sweep.destroy();
                }
            },
            {
                "run": () => {
                    t.check("plugin.json still there: no process", ProcessLog.runs.length, 0);
                    t.ok("the settings entry stays", SettingsData.pluginSettings.appGlass !== undefined);
                    t.check("no toast", ToastService.log.length, 0);
                    // 2. The folder was deleted: plugin.json gone at unload
                    root.deleteFolder();
                }
            },
            {
                "run": () => {
                    t.check("one process ran", ProcessLog.runs.length, 1);
                    t.check("argv: the rescue copy, remove --if-gone <plugin.json>", ProcessLog.runs[0].command, ["python3", "-I", "-B", root.rescue, "remove", "--if-gone", root.manifest]);
                    t.check("= Logic.sweepArgv", ProcessLog.runs[0].command, Logic.sweepArgv(root.rescue, root.manifest));
                    t.check("not detached", ProcessLog.runs[0].detached, false);
                    t.check("the process outlives the plugin", ProcessLog.alive().filter(p => p.running).length, 1);
                    t.check("keeper.js holds it", Keeper.count(), 1);
                    t.ok("the entry stays while it runs", SettingsData.pluginSettings.appGlass !== undefined);
                    t.check("no toast yet", ToastService.log.length, 0);
                    root.exitLive(0);
                }
            },
            {
                "wait": 50,
                "run": () => {
                    t.check("and goes once it exits", [ProcessLog.alive().length, Keeper.count()], [0, 0]);
                    t.check("exit 0: the entry is dropped, the others kept", SettingsData.pluginSettings, {
                        "otherPlugin": {
                            "enabled": true
                        }
                    });
                    t.check("plugin_settings.json written", SettingsData.pluginSettingsWrites.length, 1);
                    t.check("one info toast", ToastService.log.map(x => [x.level, x.message]), [["info", "appGlass removed: every file restored"]]);
                    // 2b. An update: plugin.json was back after the grace
                    root.deleteFolder();
                }
            },
            {
                "run": () => {
                    t.check("EXIT_KEPT", root.exitLive(Logic.EXIT_KEPT), 1);
                }
            },
            {
                "wait": 50,
                "run": () => {
                    t.ok("kept: the entry stays", SettingsData.pluginSettings.appGlass !== undefined);
                    t.check("kept: nothing written, no toast", [SettingsData.pluginSettingsWrites.length, ToastService.log.length], [0, 0]);
                    t.check("the keeper lets go", Keeper.count(), 0);
                    // 2c. The remove failed
                    root.deleteFolder();
                }
            },
            {
                "run": () => {
                    t.check("one more sweep", root.exitLive(1), 1);
                }
            },
            {
                "wait": 50,
                "run": () => {
                    t.ok("failed: the entry stays", SettingsData.pluginSettings.appGlass !== undefined);
                    t.check("failed: nothing written", SettingsData.pluginSettingsWrites.length, 0);
                    t.check("one error toast naming the way out", ToastService.log.map(x => [x.level, x.message, x.details]), [["error", "appGlass removed, but restoring the files failed", "exit code 1: run " + root.rescue + " remove in a terminal"]]);
                    // 3. No rescue copy (the page's Uninstall took it out, or
                    // no hook was ever installed): nothing to run
                    root.fresh();
                    FileViewLog.remove(root.manifest);
                    FileViewLog.remove(root.rescue);
                    root.sweep.destroy();
                }
            },
            {
                "run": () => {
                    t.check("no rescue copy: nothing runs", ProcessLog.runs.length, 0);
                    // 4. Disarmed (the daemon is uninstalled or uninstalling)
                    root.fresh(false);
                    FileViewLog.remove(root.manifest);
                    root.sweep.destroy();
                }
            },
            {
                "run": () => {
                    t.check("disarmed: nothing runs", ProcessLog.runs.length, 0);
                    t.check("no toast", ToastService.log.length, 0);
                    t.ok("the entry stays", SettingsData.pluginSettings.appGlass !== undefined);
                }
            }
        ]);
    }
}
