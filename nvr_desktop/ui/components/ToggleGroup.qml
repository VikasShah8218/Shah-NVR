import QtQuick
import "../theme"

// Single-choice segmented buttons (port of shadcn ToggleGroup, outline variant).
// options: [{value, label}] or strings. The selected option gets the primary tint.
Row {
    id: group

    property var options: []
    property var value
    property string size: "sm"
    signal picked(var value)

    spacing: -1

    Repeater {
        model: group.options
        delegate: Rectangle {
            required property var modelData
            readonly property var itemValue: typeof modelData === "object" ? modelData.value : modelData
            readonly property bool selected: itemValue === group.value

            implicitHeight: group.size === "sm" ? 30 : 36
            implicitWidth: Math.max(implicitHeight, label.implicitWidth + 24)
            color: selected ? Theme.alpha(Theme.primary, 0.2) : area.containsMouse ? Theme.accent : "transparent"
            border.color: Theme.border
            radius: Theme.radiusSm
            z: selected ? 1 : 0

            Text {
                id: label
                anchors.centerIn: parent
                text: typeof modelData === "object" ? modelData.label : String(modelData)
                color: selected ? Theme.primary : Theme.foreground
                font.family: Theme.font
                font.pixelSize: Theme.textSm
                font.weight: Font.Medium
            }
            MouseArea {
                id: area
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    group.value = itemValue
                    group.picked(itemValue)
                }
            }
        }
    }
}
