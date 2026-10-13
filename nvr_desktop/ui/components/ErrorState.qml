import QtQuick
import QtQuick.Layouts
import "../theme"

// Red notice with the error message (port of ErrorState in common.tsx). Hidden when `text` is empty.
Rectangle {
    id: root
    property string text: ""

    visible: text !== ""
    Layout.fillWidth: true
    implicitHeight: row.implicitHeight + 24
    radius: Theme.radius
    color: Theme.alpha(Theme.danger, 0.1)
    border.color: Theme.alpha(Theme.danger, 0.4)

    RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8
        Icon { name: "triangle-alert"; color: Theme.danger; size: 16; Layout.alignment: Qt.AlignTop }
        AppText {
            text: root.text
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
            Layout.fillWidth: true
        }
    }
}
