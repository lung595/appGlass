import QtQuick
import qs.Common
import qs.Services
import qs.Widgets
import qs.DCommon.Widgets
import qs.Modules.Plugins
import "settings"
import "settings/SettingsIndex.js" as Index
import "logic.js" as Logic

// The settings page: a search field on top, then the glass state with the
// global Pause, the categories on the left
// (Glass, Apps, Fade, Fallback, Advanced, About), one category at a time on
// the right; typing shows every matching setting across them, editable in
// place. The setting widgets save into the plugin data (keys at the top of
// components/logic.js), which the daemon turns into `appglass sync`; what
// is shown about the apps comes from the daemon's shared status, and the
// Advanced actions run in the daemon. This page runs no command itself.
//
// AppGlassSettings.qml creates it (see there why) with pluginId and
// pluginService, as DMS does for a settings page.
PluginSettings {
    id: root

    readonly property var service: root.pluginService || PluginService
    readonly property var vars: root.service.globalVars[Logic.PLUGIN_ID] || ({})
    readonly property var daemon: root.service.pluginDaemonInstances ? (root.service.pluginDaemonInstances[Logic.PLUGIN_ID] || null) : null
    readonly property var status: root.vars.status || null
    readonly property string lastError: root.vars.lastError || ""
    readonly property bool syncing: root.vars.syncing === true
    readonly property string action: root.vars.action || ""
    // "" | "removed" | "linkStays": the files are back (and the link stayed);
    // "interrupted": a reload cut the uninstall short (Uninstall again)
    readonly property string uninstallState: root.vars.uninstallState || ""
    // uninstalled: the daemon syncs nothing, so nothing here offers a change
    // (the Fade and Fallback pages are disabled, CategoryPage drops a save)
    readonly property bool gone: root.uninstallState !== ""
    // why the last Uninstall failed (kept after the sync that followed)
    readonly property string uninstallError: root.vars.uninstallError || ""
    // The pages' widgets save from here on (CategoryPage)
    property bool ready: false
    // The saved switches, reloaded whenever the plugin data changes
    property bool glassOn: true
    property var savedApps: ({})
    readonly property var rows: Logic.appRows(root.status, root.savedApps, root.glassOn)
    readonly property var conflicts: root.status && Array.isArray(root.status.hand_files) ? root.status.hand_files.filter(h => h && h.status === "conflict").map(h => String(h.path)) : []

    // Below this width the rail keeps its icons only
    readonly property int narrowWidth: 460

    function loadState() {
        root.glassOn = root.service.loadPluginData(Logic.PLUGIN_ID, "glassEnabled", true) !== false;
        const a = root.service.loadPluginData(Logic.PLUGIN_ID, "apps", {});
        root.savedApps = a && typeof a === "object" && !Array.isArray(a) ? a : {};
    }

    // PluginSettings reloads only the widgets declared right in it; these
    // sit in the category pages
    function reloadWidgets(item) {
        for (const kid of item ? item.children : []) {
            if (kid.settingKey !== undefined && typeof kid.loadValue === "function")
                kid.loadValue();
            else
                root.reloadWidgets(kid);
        }
    }

    function saveApps(apps) {
        root.saveValue("apps", apps);
        root.loadState();
    }
    function setApp(key, on) {
        root.saveApps(Logic.withApp(root.savedApps, key, on));
    }
    function setRoute(key, route) {
        root.saveApps(Logic.withRoute(root.savedApps, key, route));
    }
    function setAppRoute(key, route, on) {
        root.saveApps(Logic.withApp(Logic.withRoute(root.savedApps, key, route), key, on));
    }
    function setGlass(on) {
        root.saveValue("glassEnabled", !!on);
        root.loadState();
    }

    function noDaemon() {
        ToastService.showWarning("appGlass: the plugin daemon is not running");
        return false;
    }
    function reapply() {
        return root.daemon && root.daemon.requestSync ? root.daemon.requestSync("reapply", 0) : root.noDaemon();
    }
    function runAction(name) {
        return root.daemon && root.daemon.runAction ? root.daemon.runAction(name) : root.noDaemon();
    }
    function reinstall() {
        return root.daemon && root.daemon.reinstall ? root.daemon.reinstall() : root.noDaemon();
    }
    function copyReport() {
        return root.daemon && root.daemon.copyReport ? root.daemon.copyReport() : root.noDaemon();
    }

    // The widgets in the pages load before their parents reach this page:
    // once everything is built they load again, then they may save
    Component.onCompleted: {
        root.loadState();
        Qt.callLater(() => {
            root.reloadWidgets(pages);
            root.ready = true;
        });
    }

    Connections {
        target: root.service
        function onPluginDataChanged(changedPluginId) {
            if (changedPluginId !== root.pluginId)
                return;
            root.loadState();
            root.reloadWidgets(pages);
        }
    }

    FocusScope {
        id: page
        width: parent ? parent.width : 0
        implicitHeight: column.implicitHeight

        SettingsView {
            id: view
            compact: page.width < root.narrowWidth
            extraEntries: Index.appEntries(root.rows)
        }

        // Ctrl+F reaches the field from anywhere in the window; "/" only
        // when no text field took it
        Shortcut {
            sequence: "Ctrl+F"
            enabled: page.visible
            onActivated: search.focusField()
        }
        Keys.onPressed: event => {
            if (event.text === "/" && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier))) {
                search.focusField();
                event.accepted = true;
            } else if (event.key === Qt.Key_Escape && view.filtering) {
                view.query = "";
                event.accepted = true;
            }
        }
        // A click on the page gives it the keys ("/", Esc); the controls
        // keep their own clicks
        TapHandler {
            gesturePolicy: TapHandler.ReleaseWithinBounds
            grabPermissions: PointerHandler.ApprovesTakeOverByAnything
            onTapped: page.forceActiveFocus()
        }

        Column {
            id: column
            width: parent.width
            spacing: Theme.spacingM

            SearchField {
                id: search
                width: parent.width
                view: view
                onReleased: page.forceActiveFocus()
            }

            // --- the state, pause, the last error -------------------------
            Item {
                width: parent.width
                height: Math.max(headerText.implicitHeight, pauseButton.implicitHeight)

                Row {
                    id: headerText
                    anchors.left: parent.left
                    anchors.right: pauseButton.left
                    anchors.rightMargin: Theme.spacingS
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Theme.spacingS

                    DIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        name: root.glassOn && !root.gone ? "blur_on" : "blur_off"
                        size: 22
                        color: root.glassOn && !root.gone ? Theme.primary : Theme.surfaceVariantText
                    }
                    StyledText {
                        objectName: "headerStatus"
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 30
                        text: root.uninstallState === "interrupted" ? "Uninstall did not finish" : root.gone ? "Uninstalled: every file restored" : !root.glassOn ? "Glass paused" : (root.status ? "Glass on, " + Logic.glassCount(root.status, true) + " apps on glass" : "Waiting for appglass")
                        color: Theme.surfaceText
                        font.pixelSize: Theme.fontSizeMedium
                        font.weight: Theme.fontWeightMedium
                        elide: Text.ElideRight
                        wrapMode: Text.NoWrap
                    }
                }

                DButton {
                    id: pauseButton
                    objectName: "pauseButton"
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.glassOn ? "Pause glass" : "Resume glass"
                    iconName: root.glassOn ? "pause" : "play_arrow"
                    variant: "tonal"
                    enabled: !root.gone
                    onClicked: root.setGlass(!root.glassOn)
                }
            }

            StyledText {
                objectName: "errorInfo"
                width: parent.width
                visible: root.lastError !== ""
                text: Logic.capitalise(root.lastError)
                color: Theme.error
                font.pixelSize: Theme.fontSizeSmall
            }

            Row {
                width: parent.width
                spacing: Theme.spacingM

                CategoryRail {
                    id: rail
                    // above the content, so a narrow rail's name tips overlap it
                    z: 1
                    view: view
                }

                Item {
                    width: parent.width - rail.width - Theme.spacingM
                    height: Math.max(pages.implicitHeight, none.visible ? none.implicitHeight : 0)

                    NoResults {
                        id: none
                        width: parent.width
                        visible: view.filtering && !view.hasResults
                        query: view.query
                    }

                    // Every page is built once; the open one (or those with
                    // a match) shows
                    Column {
                        id: pages
                        width: parent.width

                        GlassPage {
                            view: view
                            host: root
                        }
                        AppsPage {
                            view: view
                            host: root
                        }
                        FadePage {
                            view: view
                            host: root
                        }
                        FallbackPage {
                            view: view
                            host: root
                        }
                        AdvancedPage {
                            view: view
                            host: root
                        }
                        AboutPage {
                            view: view
                            host: root
                        }
                    }
                }
            }
        }
    }
}
