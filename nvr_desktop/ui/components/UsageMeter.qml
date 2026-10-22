import QtQuick
import QtQuick.Layouts
import "../theme"

// Label + value line, a usage bar, and an optional hint (port of UsageMeter in UsageBar.tsx).
ColumnLayout {
    id: root

    property string label: ""
    property string value: ""
    property string hint: ""
    property var percent: null
    property real warnAt: 75
    property real dangerAt: 90
    property bool alignValueLeft: false

    spacing: 4

    RowLayout {
        Layout.fillWidth: true
        AppText { visible: label !== ""; text: label; variant: "small" }
        Item {
            visible: !root.alignValueLeft
            Layout.fillWidth: !root.alignValueLeft
        }
        AppText {
            text: value
            font.pixelSize: Theme.textXs
            font.weight: Font.Medium
            Layout.fillWidth: root.alignValueLeft
            horizontalAlignment: root.alignValueLeft ? Text.AlignLeft : Text.AlignRight
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
