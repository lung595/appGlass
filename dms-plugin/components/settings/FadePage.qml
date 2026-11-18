import QtQuick
import qs.Common
import qs.Modules.Plugins
import "../logic.js" as Logic

// Fade: unfocused windows a little more transparent, how much, how fast
CategoryPage {
    id: page

    category: "fade"
    // uninstalled: nothing here is synced
    enabled: !page.host.gone

    // The fade's own settings show while it is on (a search shows them all)
    function shownIf(id) {
        return page.view.shown(id) && (page.view.filtering || fadeToggle.value);
    }

    ToggleSetting {
        id: fadeToggle
        objectName: "inactiveToggle"
        visible: page.view.shown("inactiveToggle")
        settingKey: "inactiveEnabled"
        label: page.view.label("inactiveToggle")
        description: page.view.help("inactiveToggle")
        defaultValue: true
    }

    SliderSetting {
        id: inactiveLevel
        objectName: "inactiveLevel"
        visible: page.shownIf("inactiveLevel")
        settingKey: "inactiveMorePct"
        // the DMS slider shows its value only while dragged: the label has it
        label: page.view.label("inactiveLevel") + ": " + inactiveLevel.value + inactiveLevel.unit
        description: page.view.help("inactiveLevel")
        defaultValue: Logic.DEFAULTS.inactiveMorePct
        minimum: 0
        maximum: 20
        unit: "%"
    }

    SliderSetting {
        id: inactiveDuration
        objectName: "inactiveDuration"
        visible: page.shownIf("inactiveDuration")
        settingKey: "inactiveDurationMs"
        // the DMS slider shows its value only while dragged: the label has it
        label: page.view.label("inactiveDuration") + ": " + inactiveDuration.value + inactiveDuration.unit
        description: page.view.help("inactiveDuration")
        defaultValue: Logic.DEFAULTS.inactiveDurationMs
        minimum: 0
        maximum: 400
        unit: " ms"
    }

    SelectionSetting {
        objectName: "inactiveEasing"
        visible: page.shownIf("inactiveEasing")
        settingKey: "inactiveEasing"
        label: page.view.label("inactiveEasing")
        description: page.view.help("inactiveEasing")
        options: [
            {
                "label": "Ease out",
                "value": "ease-out-cubic"
            },
            {
                "label": "Ease in and out",
                "value": "ease-in-out"
            },
            {
                "label": "Linear",
                "value": "linear"
            }
        ]
        defaultValue: Logic.DEFAULTS.inactiveEasing
    }

    ToggleSetting {
        objectName: "instantFallback"
        visible: page.shownIf("instantFallback")
        settingKey: "inactiveInstantFallback"
        label: page.view.label("instantFallback")
        description: page.view.help("instantFallback")
        defaultValue: false
    }
}
