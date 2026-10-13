import QtQuick
import QtQuick.Controls
import "../theme"

TextField {
    id: field
    property string iconName: "" // optional leading icon, e.g. "search"

    implicitHeight: 36
    leftPadding: iconName !== "" ? 32 : 12
    rightPadding: 12
    color: Theme.foreground
    placeholderTextColor: Theme.mutedForeground
    selectionColor: Theme.alpha(Theme.primary, 0.4)
    selectedTextColor: Theme.foreground
    font.family: Theme.font
    font.pixelSize: Theme.textSm
    opacity: enabled ? 1 : 0.5

    background: Rectangle {
        radius: Theme.radiusSm + 2
        color: Theme.alpha(Theme.input, 0.25)
        border.width: field.activeFocus ? 2 : 1
        border.color: field.activeFocus ? Theme.alpha(Theme.ring, 0.8) : Theme.input
    }

    Icon {
        visible: field.iconName !== ""
        name: field.iconName
        color: Theme.mutedForeground
        size: 16
        anchors.left: parent.left
        anchors.leftMargin: 10
        anchors.verticalCenter: parent.verticalCenter
    }
}
