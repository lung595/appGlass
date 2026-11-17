import QtQuick
import "logic.js" as Logic

// The pill's text (AppGlassWidget.qml creates it, see there why)
QtObject {
    property var status: null
    property bool glassOn: true
    readonly property string text: Logic.pillText(status, glassOn)
}
