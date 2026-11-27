import QtQuick
import Quickshell.Io
import qs.Common
import qs.Services
import "logic.js" as Logic
import "keeper.js" as Keeper

// A DMS uninstall leaves nothing behind. A registry install is a clone of
// the whole repository with the plugins folder's appGlass linked to its
// dms-plugin: DMS's uninstall takes the link out and deletes the clone,
// bin/appglass with it, then unloads the plugin. When the daemon (and this
// sweep with it) is destroyed, the sweep checks whether its own plugin.json
// is gone; disabling, reloading or quitting the shell keep it, so nothing
// happens then (a disable must not tear the glass down).
// It runs the rescue copy of the CLI `appglass hook install` keeps in
// $XDG_DATA_HOME/appglass/cli: `python3 -I -B <copy>/bin/appglass remove
// --if-gone <plugin.json>`. A missing plugin.json is not trusted at once:
// an update may re-clone the repository, so the CLI first waits a grace
// period ($APPGLASS_SWEEP_GRACE, 4 s) and does nothing (EXIT_KEPT) if
// plugin.json is back; else it takes every file out, the copy last.
// components/keeper.js starts that process so that it outlives the plugin
// and, once it exits, drops the plugin_settings.json entry (only when the
// remove worked) and shows the toast.
// armed: false while the page's own Uninstall runs or once it ran (it took
// the files and the copy out itself, then the link: plugin.json is gone
// then too).
// At rest this costs nothing: no timer, no process.
Item {
    id: sweep

    property string pluginDir: ""
    property string dataHome: ""
    property bool armed: true
    readonly property string manifest: Logic.manifestPath(sweep.pluginDir)
    readonly property string rescue: Logic.rescueBin(sweep.dataHome)

    visible: false
    width: 0
    height: 0

    FileView {
        id: probe
        blockLoading: true
        printErrors: false
    }

    // An empty or unreadable file counts as missing
    function present(path) {
        probe.path = path;
        probe.reload();
        return probe.text() !== "";
    }

    Component.onCompleted: Keeper.prepare()

    Component.onDestruction: {
        if (!sweep.armed || !sweep.manifest || !sweep.rescue || sweep.present(sweep.manifest) || !sweep.present(sweep.rescue))
            return;
        Keeper.sweep(Logic.sweepArgv(sweep.rescue, sweep.manifest), {
            "settings": SettingsData,
            "toasts": ToastService,
            "pluginId": Logic.PLUGIN_ID,
            "rescue": sweep.rescue
        });
    }
}
