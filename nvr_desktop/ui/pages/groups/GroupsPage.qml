import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Port of nvr_client/src/features/groups/GroupsPage.tsx: the camera-group tree on the left (lazy: ManageGroups),
// the selection on the right: all groups (top level), ungrouped cameras, or one group with its breadcrumb,
// counts, sub-groups table and cameras table (bulk move / remove). Router.go("groups", id) opens a group.
Item {
    id: root
    objectName: "groupsPage"

    property int revealedId: 0
    readonly property var detail: Groups.detail
    readonly property var cams: Groups.groupCameras

    // the tree row / detail of a group, as one shape for the dialogs
    function ref(g) {
        const path = g.path ?? ""
        const ids = path.split("/").filter(x => x !== "")
        return {
            id: g.id, name: g.name, path: path, description: g.description ?? "",
            pathLabel: g.pathLabel ?? g.path_label ?? g.name,
            parentId: g.parentId ?? g.parent_id ?? (ids.length > 1 ? Number(ids[ids.length - 2]) : 0),
            childGroups: g.childGroups ?? g.child_groups ?? 0,
            camerasDirect: g.camerasDirect ?? g.cameras_direct ?? 0
        }
    }

    function openFromRouter() {
        if (Router.page !== "groups")
            return
        if (Router.id > 0)
            Groups.selectGroup(Router.id)
        else if (Groups.kind === "group" && Groups.groupId === 0)
            Groups.selectRoot()
    }

    Component.onCompleted: {
        ManageGroups.setActive(true)
        Groups.setActive(true)
        if (Router.id > 0)
            Groups.selectGroup(Router.id)
        else
            Groups.refreshAll()
    }
    Component.onDestruction: {
        ManageGroups.setActive(false)
        Groups.setActive(false)
    }
    Connections {
        target: Router
        function onChanged() { root.openFromRouter() }
    }
    // a selected group (from a link, the table or a new group) is expanded into view in the tree
    Connections {
        target: Groups
        function onChanged() {
            if (Groups.kind === "group" && root.detail.path && root.detail.id !== root.revealedId) {
                root.revealedId = root.detail.id
                ManageGroups.reveal(root.detail.path)
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: Theme.pagePadding
        spacing: 16

        // ============================================================ tree
        ColumnLayout {
            Layout.preferredWidth: 320
            Layout.fillHeight: true
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                AppText { text: "Groups"; variant: "title"; Layout.fillWidth: true }
                AppButton {
                    objectName: "newGroupButton"
                    text: "New group"
                    iconName: "folder-plus"
                    size: "sm"
                    onClicked: formDialog.openCreate(0, "")
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.radiusLg
                color: Theme.card
                border.color: Theme.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 2

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 32
                        radius: Theme.radiusSm
                        color: Groups.kind === "root" ? Theme.accent : rootHover.hovered ? Theme.alpha(Theme.accent, 0.7) : "transparent"
                        HoverHandler { id: rootHover }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Groups.selectRoot() }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            spacing: 8
                            Icon { name: "folder-tree"; size: 15; color: Theme.mutedForeground }
                            AppText { text: "All groups"; font.weight: Groups.kind === "root" ? Font.Medium : Font.Normal; Layout.fillWidth: true }
                        }
                    }

                    GroupTree {
                        objectName: "manageGroupTree"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        store: ManageGroups
                        selectable: true
                        dropGroups: true
                        dragItems: true
                        dragGhost: ghost
                        dragRoot: root
                        selectedGroupId: Groups.kind === "group" ? Groups.groupId : 0
                        ungroupedSelected: Groups.kind === "ungrouped"
                        emptyText: "No groups yet."
                        onGroupClicked: row => Groups.selectGroup(row.id)
                        onUngroupedClicked: Groups.selectUngrouped()
                        onGroupMenu: (row, anchor) => groupMenu.openFor(root.ref(row), anchor)
                        onGroupDropped: (draggedId, target) => moveDialog.openFor(root.ref(ghost.payload), target.id, target.pathLabel)
                    }
                }
            }
        }

        // ============================================================ selection
        PageScroll {
            id: panel
            Layout.fillWidth: true
            Layout.fillHeight: true
            // PageScroll adds its own page padding: cancel the outer one on this side
            Layout.topMargin: -Theme.pagePadding
            Layout.rightMargin: -Theme.pagePadding
            Layout.bottomMargin: -Theme.pagePadding

            // ---------------------------------------------------- top level
            ColumnLayout {
                visible: Groups.kind === "root"
                Layout.fillWidth: true
                spacing: 12
                PageHeader {
                    title: "All groups"
                    description: "Top-level groups. A camera sits in one group or none; the Live View shows this tree."
                }
                EmptyState {
                    visible: !Groups.subGroups.loading && Groups.subGroups.total === 0
                    iconName: "folder-tree"
                    title: "No groups yet"
                    text: "Create top-level groups (e.g. Anantnag, Jammu, Ramban), then sub-groups inside them, then add cameras."
                }
            }

            // ---------------------------------------------------- ungrouped
            PageHeader {
                visible: Groups.kind === "ungrouped"
                title: "Ungrouped cameras"
                description: "Cameras in no group. Select some and move them into a group."
            }

            // ---------------------------------------------------- one group
            EmptyState {
                visible: Groups.kind === "group" && Groups.missing
                iconName: "folder"
                title: "Group not found"
                text: "It was deleted. Choose another group on the left."
            }
            ColumnLayout {
                visible: Groups.kind === "group" && !Groups.missing && !!root.detail.id
                Layout.fillWidth: true
                spacing: 10

                // breadcrumb
                Flow {
                    Layout.fillWidth: true
                    spacing: 4
                    LinkText { text: "All groups"; variant: "small"; color: hovered ? Theme.primary : Theme.mutedForeground; onActivated: Groups.selectRoot() }
                    Repeater {
                        model: root.detail.breadcrumb ?? []
                        delegate: Row {
                            required property var modelData
                            spacing: 4
                            Icon { name: "chevron-right"; size: 12; color: Theme.mutedForeground; anchors.verticalCenter: parent.verticalCenter }
                            LinkText {
                                text: modelData.name
                                variant: "small"
                                color: hovered ? Theme.primary : Theme.mutedForeground
                                onActivated: Groups.selectGroup(modelData.id)
                            }
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    ColumnLayout {
                        spacing: 2
                        Layout.fillWidth: true
                        RowLayout {
                            spacing: 8
                            Icon { name: "folder"; size: 20; color: Theme.alpha(Theme.primary, 0.85) }
                            AppText { objectName: "groupTitle"; text: root.detail.name ?? ""; variant: "title"; Layout.fillWidth: true }
                        }
                        AppText {
                            visible: !!root.detail.description
                            text: root.detail.description ?? ""
                            variant: "muted"
                            wrapMode: Text.WordWrap
                            elide: Text.ElideNone
                            Layout.fillWidth: true
                        }
                    }
                    Row {
                        spacing: 6
                        Layout.alignment: Qt.AlignTop
                        AppButton { text: "Add cameras"; iconName: "plus"; size: "sm"; onClicked: addDialog.openFor(root.ref(root.detail)) }
                        AppButton { text: "Sub-group"; iconName: "folder-plus"; size: "sm"; variant: "outline"; onClicked: formDialog.openCreate(root.detail.id, root.detail.path_label) }
                        AppButton { text: "Edit"; iconName: "pencil"; size: "sm"; variant: "outline"; onClicked: formDialog.openEdit(root.ref(root.detail)) }
                        AppButton { text: "Move"; iconName: "move-right"; size: "sm"; variant: "outline"; onClicked: moveDialog.openFor(root.ref(root.detail)) }
                        AppButton { text: "Delete"; iconName: "trash-2"; size: "sm"; variant: "outline"; onClicked: deleteDialog.openFor(root.ref(root.detail)) }
                    }
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    Repeater {
                        model: [
                            { label: "Sub-groups", value: root.detail.child_groups ?? 0 },
                            { label: "Cameras here", value: root.detail.cameras_direct ?? 0 },
                            { label: "Cameras in total", value: root.detail.cameras_total ?? 0 },
                            { label: "Online", value: (root.detail.online_total ?? 0) + " / " + (root.detail.cameras_total ?? 0),
                              warn: (root.detail.online_total ?? 0) < (root.detail.cameras_total ?? 0) }
                        ]
                        delegate: Rectangle {
                            required property var modelData
                            implicitHeight: 28
                            implicitWidth: statRow.implicitWidth + 20
                            radius: Theme.radiusSm
                            color: Theme.card
                            border.color: Theme.border
                            Row {
                                id: statRow
                                anchors.centerIn: parent
                                spacing: 6
                                AppText { text: modelData.label; variant: "small" }
                                AppText {
                                    text: modelData.value
                                    font.pixelSize: Theme.textXs
                                    font.weight: Font.Medium
                                    color: modelData.warn ? Theme.warning : Theme.foreground
                                }
                            }
                        }
                    }
                }
            }

            // ---------------------------------------------------- sub-groups table (top level / a group)
            AppText {
                visible: Groups.kind === "group" && !Groups.missing && Groups.subGroups.total > 0
                text: "Sub-groups"
                font.weight: Font.Medium
            }
            Rectangle {
                visible: Groups.kind !== "ungrouped" && !Groups.missing && Groups.subGroups.listModel.count > 0
                Layout.fillWidth: true
                implicitHeight: subTable.implicitHeight
                radius: Theme.radiusLg
                color: Theme.card
                border.color: Theme.border
                clip: true
                ColumnLayout {
                    id: subTable
                    width: parent.width
                    spacing: 0
                    TableHeader {
                        columns: [{ title: "Name", width: 0 }, { title: "Sub-groups", width: 90 }, { title: "Cameras", width: 90 },
                                  { title: "Online", width: 90 }, { title: "", width: 36 }]
                    }
                    Repeater {
                        model: Groups.subGroups.listModel
                        delegate: TableRow {
                            id: subRow
                            required property var model
                            clickable: true
                            onClicked: Groups.selectGroup(model.id)
                            RowLayout {
                                spacing: 8
                                Layout.fillWidth: true
                                Icon { name: "folder"; size: 15; color: Theme.alpha(Theme.primary, 0.85) }
                                AppText { text: subRow.model.name; font.weight: Font.Medium; Layout.fillWidth: true }
                            }
                            AppText { text: subRow.model.child_groups; Layout.preferredWidth: 90 }
                            AppText { text: subRow.model.cameras_total; Layout.preferredWidth: 90 }
                            AppText {
                                text: subRow.model.cameras_total ? subRow.model.online_total + " / " + subRow.model.cameras_total : "—"
                                color: subRow.model.online_total < subRow.model.cameras_total ? Theme.warning : Theme.foreground
                                Layout.preferredWidth: 90
                            }
                            AppButton {
                                id: subMenuButton
                                variant: "ghost"; size: "icon"; iconName: "ellipsis"
                                Layout.preferredWidth: 36
                                onClicked: groupMenu.openFor(root.ref(subRow.model), subMenuButton)
                            }
                        }
                    }
                }
            }
            Pager {
                visible: Groups.kind !== "ungrouped" && !Groups.missing && Groups.subGroups.total > 0 && pageCount > 1
                Layout.fillWidth: true
                store: Groups.subGroups
                sizes: [25, 50, 100]
            }

            // ---------------------------------------------------- cameras table (a group / ungrouped)
            ColumnLayout {
                visible: Groups.kind === "ungrouped" || (Groups.kind === "group" && !Groups.missing && !!root.detail.id)
                Layout.fillWidth: true
                spacing: 10

                AppText { visible: Groups.kind === "group"; text: "Cameras in this group"; font.weight: Font.Medium }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    AppInput {
                        Layout.preferredWidth: 260
                        iconName: "search"
                        placeholderText: "Search cameras"
                        text: root.cams.search
                        onTextChanged: root.cams.setSearch(text)
                    }
                    // bulk actions on the ticked cameras
                    Rectangle {
                        visible: root.cams.selectedCount > 0
                        implicitHeight: 38
                        implicitWidth: bulkRow.implicitWidth + 16
                        radius: Theme.radiusSm
                        color: Theme.alpha(Theme.accent, 0.4)
                        border.color: Theme.border
                        RowLayout {
                            id: bulkRow
                            anchors.verticalCenter: parent.verticalCenter
                            x: 8
                            spacing: 8
                            AppText { text: root.cams.selectedCount + " selected" }
                            GroupPicker {
                                objectName: "bulkMovePicker"
                                implicitHeight: 30
                                implicitWidth: 170
                                placeholder: "Move to…"
                                isDisabled: row => row.id === Groups.groupId
                                onPicked: (id, label) => { if (id > 0) Groups.moveSelectedCameras(id) }
                            }
                            AppButton {
                                visible: Groups.kind === "group"
                                text: "Remove from group"
                                iconName: "x"
                                size: "sm"
                                variant: "outline"
                                onClicked: Groups.moveSelectedCameras(0)
                            }
                            LinkText { text: "clear"; variant: "small"; onActivated: root.cams.clearSelection() }
                        }
                    }
                    Item { Layout.fillWidth: true }
                }

                EmptyState {
                    visible: !root.cams.loading && root.cams.total === 0
                    iconName: root.cams.query !== "" ? "search" : "camera"
                    title: root.cams.query !== "" ? "No cameras match"
                         : Groups.kind === "ungrouped" ? "No ungrouped cameras" : "No cameras directly in this group"
                    text: root.cams.query !== "" ? "Change the search."
                        : Groups.kind === "ungrouped" ? "Every camera is in a group."
                        : (root.detail.cameras_total ? "Its sub-groups hold " + root.detail.cameras_total + ". " : "")
                          + "Use Add cameras to put cameras here."
                }

                Rectangle {
                    visible: root.cams.listModel.count > 0
                    Layout.fillWidth: true
                    implicitHeight: camTable.implicitHeight
                    radius: Theme.radiusLg
                    color: Theme.card
                    border.color: Theme.border
                    clip: true
                    ColumnLayout {
                        id: camTable
                        width: parent.width
                        spacing: 0
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 40
                            color: "transparent"
                            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 16
                                anchors.rightMargin: 16
                                spacing: 12
                                AppCheckBox {
                                    objectName: "selectPageBox"
                                    checkable: false
                                    checked: root.cams.pageAllSelected
                                    onClicked: root.cams.togglePage()
                                    Layout.preferredWidth: 24
                                }
                                AppText { text: "Camera"; font.weight: Font.Medium; Layout.fillWidth: true }
                                AppText { text: "Status"; font.weight: Font.Medium; Layout.preferredWidth: 160 }
                                AppText { text: "#"; font.weight: Font.Medium; Layout.preferredWidth: 50 }
                            }
                        }
                        Repeater {
                            model: root.cams.listModel
                            delegate: TableRow {
                                id: camRow
                                required property var model
                                clickable: true
                                onClicked: root.cams.toggleSelected(model.id)
                                AppCheckBox {
                                    checkable: false
                                    checked: camRow.model.selected
                                    onClicked: root.cams.toggleSelected(camRow.model.id)
                                    Layout.preferredWidth: 24
                                }
                                Item {
                                    Layout.fillWidth: true
                                    implicitHeight: camLink.implicitHeight
                                    LinkText {
                                        id: camLink
                                        text: camRow.model.name
                                        font.weight: Font.Medium
                                        width: Math.min(implicitWidth, parent.width)
                                        onActivated: Router.go("camera", camRow.model.id)
                                    }
                                }
                                RowLayout {
                                    spacing: 8
                                    Layout.fillWidth: false  // a nested layout fills by default: keep the column fixed
                                    Layout.preferredWidth: 160
                                    StatusDot { status: camRow.model.status }
                                    AppText { text: Status.label(camRow.model.status); variant: "small"; Layout.fillWidth: true }
                                }
                                AppText { text: camRow.model.id; variant: "muted"; Layout.preferredWidth: 50 }
                            }
                        }
                    }
                }
                Pager { Layout.fillWidth: true; store: root.cams; sizes: [25, 50, 100] }
            }
        }
    }

    DragGhost { id: ghost }

    // one menu for tree rows and sub-group rows
    AppMenu {
        id: groupMenu
        property var group: ({})
        function openFor(g, button) {
            group = g
            popup(button, button.width - width, button.height + 4)
        }
        AppMenuItem { text: "Add cameras"; iconName: "plus"; onTriggered: addDialog.openFor(groupMenu.group) }
        AppMenuItem { text: "New sub-group"; iconName: "folder-plus"; onTriggered: formDialog.openCreate(groupMenu.group.id, groupMenu.group.pathLabel) }
        AppMenuItem { text: "Rename"; iconName: "pencil"; onTriggered: formDialog.openEdit(groupMenu.group) }
        AppMenuItem { text: "Move…"; iconName: "move-right"; onTriggered: moveDialog.openFor(groupMenu.group) }
        MenuSeparator {}
        AppMenuItem { text: "Delete"; iconName: "trash-2"; danger: true; onTriggered: deleteDialog.openFor(groupMenu.group) }
    }

    GroupFormDialog { id: formDialog }
    MoveGroupDialog { id: moveDialog }
    AddCamerasDialog { id: addDialog }

    // an empty group goes at once; a non-empty one only with "move its contents up one level"
    ConfirmDialog {
        id: deleteDialog
        property var group: ({})
        readonly property bool empty: (group.childGroups ?? 0) === 0 && (group.camerasDirect ?? 0) === 0
        function openFor(g) { group = g; open() }
        title: 'Delete "' + (group.name ?? "") + '"?'
        description: empty ? "The group is empty."
            : "It holds " + group.childGroups + " sub-group" + (group.childGroups === 1 ? "" : "s") + " and "
              + group.camerasDirect + " camera" + (group.camerasDirect === 1 ? "" : "s") + ". They move to "
              + (group.parentId ? "the parent group" : "the top level / Ungrouped") + "; no camera or recording is deleted."
        confirmLabel: empty ? "Delete" : "Move contents up & delete"
        destructive: true
        onConfirmed: Groups.deleteGroup(group.id, group.parentId ?? 0, !empty)
    }
}
