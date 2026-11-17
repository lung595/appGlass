import QtQuick
import qs.Common
import qs.Services
import qs.Modules.Plugins

// The plugin daemon: components/DaemonBody.qml does the work (the debounced
// `appglass sync`, the status, the Advanced actions, the IPC). This shell
// only creates it, so that `dms ipc call plugins reload appGlass` after an
// update runs the new code: DMS loads this file again as
// AppGlassDaemon.qml?revision=N, but QML keeps whatever a file imports by a
// relative URL (components/logic.js...) cached under its old URL. The body
// is loaded from a URL that is new for each revision (freshUrl), and so is
// everything it imports. This file imports nothing of the plugin's own.
PluginComponent {
    id: root

    property var body: null
    readonly property bool uninstalled: root.body ? root.body.uninstalled === true : false

    // What the settings page and the tests call on the daemon
    function requestSync(reason, waitMs) {
        return root.body ? root.body.requestSync(reason, waitMs) : false;
    }
    function runAction(name) {
        return root.body ? root.body.runAction(name) : false;
    }
    function copyReport() {
        return root.body ? root.body.copyReport() : false;
    }

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

    // rel resolved against this file, under /proc/self/root and
    // /proc/thread-self/root (links to /) in a sequence that spells the
    // revision: the same file at a URL this process has not loaded yet.
    // Without a revision (the first load), rel as it is.
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

    Component.onCompleted: {
        const comp = Qt.createComponent(root.freshUrl("components/DaemonBody.qml"), Component.PreferSynchronous);
        if (comp.status !== Component.Ready) {
            console.warn("appGlass: the daemon did not load: " + comp.errorString());
            return;
        }
        root.body = comp.createObject(root, {
            "pluginId": root.pluginId,
            "pluginService": root.pluginService,
            "shellDir": Paths.strip(Qt.resolvedUrl("."))
        });
    }
}
