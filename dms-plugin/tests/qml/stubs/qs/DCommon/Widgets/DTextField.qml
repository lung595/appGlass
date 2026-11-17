import QtQuick

// Stand-in for DMS's DTextField (qs.DCommon.Widgets): a plain text input
// with only the properties the plugin sets
Item {
    id: field
    property alias text: input.text
    property string placeholderText: ""
    property string leftIconName: ""
    property bool showClearButton: false
    property Component trailingContent: null
    property var keyForwardTargets: []

    signal accepted
    signal cleared

    function forceActiveFocus() {
        input.forceActiveFocus();
    }

    implicitWidth: 200
    implicitHeight: 40
    TextInput {
        id: input
        anchors.fill: parent
        color: "white"
        onAccepted: field.accepted()
    }
    // The real field shows it at its right end, beside the clear button
    Loader {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        active: field.trailingContent !== null
        sourceComponent: field.trailingContent
    }
}
