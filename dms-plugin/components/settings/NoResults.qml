import QtQuick
import qs.Common
import qs.Widgets
import qs.DCommon.Widgets

// What a search that matches nothing shows
Column {
    id: none

    property string query: ""

    objectName: "noResults"
    spacing: Theme.spacingS
    topPadding: Theme.spacingL

    DIcon {
        anchors.horizontalCenter: parent.horizontalCenter
        name: "search_off"
        size: 32
        color: Theme.surfaceVariantText
    }
    StyledText {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: "Nothing matches \"" + none.query.trim() + "\""
        color: Theme.surfaceText
        font.pixelSize: Theme.fontSizeMedium
    }
    StyledText {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: "Try a setting's name, an app's name or a status such as glass or conflict"
        color: Theme.surfaceVariantText
        font.pixelSize: Theme.fontSizeSmall
    }
}
