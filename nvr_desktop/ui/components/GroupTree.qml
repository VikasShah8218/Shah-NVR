import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

// Lazy camera-group tree (port of nvr_client GroupTree.tsx). `store` is a GroupTreeStore singleton (LiveGroups,
// ManageGroups, PickerGroups): it keeps the visible tree as a flat list (one row per group / camera / "more" /
// "loading" line with a `depth`), and loads each group's children only when it is expanded.
//   GroupTree { store: LiveGroups; showCameraBadge: true; onCameraClicked: row => Live.place(row.id) }
ListView {
    id: tree

    property var store
    property int selectedGroupId: 0
    property bool ungroupedSelected: false
    property bool selectable: false      // a click on a group selects it (management, pickers); else it expands
    property bool showActions: false     // ▶ play / manage buttons on group rows (live)
    property bool canManage: true        // show the manage button (false without the groups permission)
    property bool dragItems: false       // cameras and groups can be dragged (needs dragGhost + dragRoot)
    property bool dropGroups: false      // a group can be dropped on another group (management: move)
    property var onView: []              // camera ids on the live grid ("on view" badge)
    property var isDisabled: null        // function(row) -> bool: greyed out, not clickable (move dialog)
    property Item dragGhost: null
    property Item dragRoot: null
    property string emptyText: "No groups yet."

    signal groupClicked(var row)
    signal ungroupedClicked()
    signal cameraClicked(var row)
    signal playGroup(var row)
    signal manageGroup(var row)
    signal groupDropped(int draggedId, var target)
    signal groupMenu(var row, Item anchor)

    clip: true
    boundsBehavior: Flickable.StopAtBounds
    model: store ? store.listModel : null
    ScrollBar.vertical: AppScrollBar {}

    AppText {
        visible: !!tree.store && tree.store.empty && tree.count <= 1
        text: tree.emptyText
        variant: "muted"
        wrapMode: Text.WordWrap
        elide: Text.ElideNone
        width: tree.width - 16
        x: 8
        y: tree.count > 0 ? 40 : 8
    }

    delegate: Rectangle {
        id: row
        required property var model
        readonly property string kind: model.kind
        readonly property bool isGroup: kind === "group"
        readonly property bool isCamera: kind === "camera"
        readonly property bool isNode: isGroup || kind === "ungrouped"
        readonly property bool off: (isGroup && !!tree.isDisabled && tree.isDisabled(model)) || (isCamera && !model.enabled)
        readonly property bool selected: (isGroup && model.id === tree.selectedGroupId) || (kind === "ungrouped" && tree.ungroupedSelected)
        readonly property bool clickable: !off && (isNode || isCamera || kind === "more")
        readonly property bool partial: model.camerasTotal > 0 && model.onlineTotal < model.camerasTotal

        width: ListView.view.width
        height: isNode || isCamera ? 32 : 28
        radius: Theme.radiusSm
        color: dropTarget.containsDrag ? Theme.alpha(Theme.primary, 0.2)
             : selected ? Theme.accent
             : hover.hovered && clickable ? Theme.alpha(Theme.accent, 0.7) : "transparent"
        border.width: dropTarget.containsDrag ? 1 : 0
        border.color: Theme.primary
        opacity: off ? 0.45 : 1

        HoverHandler { id: hover }

        MouseArea {
            id: area
            anchors.fill: parent
            enabled: row.clickable
            cursorShape: Qt.PointingHandCursor
            drag.target: tree.dragItems && (row.isCamera || row.isGroup) && tree.dragGhost ? tree.dragGhost : null
            drag.threshold: 6
            onPressed: mouse => {
                if (tree.dragItems && tree.dragGhost && (row.isCamera || row.isGroup)) {
                    tree.dragGhost.payload = { id: row.model.id, name: row.model.name, path: row.model.path,
                                               parentId: row.model.parentId, pathLabel: row.model.pathLabel }
                    tree.dragGhost.begin(row.isGroup ? "group" : "camera", row.model.id, row.model.name,
                                         row.mapToItem(tree.dragRoot, mouse.x, mouse.y))
                }
            }
            drag.onActiveChanged: {
                if (!tree.dragGhost)
                    return
                if (!drag.active)
                    tree.dragGhost.Drag.drop()
                tree.dragGhost.dragging = drag.active
            }
            onClicked: {
                if (row.kind === "more")
                    tree.store.loadMore(row.model.listKey)
                else if (row.isCamera)
                    tree.cameraClicked(row.model)
                else if (row.kind === "ungrouped")
                    tree.selectable ? tree.ungroupedClicked() : tree.store.toggle("ungrouped")
                else if (row.isGroup)
                    tree.selectable || !row.model.expandable ? tree.groupClicked(row.model) : tree.store.toggle(String(row.model.id))
            }
            onDoubleClicked: if (row.isGroup && tree.selectable && row.model.expandable) tree.store.toggle(String(row.model.id))
        }

        DropArea {
            id: dropTarget
            anchors.fill: parent
            enabled: tree.dropGroups && row.isGroup && !row.off
            keys: ["group"]
            onDropped: drop => {
                if (drop.source && drop.source.groupId && drop.source.groupId !== row.model.id)
                    tree.groupDropped(drop.source.groupId, row.model)
            }
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: row.model.depth * 14 + (row.isNode ? 2 : 14)
            anchors.rightMargin: 6
            spacing: 6

            // chevron: expands / collapses (also in selectable trees)
            Item {
                visible: row.isNode
                implicitWidth: 20
                implicitHeight: 20
                Icon {
                    anchors.centerIn: parent
                    visible: row.model.expandable
                    name: row.model.expanded ? "chevron-down" : "chevron-right"
                    size: 14
                    color: chevronArea.containsMouse ? Theme.foreground : Theme.mutedForeground
                }
                MouseArea {
                    id: chevronArea
                    anchors.fill: parent
                    enabled: row.model.expandable
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: tree.store.toggle(row.isGroup ? String(row.model.id) : "ungrouped")
                }
            }
            Icon {
                visible: row.isGroup
                name: row.model.expanded ? "folder-open" : "folder"
                size: 15
                color: Theme.alpha(Theme.primary, 0.85)
            }
            Icon { visible: row.kind === "ungrouped"; name: "inbox"; size: 15; color: Theme.mutedForeground }
            StatusDot { visible: row.isCamera; status: row.model.status }
            Spinner { visible: row.kind === "loading" || (row.kind === "more" && row.model.busy); size: 13 }
            Icon { visible: row.kind === "error"; name: "circle-alert"; size: 13; color: Theme.danger }
            AppText {
                text: row.model.name
                Layout.fillWidth: true
                variant: row.isNode || row.isCamera ? "body" : "small"
                color: row.kind === "ungrouped" || row.kind === "loading" || row.kind === "empty" ? Theme.mutedForeground
                     : row.kind === "error" ? Theme.danger
                     : row.kind === "more" && hover.hovered ? Theme.foreground
                     : row.kind === "more" ? Theme.mutedForeground : Theme.foreground
                font.italic: row.kind === "ungrouped"
                font.weight: row.selected ? Font.Medium : Font.Normal
            }
            AppText {
                visible: row.isCamera && tree.onView.includes(row.model.id)
                text: "on view"
                color: Theme.primary
                font.pixelSize: 10
            }
            Row {
                visible: row.isGroup && tree.showActions && hover.hovered
                spacing: 0
                AppButton {
                    variant: "ghost"; size: "icon"; iconName: "play"; implicitHeight: 24
                    tip: "Play " + row.model.name + " on the grid"
                    enabled: row.model.camerasTotal > 0
                    onClicked: tree.playGroup(row.model)
                }
                AppButton {
                    visible: tree.canManage
                    variant: "ghost"; size: "icon"; iconName: "settings"; implicitHeight: 24
                    tip: "Manage group"
                    onClicked: tree.manageGroup(row.model)
                }
            }
            AppButton {
                id: menuButton
                visible: row.isGroup && tree.dropGroups && (hover.hovered || row.selected)
                variant: "ghost"; size: "icon"; iconName: "ellipsis"; implicitHeight: 24
                onClicked: tree.groupMenu(row.model, menuButton)
            }
            AppText {
                visible: row.isGroup && row.model.countLabel !== ""
                text: row.model.countLabel
                font.pixelSize: 11
                color: tree.showActions && row.partial ? Theme.warning : Theme.mutedForeground
                AppToolTip {
                    visible: countHover.hovered
                    text: tree.showActions ? "online / cameras (all sub-groups)" : "cameras (all sub-groups)"
                }
                HoverHandler { id: countHover }
            }
        }
    }
}
