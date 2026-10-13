import QtQuick
import QtQuick.Layouts
import "../theme"

// Panel with border and rounded corners. Children go into a ColumnLayout (use Layout.fillWidth).
Rectangle {
    id: card

    property string title: ""
    property int padding: 16
    property int spacing: 10
    default property alias content: body.data
    property alias headerRight: headerRight.data

    color: Theme.card
    radius: Theme.radiusLg
    border.color: Theme.border
    border.width: 1
    implicitHeight: column.implicitHeight + padding * 2
    implicitWidth: column.implicitWidth + padding * 2

    ColumnLayout {
        id: column
        anchors.fill: parent
        anchors.margins: card.padding
        spacing: card.spacing

        RowLayout {
            visible: card.title !== "" || headerRight.children.length > 0
            Layout.fillWidth: true
            AppText {
                text: card.title
                font.weight: Font.Medium
                Layout.fillWidth: true
            }
            Row { id: headerRight; spacing: 6 }
        }

        ColumnLayout {
            id: body
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: card.spacing
        }
    }
}
