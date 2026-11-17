import QtQuick
import qs.Common
import qs.Services
import qs.Widgets
import qs.DCommon.Widgets
import qs.Modules.Plugins

// The bar pill: the glass icon (crossed out while paused) and how many apps
// are on glass, from the daemon's shared status. A click opens the plugin's
// settings, a right click pauses or resumes the glass. It only saves
// glassEnabled; the daemon turns that into `appglass sync`.
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
    readonly property var pillText: {
        const comp = Qt.createComponent(root.freshUrl("components/PillText.qml"), Component.PreferSynchronous);
        if (comp.status !== Component.Ready) {
            console.warn("appGlass: the pill text did not load: " + comp.errorString());
            return null;
        }
        return comp.createObject(root, {
            "status": Qt.binding(() => statusVar.value),
            "glassOn": Qt.binding(() => root.glassOn)
        });
    }
    readonly property string countText: root.pillText ? root.pillText.text : ""

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

    PluginGlobalVar {
        id: statusVar
        varName: "status"
        defaultValue: null
    }

    function togglePause() {
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
                name: root.glassOn ? "blur_on" : "blur_off"
                size: root.iconSize
                color: root.glassOn ? Theme.primary : Theme.surfaceVariantText
            }
            StyledText {
                objectName: "pillText"
                anchors.verticalCenter: parent.verticalCenter
                visible: text !== ""
                text: root.countText
                color: root.glassOn ? Theme.surfaceText : Theme.surfaceVariantText
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
                name: root.glassOn ? "blur_on" : "blur_off"
                size: root.iconSize
                color: root.glassOn ? Theme.primary : Theme.surfaceVariantText
            }
            StyledText {
                objectName: "pillText"
                anchors.horizontalCenter: parent.horizontalCenter
                visible: text !== ""
                text: root.countText
                color: root.glassOn ? Theme.surfaceText : Theme.surfaceVariantText
                font.pixelSize: Theme.fontSizeSmall
                wrapMode: Text.NoWrap
            }
        }
    }
}
