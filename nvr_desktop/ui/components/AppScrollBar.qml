import QtQuick
import QtQuick.Controls
import "../theme"

ScrollBar {
    id: bar
    implicitWidth: 8
    implicitHeight: 8
    contentItem: Rectangle {
        radius: 4
        color: bar.pressed ? Theme.mutedForeground : Theme.border
        opacity: bar.active ? 1 : 0.6
    }
}
