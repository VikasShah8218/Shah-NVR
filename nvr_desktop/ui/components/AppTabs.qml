import QtQuick
import "../theme"

// Tab list like the web client's shadcn Tabs: muted track, the active tab raised.
// options: [{value, label}]. Bind `current`; `picked(value)` fires on click.
Rectangle {
    id: tabs

    property var options: []
    property string current: ""
    signal picked(string value)

    implicitHeight: 36
    implicitWidth: row.implicitWidth + 6
    radius: Theme.radius
    color: Theme.muted

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 2
        Repeater {
            model: tabs.options
            delegate: Rectangle {
                required property var modelData
                readonly property bool active: modelData.value === tabs.current
                implicitHeight: 30
                implicitWidth: label.implicitWidth + 24
                radius: Theme.radiusSm + 2
                color: active ? Theme.card : "transparent"
                border.color: active ? Theme.border : "transparent"
                Text {
                    id: label
                    anchors.centerIn: parent
                    text: modelData.label
                    color: active ? Theme.foreground : Theme.mutedForeground
                    font.family: Theme.font
                    font.pixelSize: Theme.textSm
                    font.weight: Font.Medium
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        tabs.current = modelData.value
                        tabs.picked(modelData.value)
                    }
                }
            }
        }
    }
}
