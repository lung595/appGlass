import QtQuick
import qs.Common
import qs.Widgets
import qs.DCommon.Widgets

// The search over every setting: typing filters the page, Enter opens the
// best match's category, Esc gives the page back.
Item {
    id: search

    required property var view

    signal released

    implicitHeight: field.implicitHeight + (hint.visible ? hint.implicitHeight + 2 : 0)

    function focusField() {
        field.forceActiveFocus();
    }

    function clear() {
        search.view.query = "";
        search.released();
    }

    DTextField {
        id: field
        objectName: "searchField"
        width: parent.width
        placeholderText: "Search settings and apps"
        leftIconName: "search"
        showClearButton: true
        onTextChanged: {
            if (search.view.query !== text)
                search.view.query = text;
        }
        onAccepted: search.view.openFirst()
        onCleared: search.clear()
        Keys.onEscapePressed: search.clear()
    }

    Connections {
        target: search.view
        function onQueryChanged() {
            if (field.text !== search.view.query)
                field.text = search.view.query;
        }
    }

    StyledText {
        id: hint
        objectName: "searchHint"
        anchors.top: field.bottom
        anchors.topMargin: 2
        width: parent.width
        visible: search.view.filtering && search.view.hasResults
        text: search.view.found.length + (search.view.found.length === 1 ? " match" : " matches") + "; Enter opens the first, Esc clears"
        color: Theme.surfaceVariantText
        font.pixelSize: Theme.fontSizeSmall
    }
}
