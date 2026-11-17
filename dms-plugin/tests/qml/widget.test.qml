import QtQuick
import Quickshell
import qs.Common
import qs.Services
import "components/logic.js" as Logic

// AppGlassWidget.qml, the bar pill: on/off and how many apps are on glass,
// a click opens the plugin's settings, a right click pauses or resumes. It
// runs no command: the daemon syncs what it saves.
Item {
    id: root

    Harness {
        id: t
    }

    property var status: ({})
    property var w: null
    property var pill: null
    property var vpill: null

    Component {
        id: widgetComponent
        AppGlassWidget {
            pluginId: "appGlass"
            pluginService: PluginService
        }
    }

    function fresh(vars, data) {
        if (root.w)
            root.w.destroy();
        Proc.reset();
        Quickshell.reset();
        PopoutService.reset();
        PluginService.reset();
        SettingsData.reset();
        SettingsData.pluginSettings = {
            "appGlass": Object.assign({
                "seeded": true
            }, data || {})
        };
        PluginService.globalVars = {
            "appGlass": vars
        };
        root.w = widgetComponent.createObject(root);
        root.pill = root.w.horizontalBarPill.createObject(root);
        root.vpill = root.w.verticalBarPill.createObject(root);
    }

    function find(item, name) {
        if (!item)
            return null;
        if (item.objectName === name)
            return item;
        for (const kid of item.children || []) {
            const hit = find(kid, name);
            if (hit)
                return hit;
        }
        return null;
    }

    Component.onCompleted: {
        root.status = JSON.parse(t.readFile("contract/status.json"));
        t.steps([
            {
                "run": () => {
                    root.fresh({
                        "status": root.status
                    }, {});
                    t.check("on: the count of apps on glass", [root.find(root.pill, "pillText").text, root.find(root.pill, "pillIcon").name], ["7", "blur_on"]);
                    t.check("vertical pill too", root.find(root.vpill, "pillText").text, "7");
                    // a click opens the settings
                    root.w.triggerPopout();
                    t.check("click opens the plugin settings", PopoutService.opened, ["plugin:appGlass"]);
                    // a right click pauses
                    root.w.pillRightClickAction();
                    t.check("right click pauses", SettingsData.getPluginSetting("appGlass", "glassEnabled", undefined), false);
                    t.check("paused pill", [root.find(root.pill, "pillText").text, root.find(root.pill, "pillIcon").name], ["off", "blur_off"]);
                    root.w.pillRightClickAction();
                    t.check("and resumes", [SettingsData.getPluginSetting("appGlass", "glassEnabled", undefined), root.find(root.pill, "pillText").text], [true, "7"]);
                    t.check("the pill runs nothing", [Proc.calls, Quickshell.detached], [[], []]);
                    root.fresh({}, {
                        "glassEnabled": true
                    });
                }
            },
            {
                "run": () => {
                    t.check("before a status: the icon only", [root.find(root.pill, "pillText").visible, root.find(root.pill, "pillIcon").name], [false, "blur_on"]);
                }
            }
        ]);
    }
}
