.pragma library
.import "logic.js" as Logic

// Starts a process that outlives the plugin: UninstallSweep.qml runs the
// uninstaller while the plugin is being destroyed, after its folder is gone.
// - The Process comes from a component this library compiles while the
//   folder still exists (prepare(), at load): at teardown no file can be read.
// - It is created here, outside the plugin's QML context, so it keeps working
//   once that context is torn down, and without a parent, so nothing of the
//   plugin takes it along.
// - A parentless object belongs to the JavaScript engine, whose garbage
//   collector would destroy it (killing its child) once nothing refers to it:
//   `held` refers to it (a library lives as long as the engine) until it exits.
// - What happens once it exits runs here too: the plugin's QML context (its
//   handlers, its ids) is gone by then. The caller hands over the shell's
//   singletons it needs (`after`).

var held = [];
var runner = null;

// Compiles SweepProcess.qml; true when it is ready
function prepare() {
    if (!runner)
        runner = Qt.createComponent("SweepProcess.qml");
    return runner !== null && runner.status === 1; // Component.Ready
}

// Starts `command`; once it exits, `onExit(exitCode)` runs (when given) and
// the process is dropped. The process object, or null when it could not be
// made.
function spawn(command, onExit) {
    if (!prepare())
        return null;
    var proc = runner.createObject(null, {
        "command": command
    });
    if (!proc)
        return null;
    held.push(proc);
    proc.exited.connect(function (exitCode) {
        var i = held.indexOf(proc);
        if (i >= 0)
            held.splice(i, 1);
        proc.destroy();
        if (typeof onExit === "function")
            onExit(exitCode);
    });
    proc.running = true;
    return proc;
}

// What the sweep does once its uninstaller exited. Logic.EXIT_KEPT:
// plugin.json came back during the grace period (an update), nothing
// changes. Otherwise the plugin is gone and a toast tells how the remove
// went. Its plugin_settings.json entry is dropped only once the remove
// worked (a later install then starts fresh, from `appglass get`); after a
// failure the glass is still there and the entry stays for a reinstall.
//   after: {settings: SettingsData, toasts: ToastService, pluginId, rescue}
// DMS keeps a removed plugin's entry and writes its whole map back on every
// save, so the entry goes through SettingsData (an edit of the file itself
// would be overwritten).
function afterSweep(exitCode, after) {
    if (exitCode === Logic.EXIT_KEPT || !after)
        return "kept";
    var settings = exitCode === 0 ? after.settings : null;
    var next = settings ? Logic.withoutPlugin(settings.pluginSettings, after.pluginId) : null;
    if (next !== null) {
        settings.pluginSettings = next;
        // DMS's writer (looked up by name: older shells may lack it)
        var save = settings["savePluginSettings"];
        if (typeof save === "function")
            save.call(settings);
    }
    if (after.toasts) {
        if (exitCode === 0)
            after.toasts.showInfo("appGlass removed: every file restored");
        else
            after.toasts.showError("appGlass removed, but restoring the files failed", "exit code " + exitCode + ": run " + after.rescue + " remove in a terminal");
    }
    return exitCode === 0 ? "removed" : "failed";
}

// The sweep: `command`, then afterSweep()
function sweep(command, after) {
    return spawn(command, function (exitCode) {
        afterSweep(exitCode, after);
    });
}

function count() {
    return held.length;
}
