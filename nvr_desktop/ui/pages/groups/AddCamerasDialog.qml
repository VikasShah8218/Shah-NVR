import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Pick cameras (paged, searchable, "Ungrouped" by default) and move them into a group. The selection survives
// paging (at most 500 at a time). Store: Groups.addPicker (AddCamerasStore).
AppDialog {
    id: dialog

    property var group: ({})  // {id, name, pathLabel}
    property bool pending: false
    readonly property var picker: Groups.addPicker

    function openFor(g) {
        group = g
        pending = false
        search.text = ""
        picker.start(g.id)
        open()
    }

    width: Math.min(640, parent ? parent.width - 40 : 640)
    title: 'Add cameras to "' + (group.name ?? "") + '"'
    description: (group.pathLabel ?? "") + ". A camera is in one group at a time: cameras from another group are moved."

    Connections {
        target: Groups
        function onFailed() { dialog.pending = false }  // the toast says why; try again
        function onSaved(id) {
            if (dialog.pending && id === dialog.group.id) {
                dialog.pending = false
                dialog.close()
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        AppInput {
            id: search
            Layout.fillWidth: true
            iconName: "search"
            placeholderText: "Search name or #id"
            onTextChanged: dialog.picker.setSearch(text)
        }
        ToggleGroup {
            options: [{ value: "ungrouped", label: "Ungrouped" }, { value: "all", label: "All" }]
            value: dialog.picker.onlyUngrouped ? "ungrouped" : "all"
            onPicked: v => dialog.picker.setOnlyUngrouped(v === "ungrouped")
        }
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 330
        radius: Theme.radiusSm
        color: "transparent"
        border.color: Theme.border
        clip: true

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 1
            spacing: 0
            // "select this page"
            Rectangle {
                visible: list.count > 0
                Layout.fillWidth: true
                implicitHeight: 34
                color: "transparent"
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
                AppCheckBox {
                    anchors.verticalCenter: parent.verticalCenter
                    x: 12
                    checkable: false
                    checked: dialog.picker.pageAllSelected
                    text: "Select this page"
                    onClicked: dialog.picker.togglePage()
                }
            }
            ListView {
                id: list
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: dialog.picker.listModel
                ScrollBar.vertical: AppScrollBar {}
                delegate: Rectangle {
                    id: item
                    required property var model
                    readonly property bool here: model.group_id === dialog.group.id
                    width: list.width
                    height: 34
                    color: itemHover.hovered && !here ? Theme.alpha(Theme.accent, 0.6) : "transparent"
                    opacity: here ? 0.5 : 1
                    HoverHandler { id: itemHover }
                    MouseArea {
                        anchors.fill: parent
                        enabled: !item.here
                        cursorShape: Qt.PointingHandCursor
                        onClicked: dialog.picker.toggleSelected(item.model.id)
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 10
                        AppCheckBox {
                            checkable: false
                            enabled: !item.here
                            checked: item.here || item.model.selected
                            onClicked: dialog.picker.toggleSelected(item.model.id)
                        }
                        StatusDot { status: item.model.status }
                        AppText { text: item.model.name; Layout.fillWidth: true }
                        AppText {
                            text: item.here ? "already here" : item.model.group_path ?? ""
                            variant: "small"
                            Layout.maximumWidth: 220
                        }
                    }
                }
                AppText {
                    visible: !dialog.picker.loading && list.count === 0
                    width: list.width - 24
                    x: 12
                    y: 12
                    wrapMode: Text.WordWrap
                    elide: Text.ElideNone
                    variant: "muted"
                    text: dialog.picker.query !== "" ? "No cameras match."
                        : dialog.picker.onlyUngrouped ? "Every camera is already in a group. Choose “All” to move cameras from other groups."
                        : "No cameras."
                }
            }
        }
    }

    Pager { Layout.fillWidth: true; store: dialog.picker }

    footer: [
        AppText {
            text: dialog.picker.selectedCount + " selected"
                  + (dialog.picker.selectedCount >= dialog.picker.maxPick ? " (max " + dialog.picker.maxPick + " at a time)" : "")
            variant: "small"
        },
        LinkText {
            visible: dialog.picker.selectedCount > 0
            text: "clear"
            onActivated: dialog.picker.clearSelection()
        },
        Item { Layout.fillWidth: true },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: dialog.close() },
        AppButton {
            objectName: "addCamerasConfirm"
            text: dialog.pending ? "Adding…" : "Add " + (dialog.picker.selectedCount || "") + " camera" + (dialog.picker.selectedCount === 1 ? "" : "s")
            enabled: dialog.picker.selectedCount > 0 && !dialog.pending
            onClicked: {
                dialog.pending = true
                Groups.addPickedCameras()
            }
        }
    ]
}
