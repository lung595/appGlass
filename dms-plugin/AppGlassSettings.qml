import QtQuick
import qs.Common
import qs.Services
import qs.Widgets
import qs.DCommon.Widgets
import qs.Modules.Plugins
import "components"
import "components/logic.js" as Logic

// The settings page: glass on/off, the status (the glass level is read
// only: it follows the DMS window rule opacity), unfocused windows, the
// fallback for apps appglass cannot glass, the app list, Re-apply. The
// setting widgets save into the plugin data (keys at the top of
// components/logic.js), which the daemon turns into `appglass sync`; what
// is shown about the apps comes from the daemon's shared status. This page
// runs no command itself.
PluginSettings {
    id: root
    pluginId: "appGlass"

    readonly property var service: root.pluginService || PluginService
    readonly property var vars: service.globalVars[Logic.PLUGIN_ID] || ({})
    readonly property var daemon: service.pluginDaemonInstances ? (service.pluginDaemonInstances[Logic.PLUGIN_ID] || null) : null
    readonly property var status: vars.status || null
    readonly property string lastError: vars.lastError || ""
    readonly property bool syncing: vars.syncing === true
    // The saved app switches, reloaded with the other settings
    property var apps: ({})

    function tr(text) {
        return I18n.trFor("appGlass", text);
    }

    function loadApps() {
        const a = root.service.loadPluginData(Logic.PLUGIN_ID, "apps", {});
        root.apps = a && typeof a === "object" ? a : {};
    }

    function setApp(key, on) {
        root.service.savePluginData(Logic.PLUGIN_ID, "apps", Logic.withApp(root.apps, key, on));
        root.loadApps();
    }

    function reapply() {
        if (root.daemon && root.daemon.requestSync)
            return root.daemon.requestSync("reapply", 0);
        ToastService.showWarning(root.tr("appGlass: the plugin daemon is not running"));
        return false;
    }

    Component.onCompleted: loadApps()
    onSettingChanged: loadApps()

    // --- glass on/off ---------------------------------------------------------

    ToggleSetting {
        id: glassToggle
        objectName: "glassToggle"
        settingKey: "glassEnabled"
        label: root.tr("Glass for desktop apps")
        description: root.tr("Off takes the glass out of every app again (the sync hook stays)")
        defaultValue: true
    }

    // --- status ---------------------------------------------------------------

    Column {
        width: parent.width
        spacing: Theme.spacingXS

        StyledText {
            id: levelInfo
            objectName: "levelInfo"
            width: parent.width
            text: root.tr(Logic.levelText(root.status))
            color: Theme.surfaceText
            font.pixelSize: Theme.fontSizeMedium
        }
        StyledText {
            width: parent.width
            text: root.tr("Change it with the DMS window opacity (the Glass window rule); text and icons stay opaque.")
            color: Theme.surfaceVariantText
            font.pixelSize: Theme.fontSizeSmall
        }
        StyledText {
            id: inactiveInfo
            objectName: "inactiveInfo"
            width: parent.width
            visible: text !== ""
            text: root.tr(Logic.inactiveText(root.status))
            color: Theme.surfaceVariantText
            font.pixelSize: Theme.fontSizeSmall
        }
        StyledText {
            id: summaryInfo
            objectName: "summaryInfo"
            width: parent.width
            visible: text !== ""
            text: Logic.summaryText(root.status)
            color: Theme.surfaceVariantText
            font.pixelSize: Theme.fontSizeSmall
        }
        StyledText {
            id: errorInfo
            objectName: "errorInfo"
            width: parent.width
            visible: root.lastError !== ""
            text: root.lastError
            color: Theme.error
            font.pixelSize: Theme.fontSizeSmall
        }
    }

    // --- unfocused windows ----------------------------------------------------

    ToggleSetting {
        id: inactiveToggle
        objectName: "inactiveToggle"
        settingKey: "inactiveEnabled"
        label: root.tr("Unfocused windows a little more transparent")
        description: root.tr("Only the background fades, with a short animation")
        defaultValue: true
    }

    SliderSetting {
        id: inactiveLevel
        objectName: "inactiveLevel"
        visible: inactiveToggle.value
        settingKey: "inactiveMorePct"
        label: root.tr("More transparent by")
        description: root.tr("Never below 60% opacity")
        defaultValue: Logic.DEFAULTS.inactiveMorePct
        minimum: 0
        maximum: 20
        unit: "%"
    }

    SliderSetting {
        id: inactiveDuration
        objectName: "inactiveDuration"
        visible: inactiveToggle.value
        settingKey: "inactiveDurationMs"
        label: root.tr("Animation")
        description: root.tr("0 ms: no animation")
        defaultValue: Logic.DEFAULTS.inactiveDurationMs
        minimum: 0
        maximum: 400
        unit: " ms"
    }

    SelectionSetting {
        id: inactiveEasing
        objectName: "inactiveEasing"
        visible: inactiveToggle.value
        settingKey: "inactiveEasing"
        label: root.tr("Animation curve")
        options: [
            {
                "label": root.tr("Ease out"),
                "value": "ease-out-cubic"
            },
            {
                "label": root.tr("Ease in and out"),
                "value": "ease-in-out"
            },
            {
                "label": root.tr("Linear"),
                "value": "linear"
            }
        ]
        defaultValue: Logic.DEFAULTS.inactiveEasing
    }

    ToggleSetting {
        id: instantFallback
        objectName: "instantFallback"
        visible: inactiveToggle.value
        settingKey: "inactiveInstantFallback"
        label: root.tr("Also dim apps without a fade")
        description: root.tr("A niri rule: instant, and the text dims too")
        defaultValue: false
    }

    // --- fallback -------------------------------------------------------------

    SelectionSetting {
        id: fallbackMode
        objectName: "fallbackMode"
        settingKey: "fallbackMode"
        label: root.tr("Apps appglass cannot glass")
        options: [
            {
                "label": root.tr("Opaque"),
                "value": "opaque"
            },
            {
                "label": root.tr("Translucent (text too)"),
                "value": "value"
            },
            {
                "label": root.tr("DMS opacity"),
                "value": "off"
            }
        ]
        defaultValue: Logic.DEFAULTS.fallbackMode
    }

    SliderSetting {
        id: fallbackValue
        objectName: "fallbackValue"
        visible: fallbackMode.value === "value"
        settingKey: "fallbackValuePct"
        label: root.tr("Their opacity")
        defaultValue: Logic.DEFAULTS.fallbackValuePct
        minimum: 50
        maximum: 100
        unit: "%"
    }

    // --- apps -----------------------------------------------------------------

    StyledText {
        width: parent.width
        text: root.tr("Apps")
        color: Theme.surfaceText
        font.pixelSize: Theme.fontSizeLarge
        font.weight: Theme.fontWeightMedium
    }

    AppList {
        id: appList
        objectName: "appList"
        width: parent.width
        status: root.status
        apps: root.apps
        onAppToggled: (key, on) => root.setApp(key, on)
    }

    // --- actions --------------------------------------------------------------

    DButton {
        id: reapplyButton
        objectName: "reapplyButton"
        text: root.syncing ? root.tr("Applying...") : root.tr("Re-apply")
        iconName: "refresh"
        enabled: !root.syncing
        onClicked: root.reapply()
    }
}
