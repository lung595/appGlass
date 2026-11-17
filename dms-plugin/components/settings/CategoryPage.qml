import QtQuick
import qs.Common
import qs.Widgets
import qs.DCommon.Widgets
import "SettingsIndex.js" as Index

// One category's settings under its name. It shows when it is the open
// category or, while a search is typed, when it holds a match (its items
// hide themselves with view.shown()).
//
// The setting widgets in it find it first (it has saveValue and loadValue):
// it hands their loads and saves to the settings page, and drops the saves
// until the page is ready. A slider or a selection saves every change of its
// value, the one from 0 to its default while it is built too, which would
// write the default over the saved value.
Column {
    id: page

    required property var view
    // the settings page (AppGlassSettings)
    required property var host
    readonly property var pluginService: page.host ? page.host.service : null
    required property string category
    readonly property var meta: Index.CATEGORIES.find(c => c.id === page.category) || {
        "name": page.category,
        "help": ""
    }
    default property alias content: body.data

    // A widget reloaded after a save of its key (the page's Pause, the
    // CLI) sets the value it was given and saves it back: the same value
    // is not written twice
    function saveValue(key, value) {
        if (!page.host || !page.host.ready)
            return;
        if (JSON.stringify(page.loadValue(key, undefined)) === JSON.stringify(value))
            return;
        page.host.saveValue(key, value);
    }
    function loadValue(key, defaultValue) {
        return page.host ? page.host.loadValue(key, defaultValue) : defaultValue;
    }

    objectName: "page-" + page.category
    width: parent ? parent.width : 0
    spacing: Theme.spacingS
    visible: page.view.filtering ? (page.view.counts[page.category] || 0) > 0 : page.view.current === page.category
    bottomPadding: Theme.spacingL

    // The title: the category's icon, its name in bold, then "· what it
    // is" on the same line (elided; left out on a narrow page)
    Item {
        width: parent.width
        height: 28

        DIcon {
            id: titleIcon
            objectName: "pageIcon-" + page.category
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            name: page.meta.icon || ""
            size: 20
            color: Theme.primary
        }
        StyledText {
            id: titleText
            objectName: "pageTitle-" + page.category
            anchors.left: titleIcon.right
            anchors.leftMargin: Theme.spacingS
            anchors.verticalCenter: parent.verticalCenter
            text: page.meta.name
            color: Theme.surfaceText
            font.pixelSize: Theme.fontSizeLarge
            font.weight: Font.Bold
            wrapMode: Text.NoWrap
        }
        StyledText {
            anchors.left: titleText.right
            anchors.leftMargin: Theme.spacingS
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            visible: !page.view.compact && page.meta.help !== ""
            text: "· " + page.meta.help
            color: Theme.surfaceVariantText
            font.pixelSize: Theme.fontSizeSmall
            elide: Text.ElideRight
            wrapMode: Text.NoWrap
        }
    }

    Column {
        id: body
        width: parent.width
        spacing: Theme.spacingM
    }
}
