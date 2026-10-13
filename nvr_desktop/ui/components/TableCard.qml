import QtQuick
import QtQuick.Layouts
import "../theme"

// Card with a TableHeader and one row per item. rows: JS array or model; rowDelegate: a Component
// whose root is a TableRow with `required property var modelData`.
Rectangle {
    id: card

    property var columns: []
    property var rows: []
    property Component rowDelegate

    Layout.fillWidth: true
    implicitHeight: column.implicitHeight
    radius: Theme.radiusLg
    color: Theme.card
    border.color: Theme.border
    clip: true

    ColumnLayout {
        id: column
        width: parent.width
        spacing: 0
        TableHeader { columns: card.columns }
        Repeater {
            model: card.rows
            delegate: card.rowDelegate
        }
    }
}
