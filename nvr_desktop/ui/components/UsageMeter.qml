import QtQuick
import QtQuick.Layouts
import "../theme"

// Label + value line, a usage bar, and an optional hint (port of UsageMeter in UsageBar.tsx).
ColumnLayout {
    property string label: ""
    property string value: ""
    property string hint: ""
    property var percent: null
    property real warnAt: 75
    property real dangerAt: 90

    spacing: 4

    RowLayout {
        Layout.fillWidth: true
        AppText { visible: label !== ""; text: label; variant: "small" }
        Item { Layout.fillWidth: true }
        AppText {
            text: value
            font.pixelSize: Theme.textXs
            font.weight: Font.Medium
        }
    }
    UsageBar {
        Layout.fillWidth: true
        percent: parent.percent
        warnAt: parent.warnAt
        dangerAt: parent.dangerAt
    }
    AppText {
        visible: hint !== ""
        text: hint
        variant: "small"
        font.pixelSize: 11
        Layout.fillWidth: true
    }
}
