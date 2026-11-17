import QtQuick
import qs.Common
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

    function freshUrl(rel) {
        const m = /[?&]revision=(\d+)/.exec(String(Qt.resolvedUrl("#r")));
        const url = String(Qt.resolvedUrl(rel));
        if (!m || url.indexOf("file:///") !== 0)
            return url;
        let n = Number(m[1]);
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
