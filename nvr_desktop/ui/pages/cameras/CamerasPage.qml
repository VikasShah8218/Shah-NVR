import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Port of nvr_client/src/features/cameras/CamerasPage.tsx: camera table one page at a time (search and filter
// run on the server), enable switch, row menu (edit, live preview, recordings, delete) and the add / edit form.
PageScroll {
    id: root

    readonly property bool filtered: Cameras.query !== "" || Cameras.filter !== "all" || Cameras.groupFilter > 0
    property string groupFilterLabel: ""
    readonly property var columns: [
        { title: "#", width: 40 }, { title: "Name", width: 0 }, { title: "Group", width: 150 }, { title: "Streams", width: 280 },
        { title: "Media node", width: 150 }, { title: "Retention", width: 90 }, { title: "Last recording", width: 120 },
        { title: "Enabled", width: 70 }, { title: "", width: 36 }
    ]

    PageHeader {
        title: "Cameras"
        description: "Register cameras, their streams and how long recordings are kept."
        AppInput {
            width: 240
            iconName: "search"
            placeholderText: "Search name or #id"
            text: Cameras.search
            onTextChanged: Cameras.setSearch(text)
        }
        AppSelect {
            objectName: "cameraFilter"
            implicitWidth: 150
            options: Cameras.filterOptions
            value: Cameras.filter
            onPicked: v => Cameras.setFilter(v)
        }
        GroupPicker {
            objectName: "cameraGroupFilter"
            implicitWidth: 180
            value: Cameras.filter === "ungrouped" ? 0 : Cameras.groupFilter
            label: root.groupFilterLabel
            noneLabel: "Any group"
            onPicked: (id, label) => { root.groupFilterLabel = label; Cameras.setGroupFilter(id) }
        }
        AppButton { visible: Auth.allowed["20"] === true; text: "Discover"; iconName: "search"; variant: "outline"; onClicked: Router.go("discover") }
        AppButton { visible: Auth.allowed["20"] === true; text: "Add camera"; iconName: "plus"; onClicked: form.openFor(null) }
    }

    LoadingState { visible: Cameras.loading && Cameras.error === "" && Cameras.listModel.count === 0 }
    ErrorState { text: Cameras.error }
    EmptyState {
        visible: !Cameras.loading && Cameras.error === "" && Cameras.total === 0 && !root.filtered
        iconName: "camera"
        title: "No cameras yet"
        text: "Use Discover for ONVIF cameras, or Add camera to enter an RTSP URL manually."
    }

    Rectangle {
        visible: Cameras.listModel.count > 0
        Layout.fillWidth: true
        implicitHeight: table.implicitHeight
        radius: Theme.radiusLg
        color: Theme.card
        border.color: Theme.border
        clip: true

        ColumnLayout {
            id: table
            width: parent.width
            spacing: 0
            TableHeader { columns: root.columns }
            Repeater {
                model: Cameras.listModel
                delegate: TableRow {
                    id: row
                    required property var model
                    clickable: true
                    onClicked: Router.go("camera", model.id)

                    AppText { text: model.id; variant: "muted"; Layout.preferredWidth: 40 }
                    ColumnLayout {
                        spacing: 1
                        Layout.fillWidth: true
                        AppText { text: model.name; font.weight: Font.Medium; Layout.fillWidth: true }
                        AppText {
                            visible: !!model.description
                            text: model.description ?? ""
                            variant: "small"
                            Layout.fillWidth: true
                        }
                    }
                    Item {
                        Layout.preferredWidth: 150
                        implicitHeight: groupLink.implicitHeight
                        LinkText {
                            id: groupLink
                            text: row.model.group_path ?? "—"
                            active: !!row.model.group_id
                            variant: "small"
                            color: !active ? Theme.mutedForeground : hovered ? Theme.primary : Theme.foreground
                            width: Math.min(implicitWidth, parent.width)
                            onActivated: Router.go("groups", row.model.group_id)
                            AppToolTip { visible: groupLink.hovered && groupLink.truncated; text: row.model.group_path ?? "" }
                        }
                    }
                    Flow {
                        spacing: 8
                        Layout.preferredWidth: 280
                        Repeater {
                            model: row.model.streams
                            delegate: Row {
                                required property var modelData
                                spacing: 4
                                AppText { text: modelData.profile; variant: "small"; anchors.verticalCenter: parent.verticalCenter }
                                StatusBadge {
                                    status: modelData.status
                                    AppToolTip { visible: hoverTip.hovered && !!modelData.status_detail; text: modelData.status_detail ?? "" }
                                    HoverHandler { id: hoverTip }
                                }
                            }
                        }
                    }
                    Item {
                        Layout.preferredWidth: 150
                        implicitHeight: nodeLink.implicitHeight
                        LinkText {
                            id: nodeLink
                            readonly property var a: row.model.assignment
                            text: a && a.node_id ? a.node_name : "—"
                            active: !!(a && a.node_id)
                            color: !active ? Theme.mutedForeground : hovered ? Theme.primary : Theme.foreground
                            width: Math.min(implicitWidth, parent.width)
                            onActivated: Router.go("node", a.node_id)
                        }
                    }
                    AppText { text: Fmt.retention(model.retention_days); Layout.preferredWidth: 90 }
                    AppText {
                        text: model.lastSegment ? Fmt.timeAgo(model.lastSegment) : "—"
                        variant: "small"
                        Layout.preferredWidth: 120
                    }
                    Item {
                        Layout.preferredWidth: 70
                        implicitHeight: enabledSwitch.implicitHeight
                        AppSwitch {
                            id: enabledSwitch
                            checked: row.model.enabled
                            enabled: Auth.allowed["20"] === true
                            onToggled: Cameras.setEnabled(row.model.id, checked)
                        }
                    }
                    AppButton {
                        id: menuButton
                        variant: "ghost"
                        size: "icon"
                        iconName: "ellipsis"
                        Layout.preferredWidth: 36
                        onClicked: rowMenu.openFor(row.model, menuButton)
                    }
                }
            }
        }
    }

    EmptyState {
        visible: !Cameras.loading && Cameras.error === "" && Cameras.total === 0 && root.filtered
        iconName: "search"
        title: "No cameras match"
        text: "Change the search or the filter."
    }

    Pager {
        objectName: "camerasPager"
        Layout.fillWidth: true
        store: Cameras
        sizes: [25, 50, 100]
    }

    // One menu + confirm shared by all rows (cheaper than one per row).
    AppMenu {
        id: rowMenu
        property var camera: ({})
        function openFor(cam, button) {
            camera = cam
            popup(button, button.width - width, button.height + 4)
        }
        AppMenuItem { visible: Auth.allowed["20"] === true; text: "Edit"; iconName: "pencil"; onTriggered: form.openFor(Cameras.byId(rowMenu.camera.id)) }
        AppMenuItem { text: "Live preview"; iconName: "monitor-play"; onTriggered: Router.go("camera", rowMenu.camera.id) }
        AppMenuItem {
            visible: Auth.allowed["2"] === true
            text: "Recordings"
            iconName: "history"
            onTriggered: Router.go("playback", 0, { camera: rowMenu.camera.id })
        }
        MenuSeparator { visible: Auth.allowed["20"] === true; height: visible ? implicitHeight : 0 }
        AppMenuItem { visible: Auth.allowed["20"] === true; text: "Delete"; iconName: "trash-2"; danger: true; onTriggered: deleteConfirm.open() }
    }

    ConfirmDialog {
        id: deleteConfirm
        title: "Delete " + (rowMenu.camera.name ?? "") + "?"
        description: "Only cameras without recordings can be deleted. If it has recordings, disable it instead; they stay until their retention or storage space removes them."
        confirmLabel: "Delete camera"
        destructive: true
        onConfirmed: Cameras.remove(rowMenu.camera.id)
    }

    CameraFormSheet { id: form; objectName: "cameraForm" }
}
