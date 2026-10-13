pragma Singleton
import QtQuick

// Dusk slate theme: the same tokens as nvr_client/src/index.css, so both clients look identical.
QtObject {
    // surfaces
    readonly property color background: "#2e3440"
    readonly property color foreground: "#eceff4"
    readonly property color card: "#3b4252"
    readonly property color popover: "#3b4252"
    readonly property color secondary: "#434c5e"
    readonly property color muted: "#353c4a"
    readonly property color mutedForeground: "#a9b1c2"
    readonly property color accent: "#434c5e"
    readonly property color border: "#4c566a"
    readonly property color input: "#4c566a"
    readonly property color video: "#1f232b"

    // brand / actions
    readonly property color primary: "#88c0d0"
    readonly property color primaryForeground: "#242933"
    readonly property color ring: "#88c0d0"

    // sidebar
    readonly property color sidebar: "#272c36"
    readonly property color sidebarForeground: "#d8dee9"
    readonly property color sidebarAccent: "#3b4252"

    // status
    readonly property color success: "#a3be8c"
    readonly property color warning: "#ebcb8b"
    readonly property color info: "#88c0d0"
    readonly property color danger: "#bf616a"

    // charts
    readonly property var chart: ["#88c0d0", "#a3be8c", "#ebcb8b", "#b48ead", "#d08770"]

    // shape & type
    readonly property int radius: 10
    readonly property int radiusSm: 6
    readonly property int radiusLg: 14
    readonly property string font: "Geist"
    readonly property string mono: "Geist Mono"
    readonly property int textXs: 12
    readonly property int textSm: 13
    readonly property int textBase: 14
    readonly property int textLg: 16
    readonly property int textXl: 20

    // spacing
    readonly property int gap: 12
    readonly property int pagePadding: 20

    function toneColor(tone) {
        switch (tone) {
        case "success": return success
        case "info": return info
        case "warning": return warning
        case "danger": return danger
        default: return mutedForeground
        }
    }

    // "#rrggbb" + alpha -> color, for tinted backgrounds (bg-success/15 in the web client)
    function alpha(c, a) {
        return Qt.rgba(c.r, c.g, c.b, a)
    }
}
