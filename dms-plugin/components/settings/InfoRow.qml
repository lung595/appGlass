import QtQuick
import qs.Common
import qs.Widgets

// A read-only line: the entry's label, and a text (its help by default)
Column {
    id: info

    required property var view
    required property string key
    property string text: info.view.help(info.key)

    objectName: info.key
    width: parent ? parent.width : 0
    spacing: 2
    visible: info.view.shown(info.key)

    StyledText {
        width: parent.width
        text: info.view.label(info.key)
        color: Theme.surfaceText
        font.pixelSize: Theme.fontSizeMedium
    }
    StyledText {
        width: parent.width
        text: info.text
        color: Theme.surfaceVariantText
        font.pixelSize: Theme.fontSizeSmall
    }
}
