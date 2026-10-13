import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

// Centered modal dialog (port of shadcn Dialog / AlertDialog): title, description, body, footer buttons.
Popup {
    id: dialog

    property string title: ""
    property string description: ""
    default property alias content: body.data
    property alias footer: footerRow.data

    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(480, parent ? parent.width - 40 : 480)
    modal: true
    dim: true
    padding: 24
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.45) }

    background: Rectangle {
        color: Theme.popover
        radius: Theme.radiusLg
        border.color: Theme.border
    }

    contentItem: ColumnLayout {
        spacing: 14
        ColumnLayout {
            spacing: 6
            Layout.fillWidth: true
            AppText { text: dialog.title; variant: "heading"; font.weight: Font.DemiBold; Layout.fillWidth: true }
            AppText {
                visible: dialog.description !== ""
                text: dialog.description
                variant: "muted"
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                Layout.fillWidth: true
            }
        }
        ColumnLayout {
            id: body
            spacing: 12
            Layout.fillWidth: true
        }
        RowLayout { // dialogs put a filler Item first so buttons sit on the right
            id: footerRow
            spacing: 8
            Layout.fillWidth: true
        }
    }
}
