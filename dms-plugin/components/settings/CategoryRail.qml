import QtQuick
import qs.Common
import "SettingsIndex.js" as Index

// The categories, top to bottom; icons only when the page is narrow
Column {
    id: rail

    required property var view

    objectName: "rail"
    width: rail.view.compact ? 48 : 168
    spacing: Theme.spacingXXS

    Accessible.role: Accessible.PageTabList

    // The arrow keys: from the focused entry (Tab may have moved the focus
    // off the open one) the next or previous category opens and the focus
    // follows it, so Enter or Space acts on the one shown
    function step(from, by) {
        const n = Index.CATEGORIES.length;
        const at = (Math.max(0, Index.CATEGORIES.findIndex(c => c.id === from)) + by + n) % n;
        rail.view.pick(Index.CATEGORIES[at].id);
        const item = entries.itemAt(at);
        if (item)
            item.forceActiveFocus();
    }

    Repeater {
        id: entries
        model: Index.CATEGORIES

        delegate: RailEntry {
            view: rail.view
            onStepped: by => rail.step(modelData.id, by)
        }
    }
}
