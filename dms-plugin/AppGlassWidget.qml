import QtQuick
import qs.Common
import qs.Services
import qs.Widgets
import qs.DCommon.Widgets
import qs.Modules.Plugins

// The bar pill: the glass icon (crossed out while paused) and how many apps
// are on glass, from the daemon's shared status. A click opens the plugin's
// settings, a right click pauses or resumes the glass. It only saves
// glassEnabled; the daemon turns that into `appglass sync`. After an
// uninstall whose plugin link stayed (uninstallState), the pill says
// "uninstalled" ("unfinished" for one a reload cut short) and a right
// click does nothing (the daemon syncs nothing).
//
// It imports nothing of the plugin's own: after an update, `dms ipc call
// plugins reload appGlass` loads this file again (?revision=N) but would
// keep a relatively imported components/logic.js from before. The text
// comes from components/PillText.qml, loaded from a URL that is new for
// each revision (freshUrl, as in AppGlassDaemon.qml).
PluginComponent {
    id: root

    readonly property string id_: root.pluginId || "appGlass"
    readonly property var service: root.pluginService || PluginService
    readonly property bool glassOn: root.pluginData.glassEnabled !== false
    readonly property bool gone: uninstallVar.value === "removed" || uninstallVar.value === "linkStays" || uninstallVar.value === "external" || uninstallVar.value === "interrupted"
    readonly property bool lit: root.glassOn && !root.gone
    // made once, at this load's revision: a binding would read DMS's
    // revision map, which every other plugin's reload reassigns, and build
    // a new object each time (the old ones kept alive by their bindings)
    property var pillText: null
    Component.onCompleted: {
        const comp = Qt.createComponent(root.freshUrl("components/PillText.qml"), Component.PreferSynchronous);
        if (comp.status !== Component.Ready) {
            console.warn("appGlass: the pill text did not load: " + comp.errorString());
            return;
        }
        root.pillText = comp.createObject(root, {
            "status": Qt.binding(() => statusVar.value),
            "glassOn": Qt.binding(() => root.glassOn),
            "uninstalled": Qt.binding(() => root.gone),
            "unfinished": Qt.binding(() => uninstallVar.value === "interrupted")
        });
    }
    readonly property string countText: root.pillText ? root.pillText.text : ""

    // DMS's reload counter for the plugin, the N it loaded this file with.
    // Read from PluginService: this file's own URL is no help, as quickshell
    // keeps the QML disk cache and a file it loads again unchanged comes
    // back with the URL it was first compiled under (?revision=<the first>).
    // No entry in the counter is revision 0, never the URL's; the URL only
    // for a DMS without the counter
    function revision() {
        const revs = PluginService._componentRevisions;
        if (revs !== undefined && revs !== null)
            return revs["appGlass"] !== undefined ? Number(revs["appGlass"]) || 0 : 0;
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

    PluginGlobalVar {
        id: statusVar
        varName: "status"
        defaultValue: null
    }

    PluginGlobalVar {
        id: uninstallVar
        varName: "uninstallState"
        defaultValue: ""
    }

    function togglePause() {
        if (root.gone)
            return;
        root.service.savePluginData(root.id_, "glassEnabled", !root.glassOn);
    }

    pillClickAction: () => PopoutService.openSettingsWithTab("plugin:" + root.id_)
    pillRightClickAction: () => root.togglePause()

    horizontalBarPill: Component {
        Row {
            spacing: Theme.spacingXS

            DIcon {
                objectName: "pillIcon"
                anchors.verticalCenter: parent.verticalCenter
                name: root.lit ? "blur_on" : "blur_off"
                size: root.iconSize
                color: root.lit ? Theme.primary : Theme.surfaceVariantText
            }
            StyledText {
                objectName: "pillText"
                anchors.verticalCenter: parent.verticalCenter
                visible: text !== ""
                text: root.countText
                color: root.lit ? Theme.surfaceText : Theme.surfaceVariantText
                font.pixelSize: root.textSize
                wrapMode: Text.NoWrap
            }
        }
    }

    verticalBarPill: Component {
        Column {
            spacing: 2

            DIcon {
                objectName: "pillIcon"
                anchors.horizontalCenter: parent.horizontalCenter
                name: root.lit ? "blur_on" : "blur_off"
                size: root.iconSize
                color: root.lit ? Theme.primary : Theme.surfaceVariantText
            }
            StyledText {
                objectName: "pillText"
                anchors.horizontalCenter: parent.horizontalCenter
                visible: text !== ""
                text: root.countText
                color: root.lit ? Theme.surfaceText : Theme.surfaceVariantText
                font.pixelSize: Theme.fontSizeSmall
                wrapMode: Text.NoWrap
            }
        }
    }
}
