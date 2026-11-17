import QtQuick
import Quickshell
import qs.Common
import qs.Services

// `dms ipc call plugins reload appGlass` after an update: DMS creates the
// daemon, the pill and the settings page again from their file URL plus
// "?revision=N", but the QML engine keeps every file those import by a
// relative path (components/logic.js, components/settings/...) cached under
// its old URL. An update whose root calls a new logic.js function then
// fails ("glassCount is not a function"). run.sh copies the plugin into
// reload/ for this test, which rewrites it in place (as git pull does) and
// loads it again with the next revision. run.sh also keeps the QML disk
// cache on for it, as quickshell does: an unchanged file loaded again comes
// back with the URL it was first compiled under, so its own URL does not
// tell the revision.
Item {
    id: root

    Harness {
        id: t
    }

    property var status: ({})
    property var made: []
    property var original: ({})

    readonly property var settingsFiles: ["AppGlassSettings.qml", "components/SettingsBody.qml"]
    readonly property var widgetFiles: ["AppGlassWidget.qml", "components/PillText.qml"]
    readonly property var daemonFiles: ["AppGlassDaemon.qml", "components/DaemonBody.qml"]

    // A file:// PUT only writes when asynchronous: writing counts the
    // pending ones, and each step after an update waits for none
    property int writing: 0
    function writeFile(rel, text) {
        const xhr = new XMLHttpRequest();
        root.writing++;
        xhr.onreadystatechange = () => {
            if (xhr.readyState === XMLHttpRequest.DONE)
                root.writing--;
        };
        xhr.open("PUT", Qt.resolvedUrl("reload/" + rel));
        xhr.send(text);
    }
    function source(rel) {
        if (root.original[rel] === undefined)
            root.original[rel] = t.readFile("reload/" + rel);
        return root.original[rel];
    }
    // The update: logic.js gains functions, and the file (old layout or new)
    // that calls `call` calls the new one instead
    function rewrite(files, call, newCall) {
        for (const rel of files) {
            const text = root.source(rel);
            if (text.indexOf(call) >= 0) {
                root.writeFile(rel, text.split(call).join(newCall));
                return rel;
            }
        }
        return "";
    }
    function update(version) {
        root.writeFile("components/logic.js", root.source("components/logic.js") + "\nfunction reloadProbe() {\n    return \"" + version + "\";\n}\nfunction reloadPill() {\n    return \"" + version + "\";\n}\nfunction reloadBin() {\n    return \"/probe/" + version + "\";\n}\n");
        return [root.rewrite(root.settingsFiles, "Logic.glassCount(root.status, true)", "Logic.reloadProbe()"), root.rewrite(root.widgetFiles, "Logic.pillText(", "Logic.reloadPill("), root.rewrite(root.daemonFiles, "Logic.appglassBin(", "Logic.reloadBin(")];
    }

    function create(rel, revision, props) {
        const url = Qt.resolvedUrl("reload/" + rel) + (revision ? "?revision=" + revision : "");
        const comp = Qt.createComponent(url, Component.PreferSynchronous);
        if (comp.status !== Component.Ready) {
            t.ok(rel + " r" + revision + " loads: " + comp.errorString(), false);
            return null;
        }
        const obj = comp.createObject(root, props);
        t.ok(rel + " r" + revision + " is created", obj !== null);
        if (obj)
            root.made.push(obj);
        return obj;
    }
    function unload() {
        for (const o of root.made)
            o.destroy();
        root.made = [];
    }

    property var page: null
    property var widget: null
    property var pill: null

    // DMS loading (or reloading) the plugin at a revision
    function load(revision) {
        Proc.reset();
        Proc.autoRun = false;
        Quickshell.reset();
        Quickshell.environment = {
            "HOME": "/tmp/fakehome",
            "XDG_RUNTIME_DIR": "/tmp/fakehome/run"
        };
        PluginService.reset();
        // as DMS's reloadPlugin: bump the counter, load <file>?revision=<it>
        PluginService._componentRevisions = revision ? {
            "appGlass": revision
        } : {};
        SettingsData.reset();
        SettingsData.pluginSettings = {
            "appGlass": {
                "enabled": true,
                "seeded": true
            }
        };
        PluginService.pluginPaths = {
            "appGlass": "/tmp/fakehome/plugin/"
        };
        PluginService.globalVars = {
            "appGlass": {
                "status": root.status,
                "lastError": "",
                "syncing": false
            }
        };
        const d = root.create("AppGlassDaemon.qml", revision, {
            "pluginId": "appGlass",
            "pluginService": PluginService
        });
        PluginService.pluginDaemonInstances = {
            "appGlass": d
        };
        PluginService.globalVars = {
            "appGlass": {
                "status": root.status,
                "lastError": "",
                "syncing": false
            }
        };
        root.page = root.create("AppGlassSettings.qml", revision, {
            "pluginService": PluginService,
            "width": 600
        });
        root.widget = root.create("AppGlassWidget.qml", revision, {
            "pluginId": "appGlass",
            "pluginService": PluginService
        });
        root.pill = root.widget ? root.widget.horizontalBarPill.createObject(root.widget) : null;
        return d;
    }

    function find(item, name) {
        if (!item)
            return null;
        if (item.objectName === name)
            return item;
        for (const kid of item.children || []) {
            const hit = find(kid, name);
            if (hit)
                return hit;
        }
        return null;
    }
    function text(item, name) {
        const hit = root.find(item, name);
        return hit ? hit.text : "(no " + name + ")";
    }
    function binsRun() {
        // cliArgv: sh -c 'exec "$0" "$@"' <bin> <args>
        return Proc.calls.map(c => (c.command || [])[3]).filter(b => String(b).indexOf("/probe/") === 0);
    }

    Component.onCompleted: {
        root.status = JSON.parse(t.readFile("contract/status.json"));
        t.steps([
            {
                "run": () => {
                    root.load(0);
                    t.check("first load: the header", root.text(root.page, "headerStatus"), "Glass on, 7 apps on glass");
                    t.check("first load: the pill", root.text(root.pill, "pillText"), "7");
                }
            },
            {
                "run": () => {
                    root.unload();
                    t.ok("the update rewrote a settings, pill and daemon file", root.update("v2").every(f => f !== ""));
                }
            },
            {
                "wait": 300,
                "run": () => {
                    t.check("the update is written", root.writing, 0);
                    root.load(1);
                }
            },
            {
                "wait": 50,
                "run": () => {
                    t.check("reload 1: the page calls the new logic.js", root.text(root.page, "headerStatus"), "Glass on, v2 apps on glass");
                    t.check("reload 1: the pill too", root.text(root.pill, "pillText"), "v2");
                    t.ok("reload 1: the daemon too", root.binsRun().indexOf("/probe/v2") >= 0);
                    root.unload();
                    root.update("v3");
                }
            },
            {
                "wait": 300,
                "run": () => {
                    t.check("the second update is written", root.writing, 0);
                    root.load(2);
                }
            },
            {
                "wait": 50,
                "run": () => {
                    t.check("reload 2: the page", root.text(root.page, "headerStatus"), "Glass on, v3 apps on glass");
                    t.check("reload 2: the pill", root.text(root.pill, "pillText"), "v3");
                    t.ok("reload 2: the daemon", root.binsRun().indexOf("/probe/v3") >= 0);
                    root.unload();
                }
            },
            {
                // DMS's counter is the revision even when it has no entry for
                // the plugin (0): the file's URL can be a stale ?revision=<n>,
                // the one the disk cache first compiled it under, and a body
                // at that revision's URL would be the old one compiled again.
                // The shells run.sh copied (Stale*.qml), first compiled here
                // at ?revision=1:
                "run": () => {
                    root.load(0);
                    root.unload();
                    PluginService._componentRevisions = {};
                    const shells = [["daemon", "StaleAppGlassDaemon.qml", "components/DaemonBody.qml", {
                                "pluginId": "appGlass",
                                "pluginService": PluginService
                            }], ["settings", "StaleAppGlassSettings.qml", "components/SettingsBody.qml", {
                                "pluginService": PluginService,
                                "width": 600
                            }], ["widget", "StaleAppGlassWidget.qml", "components/PillText.qml", {
                                "pluginId": "appGlass",
                                "pluginService": PluginService
                            }]];
                    for (const [name, file, rel, props] of shells) {
                        PluginService._componentRevisions = {};
                        const shell = root.create(file, 1, props);
                        const none = shell ? shell.freshUrl(rel) : "";
                        PluginService._componentRevisions = {
                            "appGlass": 1
                        };
                        const one = shell ? shell.freshUrl(rel) : "";
                        t.ok(name + ": no counter entry is revision 0, not the URL's 1", none !== "" && none.indexOf("/proc/") < 0);
                        t.ok(name + ": revision 0 and revision 1 load different body URLs", none !== one);
                    }
                    root.unload();
                }
            }
        ]);
    }
}
