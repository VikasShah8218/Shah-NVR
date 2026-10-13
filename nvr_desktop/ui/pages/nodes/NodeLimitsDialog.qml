import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Camera capacity + storage quota for a node (port of NodeLimitsDialog in NodeActions.tsx).
AppDialog {
    id: dialog

    property var node: ({})
    readonly property bool valid: Number.isInteger(Number(capacityField.text)) && Number(capacityField.text) >= 1
        && (unlimitedSwitch.checked || Number(quotaField.text) > 0)

    function openFor(n) {
        node = n
        capacityField.text = String(n.capacity_cameras ?? 100)
        unlimitedSwitch.checked = n.storage_quota_bytes === null || n.storage_quota_bytes === undefined
        quotaField.text = unlimitedSwitch.checked ? "100" : Nodes.quotaGb(n.storage_quota_bytes)
        open()
    }

    title: "Limits for " + (node.name ?? "")
    description: "The scheduler never assigns more cameras than the capacity. Above 95% of the storage quota the node deletes its oldest recordings until it is back under 90%."

    ColumnLayout {
        spacing: 6
        Layout.fillWidth: true
        AppText { text: "Camera capacity"; font.weight: Font.Medium }
        AppInput { id: capacityField; Layout.fillWidth: true; inputMethodHints: Qt.ImhDigitsOnly }
        AppText { text: "Currently assigned: " + (dialog.node.assigned_cameras ?? 0); variant: "small" }
    }

    ColumnLayout {
        spacing: 6
        Layout.fillWidth: true
        RowLayout {
            Layout.fillWidth: true
            AppText { text: "Storage quota (GB)"; font.weight: Font.Medium; Layout.fillWidth: true }
            AppSwitch { id: unlimitedSwitch }
            AppText { text: "Use whole disk"; variant: "small" }
        }
        AppInput { id: quotaField; Layout.fillWidth: true; enabled: !unlimitedSwitch.checked }
        AppText {
            text: "Recordings now " + Fmt.bytes(dialog.node.res?.recordings) + " · disk free "
                + Fmt.bytes(dialog.node.res?.diskFree) + " of " + Fmt.bytes(dialog.node.res?.diskTotal)
            variant: "small"
        }
    }

    footer: [
        Item { Layout.fillWidth: true },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: dialog.close() },
        AppButton {
            text: "Save limits"
            enabled: dialog.valid
            onClicked: {
                Nodes.updateLimits(dialog.node.id, Number(capacityField.text), unlimitedSwitch.checked ? null : Number(quotaField.text))
                dialog.close()
            }
        }
    ]
}
