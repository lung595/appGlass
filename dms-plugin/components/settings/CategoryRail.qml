import QtQuick
import qs.Common
import "SettingsIndex.js" as Index

// The categories, top to bottom; icons only when the page is narrow
Column {
    id: rail

    required property var view

    objectName: "rail"
    width: rail.view.compact ? 48 : 168
    spacing: 2

    Accessible.role: Accessible.PageTabList

    Repeater {
        model: Index.CATEGORIES

        delegate: RailEntry {
            view: rail.view
        }
    }
}
