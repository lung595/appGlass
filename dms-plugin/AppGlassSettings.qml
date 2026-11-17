import QtQuick
import qs.Common
import qs.Services
import qs.Modules.Plugins

// The settings page: components/SettingsBody.qml is the page (search, rail,
// categories). This shell only creates it, so that `dms ipc call plugins
// reload appGlass` after an update shows the new page: DMS loads this file
// again as AppGlassSettings.qml?revision=N, but QML keeps whatever a file
// imports by a relative URL (components/logic.js, components/settings/...)
// cached under its old URL, and a new page calling a new logic.js function
// failed. The body is loaded from a URL that is new for each revision
// (freshUrl, as in AppGlassDaemon.qml), and so is everything it imports.
// This file imports nothing of the plugin's own.
PluginSettings {
    id: root
    pluginId: "appGlass"

    property var body: null

    // DMS's reload counter for the plugin, the N it loaded this file with.
    // Read from PluginService: this file's own URL is no help, as quickshell
    // keeps the QML disk cache and a file it loads again unchanged comes
    // back with the URL it was first compiled under (?revision=<the first>)
    function revision() {
        const revs = PluginService._componentRevisions;
        if (revs && revs["appGlass"] !== undefined)
            return Number(revs["appGlass"]);
        const m = /[?&]revision=(\d+)/.exec(String(Qt.resolvedUrl("#r")));
        return m ? Number(m[1]) : 0;
    }

    function freshUrl(rel) {
        const url = String(Qt.resolvedUrl(rel));
        let n = root.revision();
        if (!(n > 0) || url.indexOf("file:///") !== 0)
            return url;
        let prefix = "";
        while (n > 0) {
            prefix = ((n - 1) % 2 ? "/proc/thread-self/root" : "/proc/self/root") + prefix;
            n = Math.floor((n - 1) / 2);
        }
        return "file://" + prefix + url.slice(7);
    }

    Item {
        id: holder
        width: parent ? parent.width : 0
        height: root.body ? root.body.implicitHeight : 0

        Component.onCompleted: {
            const comp = Qt.createComponent(root.freshUrl("components/SettingsBody.qml"), Component.PreferSynchronous);
            if (comp.status !== Component.Ready) {
                console.warn("appGlass: the settings page did not load: " + comp.errorString());
                return;
            }
            root.body = comp.createObject(holder, {
                "pluginId": root.pluginId,
                "pluginService": Qt.binding(() => root.pluginService),
                "width": Qt.binding(() => holder.width)
            });
        }
    }
}
