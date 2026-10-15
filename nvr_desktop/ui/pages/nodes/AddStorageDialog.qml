import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Add a drive folder or a network share to a node (port of AddStorageDialog in StorageTab.tsx).
// Network share credentials are never sent to central: they are saved once on the node PC (cmdkey).
AppDialog {
    id: dialog

    property var node: ({})
    property string kind: "local" // local | network
    readonly property var drives: node.metrics?.drives ?? []
    readonly property string path: (kind === "local" ? localField.text : uncField.text).trim()
    readonly property bool duplicate: (node.volumes ?? []).some(v => v.path.toLowerCase() === path.toLowerCase())
    readonly property bool valid: path.length > 3 && !duplicate
        && capInput.valid
        && (kind === "local" ? /^[A-Za-z]:[\\\/]/.test(path) : /^\\\\[^\\\/]+\\[^\\\/]+/.test(path))
    readonly property string shareHost: uncField.text.replace(/^[\\\/]+/, "").split(/[\\\/]/)[0] || "<host>"

    function folderOn(root) { return root + "ShahNVR\\recordings" }

    function openFor(n) {
        node = n
        kind = "local"
        const first = (n.metrics?.drives ?? [])[0]
        driveSelect.value = first ? first.root : null
        localField.text = first ? folderOn(first.root) : ""
        uncField.text = "\\\\"
        capInput.reset(null)
        open()
    }

    width: Math.min(600, parent ? parent.width - 40 : 600)
    title: "Add storage to " + (node.name ?? "")
    description: "It is added at the end of the fill order. The node checks the folder within a few seconds and shows OK or the exact problem."

    ToggleGroup {
        options: [{ value: "local", label: "Drive on the node" }, { value: "network", label: "Network share" }]
        value: dialog.kind
        size: "md"
        onPicked: v => dialog.kind = v
    }

    // ---------------------------------------------------------------- drive on the node
    ColumnLayout {
        visible: dialog.kind === "local"
        spacing: 6
        Layout.fillWidth: true
        AppText { text: "Drive"; font.weight: Font.Medium }
        AppSelect {
            id: driveSelect
            visible: dialog.drives.length > 0
            Layout.fillWidth: true
            placeholder: "Choose a drive"
            options: dialog.drives.map(d => ({
                value: d.root,
                label: d.root + "  ·  " + Fmt.bytes(d.free_bytes) + " free of " + Fmt.bytes(d.total_bytes) + (d.fstype ? "  ·  " + d.fstype : "")
            }))
            onPicked: v => localField.text = dialog.folderOn(v)
        }
        AppText {
            visible: dialog.drives.length === 0
            text: "The node has not reported its drives yet; type the folder below."
            variant: "small"
        }
        AppText { text: "Folder"; font.weight: Font.Medium; Layout.topMargin: 4 }
        AppInput { id: localField; Layout.fillWidth: true; font.family: Theme.mono; placeholderText: "D:\\ShahNVR\\recordings" }
        AppText { text: "Created automatically if it does not exist."; variant: "small" }
    }

    // ---------------------------------------------------------------- network share
    ColumnLayout {
        visible: dialog.kind === "network"
        spacing: 6
        Layout.fillWidth: true
        AppText { text: "Share folder (UNC path)"; font.weight: Font.Medium }
        AppInput { id: uncField; Layout.fillWidth: true; font.family: Theme.mono; placeholderText: "\\\\192.168.1.9\\nvr\\recordings" }
        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: 4
            implicitHeight: help.implicitHeight + 24
            radius: Theme.radius
            color: Theme.alpha(Theme.info, 0.08)
            border.color: Theme.alpha(Theme.info, 0.3)
            RowLayout {
                id: help
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8
                Icon { name: "info"; size: 15; color: Theme.info; Layout.alignment: Qt.AlignTop }
                ColumnLayout {
                    spacing: 6
                    Layout.fillWidth: true
                    AppText {
                        text: "The share's username and password are never stored in the central manager. Save them once on the node PC, signed in as the Windows user that runs the media node:"
                        variant: "small"
                        color: Theme.foreground
                        wrapMode: Text.WordWrap
                        elide: Text.ElideNone
                        Layout.fillWidth: true
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: cmd.implicitHeight + 10
                        radius: 4
                        color: Theme.muted
                        AppText {
                            id: cmd
                            anchors.fill: parent
                            anchors.margins: 5
                            anchors.leftMargin: 8
                            text: "cmdkey /add:" + dialog.shareHost + " /user:<user> /pass:<password>"
                            variant: "mono"
                            wrapMode: Text.WrapAnywhere
                            elide: Text.ElideNone
                        }
                    }
                    AppText {
                        text: "Use the \\\\host\\share\\folder path, not a mapped drive letter (Z:): drive letters are not visible to the media node."
                        variant: "small"
                        color: Theme.foreground
                        wrapMode: Text.WordWrap
                        elide: Text.ElideNone
                        Layout.fillWidth: true
                    }
                }
            }
        }
    }

    // ---------------------------------------------------------------- cap
    CapField { id: capInput }
    AppText { visible: dialog.duplicate; text: "This node already has that folder."; color: Theme.danger; font.pixelSize: Theme.textXs }

    footer: [
        Item { Layout.fillWidth: true },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: dialog.close() },
        AppButton {
            text: "Add storage"
            enabled: dialog.valid
            onClicked: {
                NodeDetail.addVolume(dialog.path, capInput.value)
                dialog.close()
            }
        }
    ]
}
