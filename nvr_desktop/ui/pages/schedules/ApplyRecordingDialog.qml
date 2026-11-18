import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Set the recording mode of a whole group (optionally with its sub-groups) or of selected cameras
// (port of nvr_client features/schedules/ApplyRecordingDialog.tsx).
AppDialog {
    id: dialog
    objectName: "applyRecordingDialog"

    property int groupId: 0
    property string groupName: ""
    property var cameraIds: []
    property bool pending: false
    signal done()

    function openForGroup(id, name) {
        groupId = id
        groupName = name
        cameraIds = []
        reset()
    }
    function openForCameras(ids) {
        groupId = 0
        groupName = ""
        cameraIds = ids
        reset()
    }
    function reset() {
        fields.mode = "schedule"
        fields.scheduleId = 0
        fields.events = Schedules.eventSettingsOf(null)
        subgroups.checked = true
        pending = false
        open()
    }

    width: Math.min(540, parent ? parent.width - 40 : 540)
    title: "Recording schedule"
    description: groupId > 0
        ? 'Set when every camera in "' + groupName + '" records. Cameras added to the group later keep their own setting.'
        : "Set when the " + cameraIds.length + " selected camera" + (cameraIds.length === 1 ? "" : "s") + " record."

    Connections {
        target: Schedules
        function onApplied(n) {
            if (!dialog.pending)
                return
            dialog.pending = false
            dialog.close()
            dialog.done()
        }
        function onFailed() { dialog.pending = false }
    }

    RecordingFields { id: fields; Layout.fillWidth: true }

    Rectangle {
        visible: dialog.groupId > 0
        Layout.fillWidth: true
        implicitHeight: subRow.implicitHeight + 20
        radius: Theme.radiusSm
        color: "transparent"
        border.color: Theme.border
        RowLayout {
            id: subRow
            anchors.fill: parent
            anchors.margins: 10
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                AppText { text: "Include sub-groups" }
                AppText { text: "Off: only cameras directly in this group."; variant: "small" }
            }
            AppSwitch { id: subgroups; checked: true }
        }
    }

    footer: [
        Item { Layout.fillWidth: true },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: dialog.close() },
        AppButton {
            objectName: "applyRecording"
            text: dialog.pending ? "Applying…" : "Apply"
            enabled: !dialog.pending && (fields.mode !== "schedule" || fields.scheduleId > 0) && fields.eventsValid
            onClicked: {
                dialog.pending = true
                Schedules.apply(fields.mode, fields.mode === "schedule" ? fields.scheduleId : 0,
                                dialog.cameraIds, dialog.groupId, subgroups.checked, fields.events)
            }
        }
    ]
}
