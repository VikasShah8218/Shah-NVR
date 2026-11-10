import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Move a group (with its whole subtree) under another group or to the top level. Groups inside the moved group
// are greyed out in the picker; central refuses a cycle anyway.
AppDialog {
    id: dialog

    property var group: ({})   // {id, name, path, parentId}
    property int target: 0
    property string targetLabel: ""
    property bool pending: false

    function openFor(g, presetTarget, presetLabel) {
        group = g
        target = presetTarget === undefined ? (g.parentId ?? 0) : presetTarget
        targetLabel = presetLabel ?? ""
        pending = false
        open()
    }

    title: 'Move "' + (group.name ?? "") + '"'
    description: "Its sub-groups and cameras move with it."

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

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 5
        AppText { text: "New parent"; font.weight: Font.Medium }
        GroupPicker {
            objectName: "moveGroupPicker"
            Layout.fillWidth: true
            value: dialog.target
            label: dialog.targetLabel
            noneLabel: "Top level"
            isDisabled: row => !!dialog.group.path && (row.path ?? "").startsWith(dialog.group.path)
            onPicked: (id, label) => { dialog.target = id; dialog.targetLabel = label }
        }
    }
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: 36
        radius: Theme.radiusSm
        color: Theme.alpha(Theme.muted, 0.4)
        border.color: Theme.border
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            spacing: 8
            Icon { name: "folder"; size: 15; color: Theme.alpha(Theme.primary, 0.85) }
            AppText {
                text: (dialog.target > 0 ? (dialog.targetLabel !== "" ? dialog.targetLabel : "Group #" + dialog.target) + " › " : "")
                      + (dialog.group.name ?? "")
                Layout.fillWidth: true
            }
        }
    }

    footer: [
        Item { Layout.fillWidth: true },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: dialog.close() },
        AppButton {
            text: dialog.pending ? "Moving…" : "Move"
            enabled: !dialog.pending && dialog.target !== (dialog.group.parentId ?? 0)
            onClicked: {
                dialog.pending = true
                Groups.moveGroup(dialog.group.id, dialog.target)
            }
        }
    ]
}
