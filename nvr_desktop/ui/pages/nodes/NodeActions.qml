import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Row / header menu for a node (port of NodeActions.tsx):
// edit limits, drain (confirm), cordon, activate, delete (confirm + "also remove recordings index").
Item {
    id: actions

    property int nodeId: 0
    property bool asButton: false // false = "…" icon (table rows), true = "Actions" outline button
    readonly property var node: Nodes.byId(nodeId) ?? ({})

    implicitWidth: trigger.implicitWidth
    implicitHeight: trigger.implicitHeight

    AppButton {
        id: trigger
        variant: actions.asButton ? "outline" : "ghost"
        size: actions.asButton ? "sm" : "icon"
        iconName: "ellipsis"
        text: actions.asButton ? "Actions" : ""
        onClicked: menu.popup(trigger, trigger.width - menu.width, trigger.height + 4)
    }

    AppMenu {
        id: menu
        AppMenuItem { text: "Edit limits"; iconName: "sliders-horizontal"; onTriggered: limits.openFor(actions.node) }
        MenuSeparator {}
        AppMenuItem {
            text: "Drain (move cameras away)"
            iconName: "waves"
            enabled: actions.node.state !== "DRAINING"
            onTriggered: drainConfirm.open()
        }
        AppMenuItem {
            text: "Cordon (no new cameras)"
            iconName: "ban"
            enabled: actions.node.state !== "CORDONED"
            onTriggered: Nodes.action(actions.nodeId, "cordon")
        }
        AppMenuItem {
            text: "Activate"
            iconName: "play"
            enabled: actions.node.state !== "ACTIVE" && actions.node.state !== "READY"
            onTriggered: Nodes.action(actions.nodeId, "activate")
        }
        MenuSeparator {}
        AppMenuItem { text: "Delete node"; iconName: "trash-2"; danger: true; onTriggered: deleteConfirm.open() }
    }

    NodeLimitsDialog { id: limits }

    ConfirmDialog {
        id: drainConfirm
        title: "Drain " + (actions.node.name ?? "") + "?"
        description: "All cameras on this node will be moved to other healthy nodes, and it will not receive new cameras until you activate it again."
        confirmLabel: "Drain node"
        onConfirmed: Nodes.action(actions.nodeId, "drain")
    }

    ConfirmDialog {
        id: deleteConfirm
        title: "Delete " + (actions.node.name ?? "") + "?"
        description: "Only possible when no cameras are assigned (drain it first). If the node agent is still running it will register itself again."
        confirmLabel: "Delete"
        destructive: true
        onOpened: forceSwitch.checked = false
        onConfirmed: Nodes.remove(actions.nodeId, forceSwitch.checked)

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 64
            radius: Theme.radius
            color: "transparent"
            border.color: Theme.border
            RowLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 12
                AppSwitch { id: forceSwitch }
                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true
                    AppText { text: "Also remove this node's recordings index" }
                    AppText { text: "Recorded files on the node itself are not touched."; variant: "small" }
                }
            }
        }
    }
}
