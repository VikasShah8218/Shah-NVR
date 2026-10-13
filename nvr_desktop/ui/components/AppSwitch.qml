import QtQuick
import QtQuick.Controls
import "../theme"

Switch {
    id: sw
    padding: 0
    spacing: 8
    font.family: Theme.font
    font.pixelSize: Theme.textSm
    // Without text the Basic style reports zero width; size from the indicator instead.
    implicitWidth: text ? contentItem.implicitWidth : indicator.implicitWidth
    implicitHeight: Math.max(indicator.implicitHeight, contentItem.implicitHeight)

    indicator: Rectangle {
        implicitWidth: 36
        implicitHeight: 20
        x: sw.leftPadding
        y: (sw.height - height) / 2
        radius: 10
        color: sw.checked ? Theme.primary : Theme.input
        opacity: sw.enabled ? 1 : 0.5
        Rectangle {
            width: 16
            height: 16
            radius: 8
            y: 2
            x: sw.checked ? parent.width - width - 2 : 2
            color: sw.checked ? Theme.primaryForeground : Theme.foreground
            Behavior on x { NumberAnimation { duration: 120 } }
        }
    }
    contentItem: Text {
        text: sw.text
        leftPadding: sw.text ? sw.indicator.width + sw.spacing : 0
        color: Theme.foreground
        font: sw.font
        verticalAlignment: Text.AlignVCenter
    }
}
