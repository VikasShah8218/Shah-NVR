import QtQuick
import App
import "../theme"

// Pill with a coloured dot + label (port of StatusBadge.tsx). The dot pulses for RECORDING.
Rectangle {
    id: badge

    property string status: ""
    readonly property string tone: Status.tone(status)
    readonly property color toneColor: Theme.toneColor(tone)

    implicitHeight: 22
    implicitWidth: row.implicitWidth + 16
    radius: height / 2
    color: tone === "muted" ? Theme.muted : Theme.alpha(toneColor, 0.15)
    border.width: 1
    border.color: tone === "muted" ? Theme.border : Theme.alpha(toneColor, 0.35)

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
        Rectangle {
            width: 6
            height: 6
            radius: 3
            color: badge.toneColor
            anchors.verticalCenter: parent.verticalCenter
            SequentialAnimation on opacity {
                running: badge.status === "RECORDING"
                loops: Animation.Infinite
                NumberAnimation { to: 0.35; duration: 900 }
                NumberAnimation { to: 1; duration: 900 }
            }
        }
        Text {
            text: Status.label(badge.status)
            color: badge.toneColor
            font.family: Theme.font
            font.pixelSize: Theme.textXs
            font.weight: Font.Medium
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
