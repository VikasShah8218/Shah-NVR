import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

// Side drawer from the right (port of shadcn Sheet): title, description, scrollable body, footer.
Drawer {
    id: sheet

    property string title: ""
    property string description: ""
    default property alias content: body.data
    property alias footer: footerRow.data

    parent: Overlay.overlay // cover the whole window, not just the page
    edge: Qt.RightEdge
    width: Math.min(parent ? parent.width * 0.9 : 640, 600)
    height: parent ? parent.height : 800
    modal: true
    dim: true
    interactive: false
    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.45) }

    background: Rectangle {
        color: Theme.popover
        Rectangle { width: 1; height: parent.height; color: Theme.border }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 20
            spacing: 8
            ColumnLayout {
                spacing: 4
                Layout.fillWidth: true
                AppText { text: sheet.title; variant: "heading"; font.weight: Font.DemiBold; Layout.fillWidth: true }
                AppText {
                    text: sheet.description
                    variant: "muted"
                    wrapMode: Text.WordWrap
                    elide: Text.ElideNone
                    Layout.fillWidth: true
                }
            }
            AppButton { variant: "ghost"; size: "icon"; iconName: "x"; onClicked: sheet.close(); Layout.alignment: Qt.AlignTop }
        }

        ScrollView {
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ScrollBar.vertical: AppScrollBar {}
            ColumnLayout {
                id: body
                x: 20
                width: scroll.availableWidth - 40
                spacing: 14
            }
        }

        RowLayout {
            id: footerRow
            Layout.fillWidth: true
            Layout.margins: 20
            spacing: 8
        }
    }
}
