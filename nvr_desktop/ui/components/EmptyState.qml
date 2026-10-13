import QtQuick
import QtQuick.Layouts
import "../theme"

// Dashed box with an icon, a title and a hint (port of EmptyState in common.tsx).
Rectangle {
    id: root
    property string iconName: "inbox"
    property string title: ""
    property string text: ""

    Layout.fillWidth: true
    implicitHeight: column.implicitHeight + 48
    radius: Theme.radius
    color: "transparent"
    border.color: Theme.border

    ColumnLayout {
        id: column
        anchors.centerIn: parent
        width: Math.min(parent.width - 32, 460)
        spacing: 6
        Icon { name: iconName; size: 32; color: Theme.mutedForeground; Layout.alignment: Qt.AlignHCenter }
        AppText { text: title; font.weight: Font.Medium; Layout.alignment: Qt.AlignHCenter }
        AppText {
            visible: root.text !== ""
            text: root.text
            variant: "muted"
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }
    }
}
