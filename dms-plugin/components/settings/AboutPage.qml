import QtQuick
import qs.Common
import qs.Widgets
import "../logic.js" as Logic

// About: the version, what appGlass never touches, the command line
CategoryPage {
    id: page

    category: "about"

    InfoRow {
        view: page.view
        key: "versionInfo"
        text: "appGlass " + Logic.VERSION + ", " + page.view.help("versionInfo")
    }
    InfoRow {
        view: page.view
        key: "neverInfo"
        text: "Games, the windows DMS and Quickshell draw themselves, and the browsers browserGlass owns (shown as Delegated). It only writes under your home folder, never needs root, and backs up every file it changes; Uninstall puts each one back."
    }
    InfoRow {
        view: page.view
        key: "cliInfo"
        text: "appglass status, appglass learn, appglass adopt and appglass remove do the same from a terminal; dms ipc call appGlass pause | resume | sync | status from a key binding."
    }
}
