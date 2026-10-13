import QtQuick
import QtQuick.Layouts
import "../theme"

// One table row: hover highlight, bottom border, optional click. Children are laid out in a RowLayout;
// give each cell the same Layout.preferredWidth as its TableHeader column (or Layout.fillWidth).
Rectangle {
    id: rowFrame

    default property alias cells: cellRow.data
    property bool clickable: false
    property int sidePadding: 16
    property int verticalPadding: 10
    signal clicked()

    Layout.fillWidth: true
    implicitHeight: cellRow.implicitHeight + verticalPadding * 2
    color: hover.hovered ? Theme.alpha(Theme.accent, 0.45) : "transparent"

    HoverHandler { id: hover }
    // Sits behind the cells: buttons, switches and links inside a row take their own clicks first.
    MouseArea {
        anchors.fill: parent
        enabled: rowFrame.clickable
        cursorShape: Qt.PointingHandCursor
        onClicked: rowFrame.clicked()
    }

    RowLayout {
        id: cellRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: rowFrame.sidePadding
        anchors.rightMargin: rowFrame.sidePadding
        spacing: 12
    }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.alpha(Theme.border, 0.7) }
}
