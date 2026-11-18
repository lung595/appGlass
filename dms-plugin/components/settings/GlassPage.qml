import QtQuick
import qs.Common
import qs.Widgets
import qs.DCommon.Widgets
import qs.Modules.Plugins
import "../logic.js" as Logic

// Glass: the master switch, the level (read only: it follows the DMS window
// rule opacity, unless appglass's own settings hold one: then Follow the DMS
// rule clears it), how many apps are on glass, Re-apply
CategoryPage {
    id: page

    category: "glass"

    ToggleSetting {
        objectName: "glassToggle"
        visible: page.view.shown("glassToggle")
        settingKey: "glassEnabled"
        enabled: !page.host.gone
        label: page.view.label("glassToggle")
        description: page.view.help("glassToggle")
        defaultValue: true
    }

    Column {
        width: parent.width
        spacing: 2
        visible: page.view.shown("levelInfo")

        StyledText {
            objectName: "levelInfo"
            width: parent.width
            text: Logic.levelText(page.host.status, page.host.savedLevels)
            color: Theme.surfaceText
            font.pixelSize: Theme.fontSizeMedium
        }
        StyledText {
            width: parent.width
            text: page.view.help("levelInfo")
            color: Theme.surfaceVariantText
            font.pixelSize: Theme.fontSizeSmall
        }
        StyledText {
            objectName: "inactiveInfo"
            width: parent.width
            visible: text !== ""
            text: Logic.inactiveText(page.host.status)
            color: Theme.surfaceVariantText
            font.pixelSize: Theme.fontSizeSmall
        }
    }

    ActionRow {
        view: page.view
        key: "followDmsButton"
        visible: page.view.shown("followDmsButton") && page.host.ownLevels
        buttonText: "Follow the DMS rule"
        iconName: "sync"
        available: !page.host.gone
        onClicked: page.host.followDms()
    }

    StyledText {
        objectName: "summaryInfo"
        width: parent.width
        visible: page.view.shown("summaryInfo") && text !== ""
        text: page.host.status ? page.view.label("summaryInfo") + ": " + Logic.summaryText(page.host.status) : ""
        color: Theme.surfaceVariantText
        font.pixelSize: Theme.fontSizeSmall
    }

    ActionRow {
        view: page.view
        key: "reapplyButton"
        buttonText: page.host.syncing ? "Applying..." : "Re-apply"
        iconName: "refresh"
        busy: page.host.syncing
        available: !page.host.syncing && !page.host.gone
        onClicked: page.host.reapply()
    }
}
