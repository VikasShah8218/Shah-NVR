import QtQuick
import QtQuick.Controls
import "../theme"

// Compact checkbox matching the web client's form controls.
CheckBox {
    id: control

    padding: 0
    spacing: 8
    hoverEnabled: true
    opacity: enabled ? 1 : 0.5
    font.family: Theme.font
    font.pixelSize: Theme.textSm
    implicitWidth: contentItem.implicitWidth
    implicitHeight: Math.max(indicator.implicitHeight, contentItem.implicitHeight)

    indicator: Rectangle {
        implicitWidth: 16
        implicitHeight: 16
        x: control.leftPadding
        y: (control.height - height) / 2
        radius: 3
        color: control.checked ? Theme.primary : "transparent"
        border.width: 1
        border.color: control.checked ? Theme.primary
            : control.hovered ? Theme.mutedForeground : Theme.border

        Text {
            anchors.centerIn: parent
            visible: control.checked
            text: "✓"
            color: Theme.primaryForeground
            font.family: Theme.font
            font.pixelSize: 13
            font.weight: Font.Bold
        }
    }

    contentItem: Text {
        text: control.text
        leftPadding: control.indicator.width + control.spacing
        color: Theme.foreground
        font: control.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
