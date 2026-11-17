import QtQuick
import qs.Common
import qs.Services
import qs.Widgets
import qs.DCommon.Widgets
import qs.Modules.Plugins
import "components/logic.js" as Logic

// The bar pill: the glass icon (crossed out while paused) and how many apps
// are on glass, from the daemon's shared status. A click opens the plugin's
// settings, a right click pauses or resumes the glass. It only saves
// glassEnabled; the daemon turns that into `appglass sync`.
PluginComponent {
    id: root

    readonly property var service: root.pluginService || PluginService
    readonly property bool glassOn: root.pluginData.glassEnabled !== false
    readonly property string countText: Logic.pillText(statusVar.value, root.glassOn)

    PluginGlobalVar {
        id: statusVar
        varName: "status"
        defaultValue: null
    }

    function togglePause() {
        root.service.savePluginData(Logic.PLUGIN_ID, "glassEnabled", !root.glassOn);
    }

    pillClickAction: () => PopoutService.openSettingsWithTab("plugin:" + Logic.PLUGIN_ID)
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
