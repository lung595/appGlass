import QtQuick
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Services
import qs.Widgets
import qs.Modules.Plugins
import "logic.js" as Logic

// Turns the plugin settings into appglass settings.json: on every change of
// the plugin data it writes the full settings to $XDG_RUNTIME_DIR and runs
// `appglass sync --settings-file` (debounced, one at a time), then reads
// `appglass status --json` for the settings page. The theme and the DMS
// window rule are not its business: the appglass-sync path unit re-applies
// on those (appglass hook install); a change of the DMS window rules only
// refreshes the status (the level shown).
//
// First start: the plugin data is taken from `appglass get`, so what the
// CLI had set stays. Disabling, re-enabling or reloading the plugin changes
// no file and no unit: only `appglass remove` (an explicit uninstall) takes
// the glass files and the hook out, and it only runs from Settings >
// Advanced > Uninstall (confirmed there) or a terminal.
//
// Settings > Advanced runs its actions here (runAction: learn, adopt,
// uninstall; copyReport), one at a time, so the settings page and the bar
// pill run no command themselves.
// `dms ipc call appGlass sync | status | toggle | pause | resume | app <key> on|off`
//
// AppGlassDaemon.qml creates it (see there why) with the plugin's folder.
PluginComponent {
    id: root

    property string pluginDir: ""
    // the plugin's folder as the shell's URL says it (without the
    // /proc/self/root a reload puts before this file's)
    property string shellDir: ""
    readonly property string home: Quickshell.env("HOME") || ""
    readonly property string configHome: Quickshell.env("XDG_CONFIG_HOME") || (home + "/.config")
    readonly property string settingsFile: Logic.settingsFilePath(Quickshell.env("XDG_RUNTIME_DIR"))
    readonly property string bin: Logic.appglassBin(root.pluginDir, root.pluginData.appglassBin)
    readonly property var service: root.pluginService || PluginService

    // ready: the plugin data was seeded; busy: a sync runs; again: a change
    // came while it ran (one more sync when it ends)
    property bool ready: false
    property bool seeding: false
    property bool busy: false
    property bool again: false
    // the sync asked is the start sync (appglass sync --no-switch: the
    // stored data counts as no switch); any other request clears it
    property bool startSync: false
    property bool settingsWriteFailed: false
    property string lastSettingsText: ""
    // Re-apply asked: a toast when that sync ends
    property bool announce: false
    // Settings > Advanced > Uninstall asked: from then on no sync starts (a
    // sync beside `appglass remove` would write the glass back after it).
    // holding: it waits for the sync that runs to end.
    property bool sweeping: false
    property bool holding: false
    // `appglass remove` worked: nothing is synced any more (DMS drops the
    // plugin once its link is gone). Kept in the plugin data
    // (uninstallState; "unlinking" while `appglass plugin remove` runs,
    // read as linkStays on a load): a reload or a shell restart while the link stays
    // seeds and syncs nothing either; only reinstall() (the page's "Set up
    // again") brings the glass back. "removing" while the remove runs: a
    // reload then finds it cut short (interrupted: it syncs nothing, and
    // only Uninstall or Set up again goes on). "removed" means the link
    // is gone: DMS loads this body again only from a new link (`appglass
    // plugin install`), so that load sets up again, as the button does
    property bool uninstalled: false
    property bool interrupted: false

    PluginGlobalVar {
        id: statusVar
        varName: "status"
        defaultValue: null
    }
    PluginGlobalVar {
        id: lastErrorVar
        varName: "lastError"
        defaultValue: ""
    }
    PluginGlobalVar {
        id: syncingVar
        varName: "syncing"
        defaultValue: false
    }
    PluginGlobalVar {
        id: lastSyncVar
        varName: "lastSync"
        defaultValue: ""
    }
    // "" | "removed" | "linkStays": `appglass remove` worked (and the plugin
    // link could not be taken out: the page says how to finish)
    PluginGlobalVar {
        id: uninstallVar
        varName: "uninstallState"
        defaultValue: ""
    }
    // Why the last `appglass remove` failed ("" when it did not): kept
    // after the sync that follows (that one clears lastError)
    PluginGlobalVar {
        id: uninstallErrorVar
        varName: "uninstallError"
        defaultValue: ""
    }
    // The Settings > Advanced action running ("" for none)
    PluginGlobalVar {
        id: actionVar
        varName: "action"
        defaultValue: ""
    }

    function publish(variable, value) {
        if (JSON.stringify(variable.value) !== JSON.stringify(value))
            variable.set(value);
    }

    function fail(text) {
        root.publish(lastErrorVar, text);
        ToastService.showError("appGlass: " + text);
    }

    // --- sync ------------------------------------------------------------------

    // Asks for a sync: changes close together collapse into one (debounce),
    // and one that comes while a sync runs gets one more after it
    function requestSync(reason, waitMs) {
        if (root.uninstalled)
            return false;
        if (root.sweeping) {
            // kept: synced if the remove fails
            root.again = true;
            return false;
        }
        if (!root.ready) {
            if (!root.seeding && root.bin)
                root.seed();
            return false;
        }
        if (!root.bin)
            return false;
        if (reason === "reapply")
            root.announce = true;
        // only a start sync with nothing else asked since is no switch
        root.startSync = reason === "start" && (root.startSync || (!root.busy && !debounce.running));
        // a change owes a sync with its switches: saved now, so a shell
        // restart before the debounce ends still applies it (the next start
        // sync is then no --no-switch)
        if (reason !== "start" && root.pending() !== true)
            root.save("syncPending", true);
        root.publish(syncingVar, true);
        if (root.busy) {
            root.again = true;
            return true;
        }
        const wait = typeof waitMs === "number" ? waitMs : Logic.SYNC_DEBOUNCE_MS;
        if (wait <= 0) {
            debounce.stop();
            root.launchSync();
        } else {
            debounce.interval = wait;
            debounce.restart();
        }
        return true;
    }

    property bool runNoSwitch: false

    function pending() {
        return root.service.loadPluginData(Logic.PLUGIN_ID, "syncPending", false);
    }

    function launchSync() {
        if (root.uninstalled || root.sweeping) {
            root.publish(syncingVar, false);
            return;
        }
        if (!root.settingsFile) {
            root.publish(syncingVar, false);
            root.fail("no XDG_RUNTIME_DIR: the settings cannot be handed to appglass");
            return;
        }
        // Written at once; emptied first, since a FileView skips a text
        // equal to the last one it wrote
        const text = Logic.settingsText(root.pluginData);
        root.lastSettingsText = text;
        root.settingsWriteFailed = false;
        settingsFileView.setText("");
        settingsFileView.setText(text);
        if (root.settingsWriteFailed) {
            root.publish(syncingVar, false);
            root.fail("cannot write " + root.settingsFile);
            return;
        }
        root.busy = true;
        const noSwitch = root.startSync && root.pending() !== true;
        root.startSync = false;
        root.runNoSwitch = noSwitch;
        Proc.runCommand(Logic.SYNC_ID, Logic.syncArgv(root.bin, root.settingsFile, noSwitch), (out, code) => root.syncDone(out, code), 0, Logic.SYNC_TIMEOUT_MS, root);
    }

    function syncDone(output, exitCode) {
        root.busy = false;
        if (root.uninstalled || root.sweeping) {
            root.announce = false;
            root.publish(syncingVar, false);
            if (root.holding)
                root.launchRemove();
            return;
        }
        if (exitCode === 0) {
            // what was owed is applied (unless more came meanwhile)
            if (!root.runNoSwitch && !root.again && root.pending() === true)
                root.save("syncPending", false);
            root.publish(lastErrorVar, "");
            root.publish(lastSyncVar, new Date().toISOString());
            if (root.announce)
                ToastService.showInfo("appGlass: re-applied");
        } else {
            root.fail(Logic.errorText(output, exitCode));
        }
        root.announce = false;
        if (root.again) {
            root.again = false;
            root.launchSync();
            return;
        }
        root.publish(syncingVar, false);
        root.refreshStatus();
    }

    // --- status ----------------------------------------------------------------

    // One status run at a time: DMS's Proc keeps one callback per id and
    // drops it after the first run exits, so a second run started while one
    // runs would lose its (newer) answer. Asked meanwhile: one more after.
    property bool statusBusy: false
    property bool statusAgain: false

    function refreshStatus() {
        if (!root.bin)
            return false;
        if (root.statusBusy) {
            root.statusAgain = true;
            return true;
        }
        root.statusBusy = true;
        Proc.runCommand(Logic.STATUS_ID, Logic.statusArgv(root.bin), (out, code) => {
            root.statusBusy = false;
            if (root.statusAgain) {
                root.statusAgain = false;
                root.refreshStatus();
            }
            const doc = code === 0 ? Logic.parseStatus(out) : null;
            if (doc)
                root.publish(statusVar, doc);
            else if (code !== 0)
                root.publish(lastErrorVar, "status: " + Logic.errorText(out, code));
            else
                root.publish(lastErrorVar, "status: unreadable answer");
        }, 100, Logic.STATUS_TIMEOUT_MS, root);
        return true;
    }

    // --- the plugin data -------------------------------------------------------

    function save(key, value) {
        root.service.savePluginData(Logic.PLUGIN_ID, key, value);
    }

    // First start: take over what appglass has (the CLI may have set it).
    // When `appglass get` fails nothing is synced (that would write the
    // defaults over the CLI's settings); the next request tries again.
    // keep (Set up again): a full remove took settings.json out, so `get`
    // answers the defaults; the stored plugin data stays the source and
    // only the keys never stored are seeded
    function seed(keep) {
        root.seeding = true;
        Proc.runCommand(Logic.SEED_ID, Logic.getArgv(root.bin), (out, code) => {
            root.seeding = false;
            const s = code === 0 ? Logic.parseJson(out) : undefined;
            if (!s || typeof s !== "object" || Array.isArray(s)) {
                root.fail("cannot read the appglass settings: " + Logic.errorText(code === 0 ? "" : out, code));
                return;
            }
            const data = Logic.pluginDataFromSettings(s);
            for (const key of Object.keys(data)) {
                if (!keep || root.service.loadPluginData(Logic.PLUGIN_ID, key, undefined) === undefined)
                    root.save(key, data[key]);
            }
            root.save("seeded", true);
            root.ready = true;
            root.requestSync("start", 0);
        }, 0, Logic.STATUS_TIMEOUT_MS, root);
    }

    function setGlass(on) {
        root.save("glassEnabled", !!on);
        return !!on;
    }

    function setApp(key, on) {
        root.save("apps", Logic.withApp(root.pluginData.apps, key, on));
    }

    // --- Settings > Advanced ----------------------------------------------------

    // learn | adopt | uninstall: false when another one runs, the name is
    // unknown, or appglass was uninstalled. learn and adopt end with a sync
    // (what they found gets its glass), uninstall with none.
    //
    // Uninstall: no sync may run beside or after `appglass remove` (the
    // core lock only queues it: it would write the glass back). A sync
    // waiting for its debounce or queued is dropped, one running is waited
    // for, and none starts again (sweeping); a change meanwhile is kept
    // (again) for when the remove fails. Then `appglass remove`; once it
    // worked, the plugin link (`appglass plugin remove`).
    function runAction(name) {
        const argv = root.bin ? Logic.actionArgv(name, root.bin) : null;
        const retry = name === "uninstall" && root.interrupted;
        if (!argv || (root.uninstalled && !retry) || root.sweeping || actionVar.value)
            return false;
        root.publish(actionVar, name);
        if (name === "uninstall") {
            if (retry) {
                // the uninstall a reload cut short, asked again
                root.uninstalled = false;
                root.interrupted = false;
                root.publish(uninstallVar, "");
            }
            // a new try: the last one's stop is old news
            root.publish(uninstallErrorVar, "");
            root.sweeping = true;
            // kept at once: a reload or a shell restart before removeDone
            // must not seed and sync the glass back (the callback of a
            // remove whose owner is gone never comes)
            root.save("uninstallState", "removing");
            // a sync waiting for its debounce: kept for a failed remove
            if (debounce.running)
                root.again = true;
            debounce.stop();
            root.announce = false;
            if (root.busy) {
                root.holding = true;
            } else {
                root.publish(syncingVar, false);
                root.launchRemove();
            }
            return true;
        }
        // adopt moves files and records them: a kill half way would cut it
        const timeout = name === "adopt" ? Proc.noTimeout : Logic.ACTION_TIMEOUT_MS;
        Proc.runCommand(Logic.ACTION_IDS[name], argv, (out, code) => root.actionDone(name, out, code), 0, timeout, root);
        return true;
    }

    function launchRemove() {
        root.holding = false;
        // never killed half way: remove restores file after file
        Proc.runCommand(Logic.ACTION_IDS.uninstall, Logic.uninstallArgv(root.bin), (out, code) => root.removeDone(out, code), 0, Proc.noTimeout, root);
    }

    function removeDone(output, exitCode) {
        if (exitCode !== 0) {
            // remove stopped (what it restored before stopping is back to
            // the original): the glass and the syncs go on, from a sync now
            // that sets the glass up again (what changed meanwhile, `again`,
            // goes with it)
            root.sweeping = false;
            root.again = false;
            root.save("uninstallState", "");
            root.publish(actionVar, "");
            root.fail(Logic.errorText(output, exitCode));
            root.publish(uninstallErrorVar, "Uninstall stopped: " + Logic.errorText(output, exitCode) + ". Glass is set up again from the current settings");
            if (!root.requestSync("uninstall", 0))
                root.refreshStatus();
            return;
        }
        // the files are back: whatever the link step does, no sync again
        root.uninstalled = true;
        root.ready = false;
        // a later install starts again from `appglass get`
        root.save("seeded", false);
        // "unlinking" until the unlink answers: a restart that kills it
        // comes back with the link in place (linkStays, its hint shown)
        root.save("uninstallState", "unlinking");
        root.publish(lastErrorVar, "");
        root.publish(uninstallErrorVar, "");
        root.publish(uninstallVar, "removed");
        Proc.runCommand(Logic.UNLINK_ID, Logic.unlinkArgv(root.bin), (out, code) => {
            root.publish(actionVar, "");
            if (code === 0) {
                root.save("uninstallState", "removed");
                ToastService.showInfo("appGlass: uninstalled, every file restored");
            } else {
                root.save("uninstallState", "linkStays");
                root.publish(uninstallVar, "linkStays");
                root.fail("every file restored, but the plugin link stays: " + Logic.errorText(out, code) + ". Run 'appglass plugin remove' in a terminal to finish.");
            }
        }, 0, Logic.ACTION_TIMEOUT_MS, root);
    }

    // Set up again after an uninstall (the page's button, the user's own
    // click): the files come back from a sync of the stored settings (an
    // app switched off stays off), `appglass get` filling only what was
    // never stored
    function reinstall() {
        if (!root.uninstalled || root.sweeping || actionVar.value || !root.bin)
            return false;
        root.uninstalled = false;
        root.interrupted = false;
        root.save("uninstallState", "");
        root.publish(uninstallVar, "");
        root.publish(lastErrorVar, "");
        root.publish(uninstallErrorVar, "");
        root.seed(true);
        return true;
    }

    function actionDone(name, output, exitCode) {
        root.publish(actionVar, "");
        if (exitCode !== 0) {
            root.fail(Logic.errorText(output, exitCode));
            root.refreshStatus();
            return;
        }
        root.publish(lastErrorVar, "");
        ToastService.showInfo("appGlass: " + (Logic.lastLine(output) || name + " done"));
        if (!root.requestSync(name, 0))
            root.refreshStatus();
    }

    // The IPC answer to a change while uninstalling, or after ("" when
    // none): such a change is not saved
    function ipcRefusal() {
        if (root.interrupted)
            return "uninstalling";
        return root.uninstalled ? "uninstalled" : (root.sweeping ? "uninstalling" : "");
    }

    // The last status as text, on the clipboard (DMS's own copy command)
    function copyReport() {
        Quickshell.execDetached([Proc.dmsBin, "cl", "copy", Logic.reportText(statusVar.value, root.pluginData.apps, root.pluginData.glassEnabled !== false)]);
        ToastService.showInfo("appGlass: report copied");
        return true;
    }

    onPluginDataChanged: {
        if (!root.ready)
            return;
        // a save of the same settings (a slider moved back) runs nothing
        if (Logic.settingsText(root.pluginData) === root.lastSettingsText && !root.busy)
            return;
        root.requestSync("settings");
    }

    Timer {
        id: debounce
        interval: Logic.SYNC_DEBOUNCE_MS
        repeat: false
        onTriggered: root.launchSync()
    }

    // The settings of the next sync: written only, never read or watched
    FileView {
        id: settingsFileView
        path: root.settingsFile
        preload: false
        blockWrites: true
        printErrors: false
        onSaveFailed: root.settingsWriteFailed = true
    }

    // The DMS window rule opacity is the glass level: show the new one
    FileView {
        id: windowRules
        path: root.configHome + "/niri/dms/windowrules.kdl"
        watchChanges: true
        printErrors: false
        onFileChanged: {
            reload();
            if (!root.busy)
                root.refreshStatus();
        }
    }

    IpcHandler {
        target: "appGlass"

        function sync(): string {
            if (root.ipcRefusal())
                return root.ipcRefusal();
            return root.requestSync("reapply", 0) ? "OK" : "not ready";
        }
        function status(): string {
            root.refreshStatus();
            const s = statusVar.value;
            return s ? JSON.stringify(s) : JSON.stringify({
                "error": "no status yet"
            });
        }
        function toggle(): string {
            if (root.ipcRefusal())
                return root.ipcRefusal();
            const on = root.pluginData.glassEnabled !== false;
            return root.setGlass(!on) ? "glass on" : "glass off";
        }
        function pause(): string {
            if (root.ipcRefusal())
                return root.ipcRefusal();
            root.setGlass(false);
            return "glass off";
        }
        function resume(): string {
            if (root.ipcRefusal())
                return root.ipcRefusal();
            root.setGlass(true);
            return "glass on";
        }
        function app(key: string, state: string): string {
            const on = Logic.parseOnOff(state);
            if (on === null)
                return "usage: app <key> on|off";
            if (root.ipcRefusal())
                return root.ipcRefusal();
            root.setApp(key, on);
            return key + (on ? " on" : " off");
        }
    }

    Component.onCompleted: {
        root.publish(syncingVar, false);
        root.publish(actionVar, "");
        root.publish(uninstallErrorVar, "");
        const dir = PluginService.getPluginPath(root.pluginId) || root.shellDir;
        root.pluginDir = String(dir).replace(/\/+$/, "");
        let gone = root.service.loadPluginData(Logic.PLUGIN_ID, "uninstallState", "");
        if (gone === "unlinking") {
            // the files were back, the unlink was cut short: this load
            // means the link is still there
            gone = "linkStays";
            root.save("uninstallState", gone);
        }
        if (gone === "removed") {
            // the uninstall took the link out, and a link loaded this body:
            // installed again. Set up again from the stored settings
            // (`appglass get` fills only a key never stored)
            root.save("uninstallState", "");
            root.publish(uninstallVar, "");
            root.seed(true);
            return;
        }
        if (gone === "linkStays") {
            // uninstalled before this load, the link stayed: no seed, no sync
            root.uninstalled = true;
            root.publish(uninstallVar, gone);
            return;
        }
        root.publish(uninstallVar, "");
        const seeded = root.service.loadPluginData(Logic.PLUGIN_ID, "seeded", false) === true;
        if (gone === "removing") {
            // an uninstall a reload cut short (its callback never came; the
            // remove itself may have ended meanwhile, it is not known): no
            // seed and no sync (they would write the glass back), and no
            // remove either (no plugin event runs one): the page offers
            // Uninstall again or Set up again
            root.ready = seeded;
            root.uninstalled = true;
            root.interrupted = true;
            root.publish(uninstallVar, "interrupted");
            root.publish(uninstallErrorVar, "Uninstall may not have finished (the shell reloaded while it ran). Uninstall again to finish it (it does no harm if it had finished), or Set up again to keep the glass");
            return;
        }
        if (seeded) {
            root.ready = true;
            root.requestSync("start", 0);
        } else {
            root.seed();
        }
    }

    Component.onDestruction: {
        // nothing else: a plugin disable then enable must not tear down the
        // adopted files and the hook (the enable's sync does not adopt)
        for (const id of [Logic.SYNC_ID, Logic.STATUS_ID, Logic.SEED_ID, Logic.UNLINK_ID])
            Proc.release(id);
        // an action not launched yet is dropped; one already running finishes
        for (const name of Object.keys(Logic.ACTION_IDS))
            Proc.release(Logic.ACTION_IDS[name]);
    }
}
