import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Where a media node records (port of nvr_client/src/features/nodes/StorageTab.tsx): its own folder plus
// extra drives and network shares, each with an optional cap. The node fills them in order and overwrites
// the oldest recordings only when every storage is full.
Card {
    id: tab
    objectName: "storageTab"

    function openAdd() { addDialog.openFor(node) }

    property var node: ({})
    readonly property var res: node.res ?? ({})
    readonly property var volumes: node.volumes ?? []
    readonly property var columns: [
        { title: "Order", width: 104 }, { title: "Folder", width: 0 }, { title: "State", width: 230 },
        { title: "Recordings / cap", width: 200 }, { title: "Disk free", width: 150 }, { title: "", width: 36 }
    ]

    Layout.fillWidth: true
    padding: 0
    spacing: 0

    // ---------------------------------------------------------------- header
    RowLayout {
        Layout.fillWidth: true
        Layout.margins: 16
        spacing: 16
        ColumnLayout {
            spacing: 4
            Layout.fillWidth: true
            AppText { text: "Storage"; font.weight: Font.Medium }
            AppText {
                text: "The node records to the first storage in this order that has room, moves to the next when it is full, "
                    + "and overwrites the oldest recordings only when every storage is full. Recordings stay playable wherever they are."
                variant: "small"
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                Layout.fillWidth: true
            }
        }
        AppButton { text: "Add storage"; iconName: "plus"; size: "sm"; onClicked: addDialog.openFor(tab.node) }
    }

    Banner {
        visible: tab.res.allFull === true
        tone: "warning"
        text: "All storage is full: the node is overwriting its oldest recordings. Add storage or raise a cap."
    }
    Banner {
        readonly property int count: (tab.res.volumesOffline ?? []).length
        visible: count > 0
        tone: "danger"
        text: (count === 1 ? "1 storage is" : count + " storages are")
            + " offline: recordings on it cannot be played until it is back; new recordings go to the next storage."
    }

    EmptyState {
        visible: tab.volumes.length === 0
        Layout.margins: 16
        iconName: "hard-drive"
        title: "Waiting for the node"
        text: "The node registers its own recordings folder on its next heartbeat."
    }

    // ---------------------------------------------------------------- table
    TableHeader { visible: tab.volumes.length > 0; columns: tab.columns }
    Repeater {
        model: tab.volumes
        delegate: TableRow {
            id: row
            required property var modelData
            required property int index
            readonly property var v: modelData
            opacity: v.accepting ? 1 : 0.6

            // order
            RowLayout {
                spacing: 0
                Layout.preferredWidth: 104
                Layout.minimumWidth: 104
                Layout.maximumWidth: 104
                AppText { text: row.index + 1; variant: "muted"; Layout.preferredWidth: 22 }
                AppButton {
                    variant: "ghost"; size: "icon"; iconName: "arrow-up"; tip: "Earlier"
                    implicitWidth: 28; implicitHeight: 28
                    enabled: row.index > 0
                    onClicked: NodeDetail.moveVolume(row.index, -1)
                }
                AppButton {
                    variant: "ghost"; size: "icon"; iconName: "arrow-down"; tip: "Later"
                    implicitWidth: 28; implicitHeight: 28
                    enabled: row.index < tab.volumes.length - 1
                    onClicked: NodeDetail.moveVolume(row.index, 1)
                }
            }
            // folder (the flexible column: starts from 1 px so long paths wrap instead of pushing the others)
            ColumnLayout {
                spacing: 3
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                RowLayout {
                    spacing: 8
                    Layout.fillWidth: true
                    Icon {
                        name: row.v.kind === "network" ? "network" : "hard-drive"
                        size: 15
                        color: row.v.kind === "network" ? Theme.info : Theme.mutedForeground
                        Layout.alignment: Qt.AlignTop
                    }
                    AppText {
                        text: row.v.path
                        variant: "mono"
                        wrapMode: Text.WrapAnywhere
                        elide: Text.ElideNone
                        Layout.fillWidth: true
                    }
                }
                Flow {
                    spacing: 10
                    Layout.fillWidth: true
                    Layout.leftMargin: 23
                    AppText { visible: row.v.is_default; text: "node's own folder"; variant: "small"; font.pixelSize: 11 }
                    AppText { visible: row.v.writing; text: "● recording here now"; color: Theme.success; font.pixelSize: 11; font.weight: Font.Medium }
                    AppText { visible: !row.v.accepting; text: "new recordings stopped"; color: Theme.warning; font.pixelSize: 11 }
                }
            }
            // state
            ColumnLayout {
                spacing: 3
                Layout.preferredWidth: 230
                Layout.minimumWidth: 230
                Layout.maximumWidth: 230
                StatusBadge { status: row.v.state }
                AppText {
                    visible: !!row.v.state_detail
                    text: row.v.state_detail ?? ""
                    variant: "small"
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    elide: Text.ElideNone
                    Layout.fillWidth: true
                }
                AppText {
                    text: row.v.state === "PENDING" ? "waiting for the node to check it"
                        : row.v.last_report_at ? "checked " + Fmt.timeAgo(row.v.last_report_at) : ""
                    variant: "small"
                    font.pixelSize: 10
                }
            }
            // recordings / cap
            ColumnLayout {
                spacing: 4
                Layout.preferredWidth: 200
                Layout.minimumWidth: 200
                Layout.maximumWidth: 200
                AppText {
                    text: Fmt.bytes(row.v.recordings_bytes) + " / "
                        + (row.v.quota_bytes !== null && row.v.quota_bytes !== undefined ? Fmt.bytes(row.v.quota_bytes) : "whole disk")
                    font.pixelSize: Theme.textXs
                }
                UsageBar {
                    Layout.fillWidth: true
                    percent: row.v.quota_bytes ? Fmt.ratio(row.v.recordings_bytes, row.v.quota_bytes)
                        : Fmt.ratio(row.v.total_bytes - row.v.free_bytes, row.v.total_bytes)
                    warnAt: 90
                    dangerAt: 95
                }
            }
            AppText {
                text: row.v.free_bytes !== null && row.v.free_bytes !== undefined
                    ? Fmt.bytes(row.v.free_bytes) + " of " + Fmt.bytes(row.v.total_bytes) : "—"
                variant: "small"
                Layout.preferredWidth: 150
                Layout.minimumWidth: 150
                Layout.maximumWidth: 150
            }
            AppButton {
                id: menuButton
                variant: "ghost"; size: "icon"; iconName: "ellipsis"
                Layout.preferredWidth: 36
                onClicked: rowMenu.openFor(row.v, menuButton)
            }
        }
    }
    Item { implicitHeight: 6 }

    // ---------------------------------------------------------------- shared menu + dialogs
    AppMenu {
        id: rowMenu
        property var volume: ({})
        function openFor(v, button) {
            volume = v
            popup(button, button.width - width, button.height + 4)
        }
        AppMenuItem { text: "Edit cap"; iconName: "pencil"; onTriggered: capDialog.openFor(rowMenu.volume) }
        AppMenuItem {
            text: rowMenu.volume.accepting ? "Stop new recordings" : "Resume new recordings"
            iconName: rowMenu.volume.accepting ? "pause" : "play"
            onTriggered: NodeDetail.setVolumeAccepting(rowMenu.volume.id, !rowMenu.volume.accepting)
        }
        MenuSeparator {}
        AppMenuItem {
            text: "Remove"
            iconName: "trash-2"
            danger: true
            enabled: !rowMenu.volume.is_default
            onTriggered: removeDialog.openFor(rowMenu.volume)
        }
    }

    AddStorageDialog { id: addDialog }
    VolumeCapDialog { id: capDialog }

    ConfirmDialog {
        id: removeDialog
        property var volume: ({})
        readonly property bool hasRecordings: (volume.recordings_bytes ?? 0) > 0
        function openFor(v) {
            volume = v
            forceSwitch.checked = false
            open()
        }
        title: "Remove this storage?"
        description: (volume.path ?? "") + "\nThe node stops using it. Recorded files there are not deleted."
        confirmLabel: "Remove storage"
        destructive: true
        onConfirmed: NodeDetail.removeVolume(volume.id, forceSwitch.checked)

        Rectangle {
            visible: removeDialog.hasRecordings
            Layout.fillWidth: true
            implicitHeight: forceRow.implicitHeight + 24
            radius: Theme.radius
            color: "transparent"
            border.color: Theme.border
            RowLayout {
                id: forceRow
                anchors.fill: parent
                anchors.margins: 12
                spacing: 12
                AppSwitch { id: forceSwitch; Layout.alignment: Qt.AlignTop }
                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true
                    AppText { text: "Also forget its " + Fmt.bytes(removeDialog.volume.recordings_bytes) + " of recordings" }
                    AppText {
                        text: "Needed while recordings are stored there; they disappear from playback. Safer: stop new recordings and let retention empty it first."
                        variant: "small"
                        wrapMode: Text.WordWrap
                        elide: Text.ElideNone
                        Layout.fillWidth: true
                    }
                }
            }
        }
    }

    component Banner: Rectangle {
        property string tone: "warning"
        property string text: ""
        readonly property color toneColor: tone === "danger" ? Theme.danger : Theme.warning
        Layout.fillWidth: true
        Layout.leftMargin: 16
        Layout.rightMargin: 16
        Layout.bottomMargin: 12
        implicitHeight: bannerRow.implicitHeight + 16
        radius: Theme.radiusSm
        color: Theme.alpha(toneColor, 0.1)
        border.color: Theme.alpha(toneColor, 0.4)
        RowLayout {
            id: bannerRow
            anchors.fill: parent
            anchors.margins: 8
            anchors.leftMargin: 12
            spacing: 8
            Icon { name: "triangle-alert"; size: 15; color: parent.parent.toneColor; Layout.alignment: Qt.AlignTop }
            AppText {
                text: parent.parent.text
                color: parent.parent.toneColor
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                Layout.fillWidth: true
            }
        }
    }
}
