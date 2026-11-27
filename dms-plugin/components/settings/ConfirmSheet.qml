import QtQuick
import qs.Common
import qs.Widgets
import qs.DCommon.Widgets

// An inline question before a step that cannot be taken lightly: what it
// does, the risk, and two buttons (objectName + "-yes" / "-no"). It only
// emits; whoever opened it does the step.
StyledRect {
    id: sheet

    property bool open: false
    property string title: ""
    property string text: ""
    property string risk: ""
    property string confirmText: "Continue"
    property bool danger: false

    signal confirmed
    signal cancelled

    visible: sheet.open
    width: parent ? parent.width : 0
    height: sheet.open ? body.implicitHeight + Theme.spacingM * 2 : 0
    radius: Theme.cornerRadius
    color: Theme.withAlpha(sheet.danger ? Theme.error : Theme.warning, 0.10)
    border.width: 1
    border.color: Theme.withAlpha(sheet.danger ? Theme.error : Theme.warning, 0.45)

    Column {
        id: body
        x: Theme.spacingM
        y: Theme.spacingM
        width: parent.width - Theme.spacingM * 2
        spacing: Theme.spacingS

        Row {
            width: parent.width
            spacing: Theme.spacingS
            DIcon {
                name: sheet.danger ? "warning" : "help"
                size: Theme.iconSize - Theme.spacingXS
                color: sheet.danger ? Theme.error : Theme.warning
            }
            StyledText {
                width: parent.width - 28
                text: sheet.title
                color: Theme.surfaceText
                font.pixelSize: Theme.fontSizeMedium
                font.weight: Theme.fontWeightMedium
            }
        }
        StyledText {
            width: parent.width
            visible: text !== ""
            text: sheet.text
            color: Theme.surfaceText
            font.pixelSize: Theme.fontSizeSmall
        }
        StyledText {
            width: parent.width
            visible: text !== ""
            text: sheet.risk ? "Risk: " + sheet.risk : ""
            color: Theme.surfaceVariantText
            font.pixelSize: Theme.fontSizeSmall
        }
        Row {
            spacing: Theme.spacingS
            DButton {
                objectName: sheet.objectName + "-yes"
                text: sheet.confirmText
                variant: "filled"
                danger: sheet.danger
                onClicked: sheet.confirmed()
            }
            DButton {
                objectName: sheet.objectName + "-no"
                text: "Cancel"
                variant: "text"
                onClicked: sheet.cancelled()
            }
        }
    }
}
