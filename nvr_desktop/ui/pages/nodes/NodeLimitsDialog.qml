import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Camera capacity of a node (port of NodeLimitsDialog in NodeActions.tsx). Storage caps are set per
// drive / network share in the node's Storage tab.
AppDialog {
    id: dialog

    property var node: ({})
    readonly property bool valid: Number.isInteger(Number(capacityField.text)) && Number(capacityField.text) >= 1

    function openFor(n) {
        node = n
        capacityField.text = String(n.capacity_cameras ?? 100)
        open()
    }

    title: "Limits for " + (node.name ?? "")
    description: "The scheduler never assigns more cameras than the capacity."

    ColumnLayout {
        spacing: 6
        Layout.fillWidth: true
        AppText { text: "Camera capacity"; font.weight: Font.Medium }
        AppInput { id: capacityField; Layout.fillWidth: true; inputMethodHints: Qt.ImhDigitsOnly }
        AppText { text: "Currently assigned: " + (dialog.node.assigned_cameras ?? 0); variant: "small" }
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: note.implicitHeight + 20
        radius: Theme.radius
        color: "transparent"
        border.color: Theme.border
        AppText {
            id: note
            anchors.fill: parent
            anchors.margins: 10
            text: "Storage caps are set per drive or network share: open the node and use the Storage tab. Recordings now "
                + Fmt.bytes(dialog.node.res?.recordings) + " on " + Math.max(1, (dialog.node.volumes ?? []).length) + " storage(s)."
            variant: "small"
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
        }
    }

    footer: [
        Item { Layout.fillWidth: true },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: dialog.close() },
        AppButton {
            text: "Save limits"
            enabled: dialog.valid
            onClicked: {
                Nodes.updateLimits(dialog.node.id, Number(capacityField.text))
                dialog.close()
            }
        }
    ]
}
