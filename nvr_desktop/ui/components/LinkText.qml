import QtQuick
import "../theme"

// Clickable text (a router link inside a table cell). Takes the click itself, so a clickable row
// underneath does not also react.
AppText {
    id: link
    property bool active: true
    readonly property alias hovered: area.containsMouse
    signal activated()

    color: active && hovered ? Theme.primary : Theme.foreground

    MouseArea {
        id: area
        anchors.fill: parent
        enabled: link.active
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: link.activated()
    }
}
