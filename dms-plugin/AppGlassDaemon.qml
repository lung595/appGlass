import QtQuick
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Services
import qs.Widgets
import qs.Modules.Plugins
import "components/logic.js" as Logic

// Turns the plugin settings into appglass settings.json: on every change of
// the plugin data it writes the full settings to $XDG_RUNTIME_DIR and runs
// `appglass sync --settings-file` (debounced, one at a time), then reads
// `appglass status --json` for the settings page. The theme and the DMS
// window rule are not its business: the appglass-sync path unit re-applies
// on those (appglass hook install); a change of the DMS window rules only
// refreshes the status (the level shown).
//
// First start: the plugin data is taken from `appglass get`, so what the
// CLI had set stays. Disabling the plugin runs `appglass remove`.
// `dms ipc call appGlass sync | status | toggle | app <key> on|off`
PluginComponent {
    id: root

    property string pluginDir: ""
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
    property bool settingsWriteFailed: false
    property string lastSettingsText: ""
    // Re-apply asked: a toast when that sync ends
    property bool announce: false

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
        if (!root.ready) {
            if (!root.seeding && root.bin)
                root.seed();
            return false;
        }
        if (!root.bin)
            return false;
        if (reason === "reapply")
            root.announce = true;
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

    function launchSync() {
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
        Proc.runCommand(Logic.SYNC_ID, Logic.syncArgv(root.bin, root.settingsFile), (out, code) => root.syncDone(out, code), 0, Logic.SYNC_TIMEOUT_MS, root);
    }

    function syncDone(output, exitCode) {
        root.busy = false;
        if (exitCode === 0) {
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

    function refreshStatus() {
        if (!root.bin)
            return false;
        Proc.runCommand(Logic.STATUS_ID, Logic.statusArgv(root.bin), (out, code) => {
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
    function seed() {
        root.seeding = true;
        Proc.runCommand(Logic.SEED_ID, Logic.getArgv(root.bin), (out, code) => {
            root.seeding = false;
            const s = code === 0 ? Logic.parseJson(out) : undefined;
            if (!s || typeof s !== "object" || Array.isArray(s)) {
                root.fail("cannot read the appglass settings: " + Logic.errorText(code === 0 ? "" : out, code));
                return;
            }
            const data = Logic.pluginDataFromSettings(s);
            for (const key of Object.keys(data))
                root.save(key, data[key]);
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
            const on = root.pluginData.glassEnabled !== false;
            return root.setGlass(!on) ? "glass on" : "glass off";
        }
        function app(key: string, state: string): string {
            const on = Logic.parseOnOff(state);
            if (on === null)
                return "usage: app <key> on|off";
            root.setApp(key, on);
            return key + (on ? " on" : " off");
        }
    }

    Component.onCompleted: {
        root.publish(syncingVar, false);
        const dir = PluginService.getPluginPath(root.pluginId) || Paths.strip(Qt.resolvedUrl("."));
        root.pluginDir = String(dir).replace(/\/+$/, "");
        if (root.service.loadPluginData(Logic.PLUGIN_ID, "seeded", false) === true) {
            root.ready = true;
            root.requestSync("start", 0);
        } else {
            root.seed();
        }
    }

    Component.onDestruction: {
        for (const id of [Logic.SYNC_ID, Logic.STATUS_ID, Logic.SEED_ID])
            Proc.release(id);
        // "enabled" turns false only when the user disables the plugin, not
        // when the shell quits or reloads it
        const enabled = SettingsData.getPluginSetting(Logic.PLUGIN_ID, "enabled", true);
        if (enabled !== false || !root.bin)
            return;
        Quickshell.execDetached(Logic.removeArgv(root.bin));
        ToastService.showInfo("appGlass disabled: taking the glass files out");
    }
}
