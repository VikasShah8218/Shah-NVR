import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Port of nvr_client/src/features/assignments/AssignmentsPage.tsx
PageScroll {
    id: root

    property double now: Date.now()
    readonly property var columns: [
        { title: "Camera", width: 0 }, { title: "Media node", width: 200 }, { title: "Generation", width: 110 },
        { title: "Lease", width: 90 }, { title: "Reason", width: 140 }, { title: "Updated", width: 150 }, { title: "", width: 200 }
    ]

    Timer { interval: 1000; running: true; repeat: true; onTriggered: root.now = Date.now() }

    PageHeader {
        title: "Assignments"
        description: "Which media node records each camera. The scheduler places cameras automatically and moves them on failure."
        AppButton { text: "Run scheduler now"; variant: "outline"; iconName: "play"; onClicked: Assignments.runScheduler() }
    }

    LoadingState { visible: Assignments.loading && Assignments.error === "" }
    ErrorState { text: Assignments.error }
    EmptyState {
        visible: !Assignments.loading && Assignments.error === "" && Assignments.listModel.count === 0
        title: "No assignments yet"
        text: "Add a camera and start a media node."
    }

    Rectangle {
        visible: Assignments.listModel.count > 0
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
                model: Assignments.listModel
                delegate: TableRow {
                    required property var model
                    readonly property int leftSeconds: model.lease_expires_at
                        ? Math.round((new Date(model.lease_expires_at).getTime() - root.now) / 1000) : NaN

                    Item {
                        Layout.fillWidth: true
                        implicitHeight: cameraLink.implicitHeight
                        LinkText {
                            id: cameraLink
                            text: model.camera_name
                            font.weight: Font.Medium
                            width: Math.min(implicitWidth, parent.width)
                            onActivated: Router.go("camera", model.camera_id)
                        }
                    }
                    Item {
                        Layout.preferredWidth: 200
                        implicitHeight: nodeLink.implicitHeight
                        LinkText {
                            id: nodeLink
                            text: model.node_name ?? "unassigned"
                            active: !!model.node_id
                            color: !model.node_id ? Theme.mutedForeground : active && hovered ? Theme.primary : Theme.foreground
                            width: Math.min(implicitWidth, parent.width)
                            onActivated: Router.go("node", model.node_id)
                        }
                    }
                    AppText { text: model.generation; Layout.preferredWidth: 110 }
                    AppText {
                        text: isNaN(leftSeconds) ? "—" : leftSeconds >= 0 ? leftSeconds + "s" : "expired"
                        color: leftSeconds < 0 ? Theme.warning : Theme.foreground
                        Layout.preferredWidth: 90
                    }
                    AppText { text: model.reason ?? "—"; Layout.preferredWidth: 140 }
                    AppText { text: Fmt.timeAgo(model.updated_at); variant: "small"; Layout.preferredWidth: 150 }
                    Row {
                        spacing: 4
                        Layout.preferredWidth: 200
                        layoutDirection: Qt.RightToLeft
                        AppButton {
                            text: "Move"; iconName: "arrow-left-right"; variant: "ghost"; size: "sm"
                            onClicked: moveDialog.openFor(model.camera_id, model.camera_name, model.node_id)
                        }
                        AppButton {
                            text: "History"; iconName: "history"; variant: "ghost"; size: "sm"
                            onClicked: {
                                historySheet.cameraName = model.camera_name
                                Assignments.loadHistory(model.camera_id)
                                historySheet.open()
                            }
                        }
                    }
                }
            }
        }
    }

    MoveCameraDialog {
        id: moveDialog
        onMoveRequested: (cameraId, nodeId) => Assignments.move(cameraId, nodeId)
    }

    Sheet {
        id: historySheet
        property string cameraName: ""
        title: "Ownership history"
        description: cameraName + ": every move between media nodes."
        width: 480

        Repeater {
            model: Assignments.history
            delegate: RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: 12
                Rectangle {
                    width: 12
                    height: 12
                    radius: 6
                    color: modelData.ended_at ? Theme.mutedForeground : Theme.success
                    Layout.alignment: Qt.AlignTop
                    Layout.topMargin: 4
                }
                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true
                    AppText {
                        textFormat: Text.StyledText
                        text: "<b>Generation " + modelData.generation + " → node " + (modelData.node_id ?? "—") + "</b> <font color='"
                            + Theme.mutedForeground + "'>(" + modelData.reason + ")</font>"
                        Layout.fillWidth: true
                    }
                    AppText {
                        text: Fmt.dateTime(modelData.started_at) + " — " + (modelData.ended_at ? Fmt.dateTime(modelData.ended_at) : "now")
                        variant: "small"
                    }
                }
            }
        }
    }
}
