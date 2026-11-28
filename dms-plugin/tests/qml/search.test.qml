import QtQuick
import "components/logic.js" as Logic
import "components/settings/SettingsIndex.js" as Index
import "components/settings/Search.js" as Search

// components/settings/Search.js and SettingsIndex.js: the words typed find a
// setting by its label, its keywords or its help, every word must match, and
// the app list joins the index one entry per app.
Item {
    Harness {
        id: t
    }

    function ids(list) {
        return list.map(r => r.id);
    }

    Component.onCompleted: {
        const status = JSON.parse(t.readFile("contract/status.json"));
        const cats = Index.CATEGORIES.map(c => c.id);
        t.check("the rail", cats, ["glass", "apps", "fallback", "advanced", "about"]);
        t.ok("every category has an icon, a name and a help line", Index.CATEGORIES.every(c => c.icon && c.name && c.help));
        t.ok("every entry is in a category", Index.ENTRIES.every(e => cats.indexOf(e.category) >= 0 && e.label && e.help));
        const seen = {};
        t.ok("entry ids unique", Index.ENTRIES.every(e => !seen[e.id] && (seen[e.id] = true)));
        t.ok("every category has an entry", cats.every(c => Index.ENTRIES.some(e => e.category === c)));

        // --- matching
        const fb = Search.search(Index.ENTRIES, "fallback");
        t.check("\"fallback\": the Fallback page first", Index.ENTRIES.filter(e => e.category === "fallback").map(e => e.id).every(id => ids(fb).indexOf(id) >= 0), true);
        t.check("\"fallback\": best match is on the Fallback page", Index.ENTRIES.filter(e => e.id === fb[0].id)[0].category, "fallback");
        t.check("no fade setting left (0.1.4)", Index.ENTRIES.filter(e => e.id.indexOf("inactive") === 0), []);
        t.check("\"xyz\": nothing", Search.search(Index.ENTRIES, "xyz"), []);
        t.check("empty query: nothing", Search.search(Index.ENTRIES, "   "), []);
        t.check("case and prefix", ids(Search.search(Index.ENTRIES, "UNINST")), ["uninstallButton"]);
        t.check("every word must match", ids(Search.search(Index.ENTRIES, "fallback value")), ["fallbackValue"]);
        t.ok("a keyword finds it", ids(Search.search(Index.ENTRIES, "opacity")).indexOf("fallbackMode") >= 0);
        t.check("label beats help", ids(Search.search([{
                    "id": "b",
                    "category": "x",
                    "label": "Other",
                    "help": "mentions pause"
                }, {
                    "id": "a",
                    "category": "x",
                    "label": "Pause",
                    "help": ""
                }], "pause")), ["a", "b"]);

        // --- the apps join the index
        const apps = Index.appEntries(Logic.appRows(status, {}, true));
        t.check("one entry per app", apps.length, status.apps.length);
        t.check("app entry", apps.filter(e => e.id === "app:vlc")[0].category, "apps");
        t.check("an app by name", ids(Search.search(apps, "flatseal")), ["app:com.github.tchx84.Flatseal"]);
        t.ok("an app by status", ids(Search.search(apps, "conflict")).indexOf("app:vlc") >= 0);
        t.ok("an app by toolkit", ids(Search.search(apps, "gtk3")).indexOf("app:solaar") >= 0);
        t.finish();
    }
}
