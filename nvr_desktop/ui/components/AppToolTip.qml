import QtQuick
import QtQuick.Controls
import "../theme"

ToolTip {
    id: tip
    delay: 400
    padding: 6
    contentItem: Text {
        text: tip.text
        color: Theme.foreground
        font.family: Theme.font
        font.pixelSize: Theme.textXs
    }
    background: Rectangle {
        color: Theme.popover
        radius: Theme.radiusSm
        border.color: Theme.border
    }
}
