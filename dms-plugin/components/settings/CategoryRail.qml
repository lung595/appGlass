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

    // The arrow keys: the next or previous category opens and the focus
    // follows it, so Enter or Space acts on the one shown
    function step(by) {
        rail.view.step(by);
        const at = Index.CATEGORIES.findIndex(c => c.id === rail.view.current);
        const item = entries.itemAt(at);
        if (item)
            item.forceActiveFocus();
    }

    Repeater {
        id: entries
        model: Index.CATEGORIES

        delegate: RailEntry {
            view: rail.view
            onStepped: by => rail.step(by)
        }
    }
}
