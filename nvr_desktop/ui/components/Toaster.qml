import QtQuick
import QtQuick.Layouts
import App
import "../theme"

// Toast notifications at the bottom right (port of sonner). Listens to the Toasts singleton.
Column {
    id: toaster
    spacing: 8
    width: 360

    ListModel { id: toasts }

    Connections {
        target: Toasts
        function onToast(kind, message) {
            toasts.append({ kind: kind, message: message, stamp: Date.now() })
            if (toasts.count > 5)
                toasts.remove(0)
        }
    }

    Repeater {
        model: toasts
        delegate: Rectangle {
            id: toast
            required property int index
            required property string kind
            required property string message
            readonly property color tone: kind === "success" ? Theme.success : kind === "error" ? Theme.danger : Theme.info

            width: toaster.width
            implicitHeight: row.implicitHeight + 24
            radius: Theme.radius
            color: Theme.popover
            border.color: Theme.alpha(tone, 0.5)

            RowLayout {
                id: row
                anchors.fill: parent
                anchors.margins: 12
                spacing: 10
                Icon {
                    name: kind === "success" ? "circle-check-big" : kind === "error" ? "octagon-x" : "info"
                    color: toast.tone
                    size: 16
                    Layout.alignment: Qt.AlignTop
                }
                AppText {
                    text: message
                    wrapMode: Text.WordWrap
                    elide: Text.ElideNone
                    Layout.fillWidth: true
                }
            }
            Timer {
                interval: toast.kind === "error" ? 6000 : 3500
                running: true
                onTriggered: if (toast.index >= 0 && toast.index < toasts.count) toasts.remove(toast.index)
            }
            MouseArea {
                anchors.fill: parent
                onClicked: toasts.remove(toast.index)
            }
        }
    }
}
