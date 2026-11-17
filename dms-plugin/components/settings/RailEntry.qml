import QtQuick
import qs.Common
import qs.Widgets
import qs.DCommon.Widgets

// One category of the rail. The open one is tinted; while a search is typed
// the categories with a match carry their count and the others fade.
Item {
    id: entry

    required property var view
    required property var modelData

    readonly property bool on: !entry.view.filtering && entry.view.current === entry.modelData.id
    readonly property int count: entry.view.counts[entry.modelData.id] || 0
    readonly property bool dim: entry.view.filtering && entry.count === 0

    signal clicked

    objectName: "rail-" + entry.modelData.id
    width: parent ? parent.width : 0
    height: 40
    opacity: entry.dim ? 0.4 : 1
    activeFocusOnTab: true

    Accessible.role: Accessible.PageTab
    Accessible.name: entry.modelData.name
    Accessible.selected: entry.on
    Accessible.onPressAction: entry.clicked()

    onClicked: entry.view.pick(entry.modelData.id)

    Keys.onReturnPressed: entry.clicked()
    Keys.onEnterPressed: entry.clicked()
    Keys.onSpacePressed: entry.clicked()
    Keys.onUpPressed: entry.view.step(-1)
    Keys.onDownPressed: entry.view.step(1)

    HoverHandler {
        id: hover
        cursorShape: Qt.PointingHandCursor
    }
    TapHandler {
        onTapped: entry.clicked()
    }

    StyledRect {
        anchors.fill: parent
        radius: height / 2
        color: entry.on ? Theme.withAlpha(Theme.primary, 0.16) : (hover.hovered ? Theme.withAlpha(Theme.surfaceText, 0.06) : "transparent")
        border.width: entry.activeFocus ? 2 : 0
        border.color: Theme.primary
    }

    DIcon {
        id: icon
        x: entry.view.compact ? (entry.width - size) / 2 : Theme.spacingM
        anchors.verticalCenter: parent.verticalCenter
        name: entry.modelData.icon
        size: 20
        color: entry.on ? Theme.primary : Theme.surfaceText
    }

    StyledText {
        visible: !entry.view.compact
        anchors.left: icon.right
        anchors.leftMargin: Theme.spacingS
        anchors.right: badge.visible ? badge.left : parent.right
        anchors.rightMargin: Theme.spacingS
        anchors.verticalCenter: parent.verticalCenter
        text: entry.modelData.name
        elide: Text.ElideRight
        wrapMode: Text.NoWrap
        font.pixelSize: Theme.fontSizeMedium
        font.weight: entry.on ? Theme.fontWeightMedium : Font.Normal
        color: entry.on ? Theme.primary : Theme.surfaceText
    }

    StyledRect {
        id: badge
        objectName: "railCount-" + entry.modelData.id
        visible: entry.view.filtering && entry.count > 0
        anchors.right: parent.right
        anchors.rightMargin: entry.view.compact ? 0 : Theme.spacingS
        anchors.top: entry.view.compact ? parent.top : undefined
        anchors.verticalCenter: entry.view.compact ? undefined : parent.verticalCenter
        width: Math.max(20, countText.implicitWidth + 10)
        height: 20
        radius: 10
        color: Theme.primary

        StyledText {
            id: countText
            anchors.centerIn: parent
            text: entry.count
            color: Theme.primaryText
            font.pixelSize: Theme.fontSizeSmall
            wrapMode: Text.NoWrap
        }
    }
}
