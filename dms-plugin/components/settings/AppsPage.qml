import QtQuick
import qs.Common
import qs.Widgets

// Apps: every app of the last status with its status, route and switch
CategoryPage {
    id: page

    category: "apps"

    StyledText {
        width: parent.width
        visible: !page.view.filtering
        text: page.view.help("appList") + ". Mod and Forced routes ask before they turn on."
        color: Theme.surfaceVariantText
        font.pixelSize: Theme.fontSizeSmall
    }

    AppList {
        objectName: "appList"
        width: parent.width
        view: page.view
        host: page.host
    }
}
