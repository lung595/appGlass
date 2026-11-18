import QtQuick
import qs.Common
import qs.Widgets
import qs.DCommon.Widgets

// Advanced: the CLI's learn, adopt, report and uninstall, run by the daemon.
// Adopt and Uninstall ask first; one action runs at a time. A question
// left open is dropped as soon as the page changes (another category, a
// search), so it never waits armed for a later visit.
CategoryPage {
    id: page

    // "adopt" | "uninstall" | "" : the question open
    property string asking: ""
    readonly property bool idle: page.host.action === ""

    category: "advanced"

    Connections {
        target: page.view
        function onCurrentChanged() {
            page.asking = "";
        }
        function onQueryChanged() {
            page.asking = "";
        }
    }

    function run(name) {
        page.asking = "";
        page.host.runAction(name);
    }

    ActionRow {
        view: page.view
        key: "learnButton"
        buttonText: page.host.action === "learn" ? "Learning..." : "Learn"
        iconName: "travel_explore"
        busy: page.host.action === "learn"
        available: page.idle && !page.host.gone
        onClicked: page.run("learn")
    }

    ActionRow {
        view: page.view
        key: "adoptButton"
        buttonText: page.host.action === "adopt" ? "Adopting..." : "Adopt"
        iconName: "move_to_inbox"
        busy: page.host.action === "adopt"
        available: page.idle && !page.host.gone
        onClicked: page.asking = "adopt"
    }
    ConfirmSheet {
        objectName: "confirmAdopt"
        open: page.asking === "adopt"
        title: "Adopt the hand-made glass files?"
        text: "appglass backs up each one, then writes and keeps them itself. Uninstall puts the originals back."
        risk: page.host.conflicts.length ? page.host.conflicts.length + " file(s) in the way: " + page.host.conflicts.join(", ") : ""
        confirmText: "Adopt"
        onConfirmed: page.run("adopt")
        onCancelled: page.asking = ""
    }

    ActionRow {
        view: page.view
        key: "reportButton"
        buttonText: "Copy report"
        iconName: "content_copy"
        onClicked: page.host.copyReport()
    }

    ActionRow {
        view: page.view
        key: "uninstallButton"
        buttonText: page.host.action === "uninstall" ? "Uninstalling..." : "Uninstall"
        iconName: "delete_forever"
        danger: true
        busy: page.host.action === "uninstall"
        // once the files are back, never again (the link may stay: below)
        // (again, after a reload cut it short)
        available: page.idle && (page.host.uninstallState === "" || page.host.uninstallState === "interrupted")
        onClicked: page.asking = "uninstall"
    }
    StyledText {
        objectName: "uninstallErrorInfo"
        width: parent.width
        visible: page.view.shown("uninstallButton") && page.host.uninstallError !== ""
        text: page.host.uninstallError
        color: Theme.error
        font.pixelSize: Theme.fontSizeSmall
        wrapMode: Text.WordWrap
    }
    StyledText {
        objectName: "uninstallLinkHint"
        width: parent.width
        visible: page.host.uninstallState === "linkStays"
        text: "Every file is restored, but this plugin's link stays: run 'appglass plugin remove' in a terminal to finish."
        color: Theme.error
        font.pixelSize: Theme.fontSizeSmall
        wrapMode: Text.WordWrap
    }
    // Uninstalled: only the user's own click brings the glass back (the
    // daemon syncs the stored settings, `appglass get` filling only what
    // was never stored)
    DButton {
        objectName: "reinstallButton"
        visible: page.view.shown("uninstallButton") && page.host.gone
        text: "Set up again"
        iconName: "restart_alt"
        variant: "tonal"
        enabled: page.idle
        onClicked: page.host.reinstall()
    }
    ConfirmSheet {
        objectName: "confirmUninstall"
        open: page.asking === "uninstall"
        danger: true
        title: "Uninstall appGlass?"
        text: "Every file appglass wrote or changed is put back byte for byte, its sync hook goes, then this plugin's link. Your other DMS plugins are not touched."
        confirmText: "Uninstall"
        onConfirmed: page.run("uninstall")
        onCancelled: page.asking = ""
    }
}
