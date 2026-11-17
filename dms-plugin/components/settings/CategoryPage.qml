import QtQuick
import qs.Common
import qs.Widgets
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

    function saveValue(key, value) {
        if (page.host && page.host.ready)
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

    Column {
        width: parent.width
        spacing: 2

        StyledText {
            width: parent.width
            text: page.meta.name
            color: Theme.surfaceText
            font.pixelSize: Theme.fontSizeLarge
            font.weight: Theme.fontWeightMedium
        }
        StyledText {
            width: parent.width
            visible: !page.view.filtering
            text: page.meta.help
            color: Theme.surfaceVariantText
            font.pixelSize: Theme.fontSizeSmall
        }
    }

    Column {
        id: body
        width: parent.width
        spacing: Theme.spacingM
    }
}
