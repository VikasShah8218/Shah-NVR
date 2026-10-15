import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Change one storage volume's cap (port of EditCapDialog in StorageTab.tsx).
AppDialog {
    id: dialog

    property var volume: ({})

    function openFor(v) {
        volume = v
        capInput.reset(v.quota_bytes)
        open()
    }

    title: volume.kind === "network" ? "Cap for network share" : "Cap for folder"
    description: volume.path ?? ""

    CapField { id: capInput }
    AppText {
        text: "Recordings here now: " + Fmt.bytes(dialog.volume.recordings_bytes) + " · disk free "
            + Fmt.bytes(dialog.volume.free_bytes) + " of " + Fmt.bytes(dialog.volume.total_bytes)
            + ". A cap below the current size removes the oldest recordings here."
        variant: "small"
        wrapMode: Text.WordWrap
        elide: Text.ElideNone
        Layout.fillWidth: true
    }

    footer: [
        Item { Layout.fillWidth: true },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: dialog.close() },
        AppButton {
            text: "Save cap"
            enabled: capInput.valid
            onClicked: {
                NodeDetail.updateVolumeCap(dialog.volume.id, capInput.value)
                dialog.close()
            }
        }
    ]
}
