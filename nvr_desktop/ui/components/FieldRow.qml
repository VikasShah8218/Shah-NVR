import QtQuick
import QtQuick.Layouts
import "../theme"

// "Label ........ value" row used in detail cards (port of Field in common.tsx).
RowLayout {
    property string label: ""
    property string value: ""
    property color valueColor: Theme.foreground
    default property alias custom: customSlot.data

    Layout.fillWidth: true
    spacing: 16
    AppText { text: label; variant: "muted" }
    Item { Layout.fillWidth: true }
    AppText {
        visible: customSlot.children.length === 0
        text: value
        color: valueColor
        horizontalAlignment: Text.AlignRight
        Layout.maximumWidth: 260
    }
    Row { id: customSlot; spacing: 6; visible: children.length > 0 }
}
