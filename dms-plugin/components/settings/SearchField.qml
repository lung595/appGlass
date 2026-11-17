import QtQuick
import qs.Common
import qs.Widgets
import qs.DCommon.Widgets

// The search over every setting: typing filters the page, Enter opens the
// best match's category, Esc clears it, a second Esc gives the page back. The key hint sits in the
// field (how to come here at rest, how to get out while typing), so typing
// does not move the page.
Item {
    id: search

    required property var view

    signal released

    objectName: "search"
    implicitHeight: field.implicitHeight

    function focusField() {
        field.forceActiveFocus();
    }

    function release() {
        if (field.setFocus)
            field.setFocus(false);
        search.released();
    }
    function clear() {
        search.view.query = "";
        search.release();
    }
    // Esc: a typed search is cleared first, the focus kept for a new one
    function stepBack() {
        if (field.text !== "" || search.view.query !== "") {
            search.view.query = "";
            field.text = "";
            return;
        }
        search.release();
    }

    DTextField {
        id: field
        objectName: "searchField"
        width: parent.width
        placeholderText: "Search settings and apps"
        leftIconName: "search"
        showClearButton: true
        trailingContent: Component {
            StyledRect {
                objectName: "searchHintChip"
                width: hintText.implicitWidth + 16
                height: 24
                radius: 12
                color: Theme.withAlpha(Theme.surfaceText, 0.07)

                StyledText {
                    id: hintText
                    objectName: "searchHint"
                    anchors.centerIn: parent
                    text: search.view.filtering ? "Esc clears" : (search.view.compact ? "/" : "Ctrl+F or /")
                    color: Theme.surfaceVariantText
                    font.pixelSize: Theme.fontSizeSmall
                    wrapMode: Text.NoWrap
                }
            }
        }
        onTextChanged: {
            if (search.view.query !== text)
                search.view.query = text;
        }
        onAccepted: search.view.openFirst()
        onCleared: search.clear()
        Keys.onEscapePressed: search.stepBack()
    }

    Connections {
        target: search.view
        function onQueryChanged() {
            if (field.text !== search.view.query)
                field.text = search.view.query;
        }
    }
}
