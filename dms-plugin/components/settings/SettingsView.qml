import QtQuick
import "SettingsIndex.js" as Index
import "Search.js" as Search

// What the settings page shows: the open category, or, while a search is
// typed, every setting that matches it across the categories. The rail, the
// search field and the pages all read this one object.
QtObject {
    id: view

    // The open category (Index.CATEGORIES ids)
    property string current: "glass"
    property string query: ""
    // The rail keeps its icons only
    property bool compact: false
    // Entries that come and go with the status (one per app)
    property var extraEntries: []
    // Ids of rows not offered now (a search must not count them)
    property var hiddenIds: []

    readonly property var entries: Index.ENTRIES.filter(e => view.hiddenIds.indexOf(e.id) < 0).concat(view.extraEntries)
    readonly property bool filtering: view.query.trim() !== ""
    readonly property var found: view.filtering ? Search.search(view.entries, view.query) : []
    readonly property bool hasResults: view.found.length > 0
    // id -> true for every match
    readonly property var hits: {
        const out = {};
        for (const r of view.found)
            out[r.id] = true;
        return out;
    }
    // category -> how many matches
    readonly property var counts: {
        const out = {};
        for (const r of view.found)
            out[r.category] = (out[r.category] || 0) + 1;
        return out;
    }

    // Opens a category from the rail; a search typed is given up
    function pick(category) {
        if (!Index.CATEGORIES.some(c => c.id === category))
            return;
        view.query = "";
        view.current = category;
    }

    // The next or previous category (the rail's arrow keys)
    function step(by) {
        const ids = Index.CATEGORIES.map(c => c.id);
        const at = Math.max(0, ids.indexOf(view.current));
        view.pick(ids[(at + by + ids.length) % ids.length]);
    }

    // Enter in the search field: the best match's category
    function openFirst() {
        if (view.hasResults)
            view.pick(view.found[0].category);
    }

    // Whether the item `id` shows: always, unless a search leaves it out
    function shown(id) {
        return !view.filtering || view.hits[id] === true;
    }

    function info(id) {
        return Index.ENTRIES.find(e => e.id === id) || {
            "id": id,
            "label": id,
            "help": ""
        };
    }
    function label(id) {
        return view.info(id).label;
    }
    function help(id) {
        return view.info(id).help;
    }
}
