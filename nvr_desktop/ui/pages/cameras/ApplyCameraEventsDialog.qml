import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Switch camera events (ONVIF motion / tamper / inputs) on or off for a group or selected cameras
// (port of nvr_client/src/features/cameras/ApplyCameraEventsDialog.tsx; docs/DESKTOP_ONVIF_EVENTS_PLAN.md).
AppDialog {
    id: dialog
    objectName: "applyCameraEventsDialog"

    readonly property var allKinds: [
        { kind: "motion", title: "Motion", hint: "The camera's own motion detection" },
        { kind: "tamper", title: "Tamper", hint: "Lens covered, blurred or camera turned" },
        { kind: "digital_input", title: "Digital inputs", hint: "Door contacts, alarm panels, buttons wired to the camera" }]
    property int groupId: 0
    property string groupName: ""
    property var cameraIds: []
    property bool enabledOn: true
    property var kinds: ["motion", "tamper", "digital_input"]
    property bool includeSubgroups: true
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
        enabledOn = true
        kinds = allKinds.map(k => k.kind)
        includeSubgroups = true
        pending = false
        open()
    }
    function setKind(kind, on) {
        kinds = allKinds.map(k => k.kind).filter(k => k === kind ? on : kinds.indexOf(k) >= 0)
    }

    width: Math.min(520, parent ? parent.width - 40 : 520)
    title: "Camera events"
    description: groupId > 0
        ? 'Motion, tamper and inputs from every camera in "' + groupName + '" (cameras with ONVIF).'
        : "Motion, tamper and inputs from the " + cameraIds.length + " selected camera" + (cameraIds.length === 1 ? "" : "s") + " (cameras with ONVIF)."

    Connections {
        target: Groups
        function onCameraEventsApplied() {
            if (!dialog.pending)
                return
            dialog.pending = false
            dialog.close()
            dialog.done()
        }
        function onFailed() { dialog.pending = false }
    }

    component SwitchRow: Rectangle {
        id: row
        property string title: ""
        property string hint: ""
        property bool checked: false
        property string name: ""
        signal toggled(bool on)
        Layout.fillWidth: true
        implicitHeight: rowLayout.implicitHeight + 18
        radius: Theme.radiusSm
        color: "transparent"
        border.color: Theme.border
        RowLayout {
            id: rowLayout
            anchors.fill: parent
            anchors.margins: 9
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 12
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                AppText { text: row.title; Layout.fillWidth: true }
                AppText { visible: row.hint !== ""; text: row.hint; variant: "small"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
            AppSwitch {
                objectName: row.name
                checked: row.checked
                // a click breaks the binding: hand the value up, then follow the row again
                onToggled: { row.toggled(checked); checked = Qt.binding(() => row.checked) }
            }
        }
    }

    SwitchRow {
        name: "applyEventsEnabled"
        title: "Use camera events"
        checked: dialog.enabledOn
        onToggled: on => dialog.enabledOn = on
    }
    Repeater {
        model: dialog.enabledOn ? dialog.allKinds : []
        delegate: SwitchRow {
            required property var modelData
            name: "applyEventKind_" + modelData.kind
            title: modelData.title
            hint: modelData.hint
            checked: dialog.kinds.indexOf(modelData.kind) >= 0
            onToggled: on => dialog.setKind(modelData.kind, on)
        }
    }
    SwitchRow {
        visible: dialog.groupId > 0
        title: "Include sub-groups"
        hint: "Off: only cameras directly in this group."
        name: "applyEventsSubgroups"
        checked: dialog.includeSubgroups
        onToggled: on => dialog.includeSubgroups = on
    }
    AppText {
        Layout.fillWidth: true
        variant: "small"
        wrapMode: Text.WordWrap
        text: "Each camera's Camera events tab shows what it offers and whether events arrive."
    }

    footer: [
        Item { Layout.fillWidth: true },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: dialog.close() },
        AppButton {
            objectName: "applyCameraEvents"
            text: dialog.pending ? "Applying…" : "Apply"
            enabled: !dialog.pending && (!dialog.enabledOn || dialog.kinds.length > 0)
            onClicked: {
                dialog.pending = true
                Groups.applyCameraEvents(dialog.enabledOn, dialog.kinds, dialog.cameraIds, dialog.groupId,
                                         dialog.includeSubgroups)
            }
        }
    ]
}
