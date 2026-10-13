import QtQuick
import QtQuick.Layouts
import "../theme"

// Page title + description on the left, action controls on the right.
RowLayout {
    property string title: ""
    property string description: ""
    default property alias actions: actionsRow.data

    Layout.fillWidth: true
    spacing: 12

    ColumnLayout {
        spacing: 2
        Layout.fillWidth: true
        AppText { text: title; variant: "title"; Layout.fillWidth: true }
        AppText { visible: description !== ""; text: description; variant: "muted"; Layout.fillWidth: true }
    }
    Row {
        id: actionsRow
        spacing: 8
        Layout.alignment: Qt.AlignBottom
    }
}
