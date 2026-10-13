import QtQuick
import QtQuick.Layouts
import "../theme"

// Header row of a table. columns: [{title, width}] - width in px, or 0 for "fill remaining space".
// Rows use the same widths (see TableRow.qml) so columns line up.
Rectangle {
    property var columns: []
    property int sidePadding: 16

    Layout.fillWidth: true
    implicitHeight: 40
    color: "transparent"

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: sidePadding
        anchors.rightMargin: sidePadding
        spacing: 12
        Repeater {
            model: columns
            delegate: AppText {
                required property var modelData
                text: modelData.title
                font.weight: Font.Medium
                color: Theme.foreground
                Layout.preferredWidth: modelData.width > 0 ? modelData.width : -1
                Layout.fillWidth: !(modelData.width > 0)
            }
        }
    }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
}
