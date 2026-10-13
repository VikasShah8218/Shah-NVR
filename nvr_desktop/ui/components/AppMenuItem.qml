import QtQuick
import QtQuick.Controls
import "../theme"

MenuItem {
    id: item
    property string iconName: ""
    property bool danger: false
    // Option lists: radio items show a check when `marked` (bound by the caller; never toggles itself).
    property bool radio: false
    property bool marked: false

    implicitHeight: visible ? 32 : 0
    hoverEnabled: true
    opacity: enabled ? 1 : 0.45

    contentItem: Row {
        spacing: 8
        leftPadding: 4
        Icon {
            visible: item.iconName !== "" || item.radio
            name: item.radio ? (item.marked ? "check" : "") : item.iconName
            size: 15
            color: item.danger ? Theme.danger : Theme.foreground
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: item.text
            color: item.danger ? Theme.danger : Theme.foreground
            font.family: Theme.font
            font.pixelSize: Theme.textSm
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    indicator: Item {}
    background: Rectangle {
        radius: Theme.radiusSm
        color: item.highlighted ? Theme.accent : "transparent"
    }
}
