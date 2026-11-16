import QtQuick
import qs.Common
import qs.Widgets
import qs.DCommon.Widgets
import "logic.js" as Logic

// The apps of the last status, one row each: name, app-id, tier badge, why,
// and a switch (none for delegated, excluded and game rows). The switch
// shows the saved choice (`apps` in the plugin data) until the next status
// has it; a tap only emits appToggled: the settings page saves it.
Column {
    id: root

    property var status: null
    // The plugin data `apps` map
    property var apps: ({})
    property string filter: ""
    readonly property var rows: Logic.appRows(root.status, root.filter)

    signal appToggled(string key, bool on)

    spacing: Theme.spacingS

    function shownOn(row) {
        const a = root.apps ? root.apps[row.key] : null;
        return a && typeof a.enabled === "boolean" ? a.enabled : row.on;
    }

    function badgeColor(b) {
        if (b === "Native")
            return Theme.primary;
        if (b === "Forced" || b === "Mod")
            return Theme.warning;
        if (b === "Delegated")
            return Theme.tertiary;
        return Theme.outline;
    }

    DTextField {
        id: search
        objectName: "search"
        width: root.width
        placeholderText: I18n.trFor("appGlass", "Search apps")
        onTextChanged: root.filter = text
    }

    StyledText {
        width: root.width
        visible: root.rows.length === 0
        text: root.status ? I18n.trFor("appGlass", "No app matches") : I18n.trFor("appGlass", "Waiting for appglass status")
        color: Theme.surfaceVariantText
        font.pixelSize: Theme.fontSizeSmall
    }

    Repeater {
        model: root.rows

        delegate: StyledRect {
            id: row
            required property var modelData
            width: root.width
            height: Math.max(56, texts.implicitHeight + Theme.spacingS * 2)
            radius: Theme.cornerRadius
            color: Theme.surfaceContainerHigh

            Column {
                id: texts
                anchors.left: parent.left
                anchors.leftMargin: Theme.spacingM
                anchors.right: badge.left
                anchors.rightMargin: Theme.spacingS
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2

                StyledText {
                    width: parent.width
                    text: row.modelData.name
                    color: Theme.surfaceText
                    font.pixelSize: Theme.fontSizeMedium
                    wrapMode: Text.NoWrap
                }
                StyledText {
                    width: parent.width
                    text: row.modelData.appId + "  ·  " + row.modelData.reason
                    color: Theme.surfaceVariantText
                    font.pixelSize: Theme.fontSizeSmall
                    wrapMode: Text.NoWrap
                }
            }

            StyledRect {
                id: badge
                anchors.right: toggle.left
                anchors.rightMargin: Theme.spacingS
                anchors.verticalCenter: parent.verticalCenter
                width: badgeText.implicitWidth + Theme.spacingS * 2
                height: 22
                radius: 11
                color: Theme.withAlpha(root.badgeColor(row.modelData.badge), 0.18)

                StyledText {
                    id: badgeText
                    anchors.centerIn: parent
                    text: I18n.trFor("appGlass", row.modelData.badge)
                    color: root.badgeColor(row.modelData.badge)
                    font.pixelSize: Theme.fontSizeSmall
                    wrapMode: Text.NoWrap
                }
            }

            DToggle {
                id: toggle
                objectName: "appToggle-" + row.modelData.key
                anchors.right: parent.right
                anchors.rightMargin: Theme.spacingM
                anchors.verticalCenter: parent.verticalCenter
                visible: row.modelData.switchable
                enabled: row.modelData.switchable
                checked: root.shownOn(row.modelData)
                onToggled: on => root.appToggled(row.modelData.key, on)
            }
        }
    }
}
