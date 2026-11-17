import QtQuick
import qs.Common
import qs.Widgets
import qs.DCommon.Widgets
import "../logic.js" as Logic

// The apps of the last status, one row each: name, status, route and why,
// a switch (none for delegated, excluded and game rows) and, when an app has
// more than one route (or a saved one the status no longer lists), the
// routes to pick from. Turning an app on with a mod or forced route, or
// picking one while it is on, asks first (the sheet under the row); an app
// with no route list has nothing to force, so its switch never asks. The rows only call the page (host.setApp, host.setRoute,
// host.setAppRoute), which saves; the daemon syncs.
Column {
    id: list

    required property var view
    required property var host
    readonly property var rows: list.host.rows
    // key -> row; the delegates are keyed so a save does not rebuild them
    readonly property var byKey: {
        const out = {};
        for (const r of list.rows)
            out[r.key] = r;
        return out;
    }
    readonly property var blank: ({
            "appId": "",
            "toolkit": "",
            "kind": "",
            "reason": "",
            "risk": "",
            "switchable": false,
            "on": false,
            "route": "",
            "routes": [],
            "status": "",
            "statusLabel": "",
            "conflicts": []
        })
    // The question open: {key, route, tier}, or null; dropped as soon as
    // the page changes (another category, a search)
    property var pending: null

    Connections {
        target: list.view
        function onCurrentChanged() {
            list.pending = null;
        }
        function onQueryChanged() {
            list.pending = null;
        }
    }

    spacing: Theme.spacingS

    function syncKeys() {
        const keys = list.rows.map(r => r.key);
        let same = keys.length === keysModel.count;
        for (let i = 0; same && i < keys.length; i++)
            same = keysModel.get(i).key === keys[i];
        if (same)
            return;
        keysModel.clear();
        for (const k of keys)
            keysModel.append({
                "key": k
            });
    }

    onRowsChanged: list.syncKeys()
    Component.onCompleted: list.syncKeys()

    ListModel {
        id: keysModel
    }

    function statusColor(st) {
        if (st === "glass")
            return Theme.primary;
        if (st === "fallback")
            return Theme.warning;
        if (st === "delegated")
            return Theme.tertiary;
        if (st === "conflict")
            return Theme.error;
        return Theme.surfaceVariantText;
    }

    // The tier of one of the row's routes; none when the status lists no
    // route for the app (nothing to force: the engine keeps its fallback)
    function tierOf(row, name) {
        const r = row.routes.find(x => x.name === name);
        return r ? r.tier : "";
    }

    // The switch: on with a mod or forced route asks first
    function toggle(row, on) {
        const tier = list.tierOf(row, row.route);
        if (on && Logic.needsConfirm(tier)) {
            list.pending = {
                "key": row.key,
                "route": row.route,
                "tier": tier
            };
            return;
        }
        list.pending = null;
        list.host.setApp(row.key, on);
    }

    // A route chip: while the app is on, a mod or forced route asks first
    function choose(row, name) {
        // the route in use already: only a stale saved one is written over
        if (name === row.route) {
            if (row.routeStale) {
                list.pending = null;
                list.host.setRoute(row.key, name);
            }
            return;
        }
        const tier = list.tierOf(row, name);
        if (row.on && Logic.needsConfirm(tier)) {
            list.pending = {
                "key": row.key,
                "route": name,
                "tier": tier
            };
            return;
        }
        list.pending = null;
        list.host.setRoute(row.key, name);
    }

    function confirm() {
        const p = list.pending;
        list.pending = null;
        if (p)
            list.host.setAppRoute(p.key, p.route, true);
    }

    StyledText {
        objectName: "appListEmpty"
        width: list.width
        visible: list.rows.length === 0
        text: list.host.status ? "No app found yet: open one, then Advanced > Learn open windows" : "Waiting for the appglass status"
        color: Theme.surfaceVariantText
        font.pixelSize: Theme.fontSizeSmall
    }

    Repeater {
        model: keysModel

        delegate: StyledRect {
            id: row

            required property string key
            // a row whose app just left the status, until it goes
            readonly property var app: list.byKey[row.key] || Object.assign({}, list.blank, {
                "key": row.key,
                "name": row.key
            })
            readonly property bool asking: list.pending !== null && list.pending.key === row.app.key
            readonly property var asked: row.asking ? Logic.routeInfo(list.host.status, list.pending.route) : null

            objectName: "app:" + row.app.key
            width: list.width
            visible: !list.view.filtering || list.view.hits["appList"] === true || list.view.hits["app:" + row.app.key] === true
            height: visible ? texts.implicitHeight + Theme.spacingS * 2 : 0
            radius: Theme.cornerRadius
            color: Theme.surfaceContainerHigh

            Column {
                id: texts
                x: Theme.spacingM
                y: Theme.spacingS
                width: parent.width - Theme.spacingM * 2
                spacing: 4

                Item {
                    width: parent.width
                    height: Math.max(head.implicitHeight, toggle.height)

                    Column {
                        id: head
                        anchors.left: parent.left
                        anchors.right: chip.left
                        anchors.rightMargin: Theme.spacingS
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2

                        StyledText {
                            width: parent.width
                            text: row.app.name
                            color: Theme.surfaceText
                            font.pixelSize: Theme.fontSizeMedium
                            elide: Text.ElideRight
                            wrapMode: Text.NoWrap
                        }
                        StyledText {
                            objectName: "route-" + row.app.key
                            width: parent.width
                            text: row.app.routes.length ? row.app.route + (row.app.kind ? " · " + row.app.kind : "") + "  ·  " + row.app.appId : row.app.appId
                            color: Theme.surfaceVariantText
                            font.pixelSize: Theme.fontSizeSmall
                            elide: Text.ElideRight
                            wrapMode: Text.NoWrap
                        }
                    }

                    StyledRect {
                        id: chip
                        objectName: "status-" + row.app.key
                        readonly property string text: row.app.statusLabel
                        anchors.right: toggle.visible ? toggle.left : parent.right
                        anchors.rightMargin: toggle.visible ? Theme.spacingS : 0
                        anchors.verticalCenter: parent.verticalCenter
                        width: chipText.implicitWidth + Theme.spacingS * 2
                        height: 22
                        radius: 11
                        color: Theme.withAlpha(list.statusColor(row.app.status), 0.18)

                        StyledText {
                            id: chipText
                            anchors.centerIn: parent
                            text: chip.text
                            color: list.statusColor(row.app.status)
                            font.pixelSize: Theme.fontSizeSmall
                            wrapMode: Text.NoWrap
                        }
                    }

                    DToggle {
                        id: toggle
                        objectName: "appToggle-" + row.app.key
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        visible: row.app.switchable
                        enabled: row.app.switchable && list.host.glassOn && !list.host.gone
                        checked: row.app.on
                        onToggled: on => list.toggle(row.app, on)
                    }
                }

                StyledText {
                    objectName: "reason-" + row.app.key
                    width: parent.width
                    visible: text !== ""
                    text: row.app.reason
                    color: Theme.surfaceVariantText
                    font.pixelSize: Theme.fontSizeSmall
                }

                StyledText {
                    objectName: "conflict-" + row.app.key
                    width: parent.width
                    visible: row.app.conflicts.length > 0
                    text: "A hand-made file is in the way: " + row.app.conflicts.join(", ") + ". Advanced > Adopt hands it over."
                    color: Theme.error
                    font.pixelSize: Theme.fontSizeSmall
                }

                Flow {
                    width: parent.width
                    visible: Logic.showRoutes(row.app)
                    spacing: Theme.spacingXS

                    Repeater {
                        model: row.app.routes

                        delegate: DButton {
                            required property var modelData
                            objectName: "route-" + row.app.key + "-" + modelData.name
                            text: modelData.name + (modelData.kind ? " · " + modelData.kind : "")
                            variant: modelData.name === row.app.route ? "tonal" : "outlined"
                            enabled: !list.host.gone
                            onClicked: list.choose(row.app, modelData.name)
                        }
                    }
                }

                ConfirmSheet {
                    objectName: "confirm-" + row.app.key
                    open: row.asking
                    title: row.asking ? "Turn on " + row.app.name + " with " + list.pending.route + " (" + (list.pending.tier === "mod" ? "a mod" : "forced") + ")?" : ""
                    text: row.asked ? Logic.routeText(row.asked) : ""
                    risk: row.asked ? Logic.riskText(row.asked) : ""
                    confirmText: "Turn on"
                    onConfirmed: list.confirm()
                    onCancelled: list.pending = null
                }
            }
        }
    }
}
