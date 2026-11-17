import QtQuick
import qs.Common
import qs.Modules.Plugins
import "../logic.js" as Logic

// Fallback: what the apps appglass cannot glass look like
CategoryPage {
    id: page

    category: "fallback"

    SelectionSetting {
        id: mode
        objectName: "fallbackMode"
        visible: page.view.shown("fallbackMode")
        settingKey: "fallbackMode"
        label: page.view.label("fallbackMode")
        description: page.view.help("fallbackMode")
        options: [
            {
                "label": "Opaque",
                "value": "opaque"
            },
            {
                "label": "Translucent (text too)",
                "value": "value"
            },
            {
                "label": "DMS opacity",
                "value": "off"
            }
        ]
        defaultValue: Logic.DEFAULTS.fallbackMode
    }

    SliderSetting {
        id: fallbackValue
        objectName: "fallbackValue"
        visible: page.view.shown("fallbackValue") && (page.view.filtering || mode.value === "value")
        settingKey: "fallbackValuePct"
        // the DMS slider shows its value only while dragged: the label has it
        label: page.view.label("fallbackValue") + ": " + fallbackValue.value + fallbackValue.unit
        description: page.view.help("fallbackValue")
        defaultValue: Logic.DEFAULTS.fallbackValuePct
        minimum: 50
        maximum: 100
        unit: "%"
    }
}
