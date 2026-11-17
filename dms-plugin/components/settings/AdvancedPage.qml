import QtQuick
import qs.Common
import qs.Widgets

// Advanced: the CLI's learn, adopt, report and uninstall, run by the daemon.
// Adopt and Uninstall ask first; one action runs at a time.
CategoryPage {
    id: page

    // "adopt" | "uninstall" | "" : the question open
    property string asking: ""
    readonly property bool idle: page.host.action === ""

    category: "advanced"

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
        available: page.idle
        onClicked: page.run("learn")
    }

    ActionRow {
        view: page.view
        key: "adoptButton"
        buttonText: page.host.action === "adopt" ? "Adopting..." : "Adopt"
        iconName: "move_to_inbox"
        busy: page.host.action === "adopt"
        available: page.idle
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
        available: page.idle
        onClicked: page.asking = "uninstall"
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
