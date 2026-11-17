import QtQuick
import qs.Common
import qs.Widgets
import qs.DCommon.Widgets

// One category of the rail. The open one is tinted; while a search is typed
// the categories with a match carry their count and the others fade. The
// arrow keys open the next or previous category and take the focus there
// (stepped: the rail moves it); narrow, the name shows beside the icon on
// hover or focus. A faded entry fades its background, icon and name only:
// the name tip and the count stay opaque.
Item {
    id: entry

    required property var view
    required property var modelData

    readonly property bool on: !entry.view.filtering && entry.view.current === entry.modelData.id
    readonly property int count: entry.view.counts[entry.modelData.id] || 0
    readonly property bool dim: entry.view.filtering && entry.count === 0
    readonly property real dimOpacity: entry.dim ? 0.4 : 1

    signal clicked
    signal stepped(int by)

    objectName: "rail-" + entry.modelData.id
    width: parent ? parent.width : 0
    height: 40
    activeFocusOnTab: true

    Accessible.role: Accessible.PageTab
    Accessible.name: entry.modelData.name
    Accessible.selected: entry.on
    Accessible.onPressAction: entry.clicked()

    // a click (or tap) takes the focus too, so the arrow keys step from here
    onClicked: {
        entry.forceActiveFocus();
        entry.view.pick(entry.modelData.id);
    }

    Keys.onReturnPressed: entry.clicked()
    Keys.onEnterPressed: entry.clicked()
    Keys.onSpacePressed: entry.clicked()
    Keys.onUpPressed: entry.stepped(-1)
    Keys.onDownPressed: entry.stepped(1)

    HoverHandler {
        id: hover
        cursorShape: Qt.PointingHandCursor
    }
    TapHandler {
        onTapped: entry.clicked()
    }

    StyledRect {
        objectName: "railBg-" + entry.modelData.id
        anchors.fill: parent
        opacity: entry.dimOpacity
        radius: height / 2
        color: entry.on ? Theme.withAlpha(Theme.primary, 0.16) : (hover.hovered ? Theme.withAlpha(Theme.surfaceText, 0.06) : "transparent")
        border.width: entry.activeFocus ? 2 : 0
        border.color: Theme.primary
    }

    DIcon {
        id: icon
        objectName: "railIcon-" + entry.modelData.id
        opacity: entry.dimOpacity
        x: entry.view.compact ? (entry.width - size) / 2 : Theme.spacingM
        anchors.verticalCenter: parent.verticalCenter
        name: entry.modelData.icon
        size: 20
        color: entry.on ? Theme.primary : Theme.surfaceText
    }

    StyledText {
        objectName: "railName-" + entry.modelData.id
        opacity: entry.dimOpacity
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

    // Wide: at the row's end; narrow: on the icon's upper-right corner.
    // Placed by x/y: switching anchors between top and verticalCenter left
    // both set for a moment, which stretched it to the row's height.
    StyledRect {
        id: badge
        objectName: "railCount-" + entry.modelData.id
        visible: entry.view.filtering && entry.count > 0
        x: entry.view.compact ? Math.min(entry.width - width, icon.x + icon.size - 6) : entry.width - width - Theme.spacingS
        y: entry.view.compact ? 0 : (entry.height - height) / 2
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

    // Narrow: the name beside the icon on hover or focus
    StyledRect {
        objectName: "railTip-" + entry.modelData.id
        readonly property string text: entry.modelData.name
        visible: entry.view.compact && (hover.hovered || entry.activeFocus)
        z: 10
        x: entry.width + Theme.spacingXS
        anchors.verticalCenter: parent.verticalCenter
        width: tipText.implicitWidth + Theme.spacingS * 2
        height: 28
        radius: 8
        color: Theme.surfaceContainerHigh
        border.width: 1
        border.color: Theme.outline

        StyledText {
            id: tipText
            anchors.centerIn: parent
            text: entry.modelData.name
            color: Theme.surfaceText
            font.pixelSize: Theme.fontSizeSmall
            wrapMode: Text.NoWrap
        }
    }
}
