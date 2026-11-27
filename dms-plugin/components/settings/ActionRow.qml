import QtQuick
import qs.Common
import qs.Widgets
import qs.DCommon.Widgets

// One Settings > Advanced action: its label and help (from the index) and a
// button; the button's objectName is the entry id
Column {
    id: action

    required property var view
    required property string key
    property string buttonText: ""
    property string iconName: ""
    property bool busy: false
    property bool danger: false
    property bool available: true

    signal clicked

    width: parent ? parent.width : 0
    spacing: Theme.spacingXS
    visible: action.view.shown(action.key)

    StyledText {
        width: parent.width
        text: action.view.label(action.key)
        color: Theme.surfaceText
        font.pixelSize: Theme.fontSizeMedium
    }
    StyledText {
        width: parent.width
        text: action.view.help(action.key)
        color: Theme.surfaceVariantText
        font.pixelSize: Theme.fontSizeSmall
    }
    DButton {
        objectName: action.key
        text: action.buttonText
        iconName: action.iconName
        variant: action.danger ? "outlined" : "tonal"
        danger: action.danger
        busy: action.busy
        enabled: action.available
        onClicked: action.clicked()
    }
}
