import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Create a group (under a parent, or at the top level) or edit a group's name / description.
AppDialog {
    id: dialog

    property int groupId: 0     // 0 = create
    property int parentId: 0    // create: 0 = top level
    property string context: "" // path label shown under the title
    property bool pending: false

    function openCreate(parentId, parentLabel) {
        groupId = 0
        dialog.parentId = parentId
        context = parentId > 0 ? "Inside " + parentLabel : "A top-level group, e.g. a district or region."
        nameField.text = ""
        descField.text = ""
        pending = false
        open()
        nameField.forceActiveFocus()
    }

    function openEdit(group) {
        groupId = group.id
        parentId = 0
        context = group.pathLabel ?? group.path_label ?? ""
        nameField.text = group.name
        descField.text = group.description ?? ""
        pending = false
        open()
        nameField.forceActiveFocus()
    }

    function submit() {
        if (nameField.text.trim() === "" || pending)
            return
        pending = true
        if (groupId > 0)
            Groups.updateGroup(groupId, nameField.text, descField.text)
        else
            Groups.createGroup(parentId, nameField.text, descField.text)
    }

    title: groupId > 0 ? "Edit group" : parentId > 0 ? "New sub-group" : "New group"
    description: context

    Connections {
        target: Groups
        function onFailed() { dialog.pending = false }  // the toast says why; try again
        function onSaved(id) {
            if (!dialog.pending)
                return
            dialog.pending = false
            dialog.close()
            if (dialog.groupId === 0)
                Groups.selectGroup(id)  // show the new group
        }
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 5
        AppText { text: "Name"; font.weight: Font.Medium }
        AppInput {
            id: nameField
            objectName: "groupNameField"
            Layout.fillWidth: true
            placeholderText: "e.g. Anantnag"
            maximumLength: 128
            onAccepted: dialog.submit()
        }
    }
    ColumnLayout {
        Layout.fillWidth: true
        spacing: 5
        AppText { text: "Description (optional)"; font.weight: Font.Medium }
        AppTextArea { id: descField; Layout.fillWidth: true; Layout.preferredHeight: 64 }
    }

    footer: [
        Item { Layout.fillWidth: true },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: dialog.close() },
        AppButton {
            text: dialog.pending ? "Saving…" : dialog.groupId > 0 ? "Save" : "Create"
            enabled: nameField.text.trim() !== "" && !dialog.pending
            onClicked: dialog.submit()
        }
    ]
}
