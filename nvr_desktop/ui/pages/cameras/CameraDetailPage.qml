import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"
import "../../video"
import "../assignments"

// Port of nvr_client/src/features/cameras/CameraDetailPage.tsx:
// tabs Overview / Device (ONVIF) / Video / Recordings / Assignment.
PageScroll {
    id: root
    objectName: "cameraDetail"

    readonly property var c: CameraDetail.camera
    readonly property bool ready: c.id !== undefined
    property string tab: Router.params && Router.params.tab ? Router.params.tab : "overview"
    property string previewProfile: ""
    property double now: Date.now()

    function showTab(name) { tab = name }

    Component.onCompleted: {
        CameraDetail.cameraId = Router.id
    }
    Component.onDestruction: CameraDetail.cameraId = 0
    Connections {
        target: Router
        function onChanged() {
            if (Router.page === "camera") {
                CameraDetail.cameraId = Router.id
                root.tab = Router.params && Router.params.tab ? Router.params.tab : "overview"
            }
        }
    }
    Connections {
        target: CameraDetail
        function onCameraIdChanged() { root.previewProfile = "" }
        function onCameraChanged() {
            if (root.previewProfile === "" && root.ready && root.c.streams.length > 0)
                root.previewProfile = root.c.streams[0].profile
        }
    }
    Timer { interval: 1000; running: root.tab === "assignment"; repeat: true; onTriggered: root.now = Date.now() }

    // back link
    Row {
        spacing: 4
        Icon { name: "arrow-left"; size: 16; color: Theme.mutedForeground; anchors.verticalCenter: parent.verticalCenter }
        AppText { text: "Cameras"; variant: "muted" }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: Router.go("cameras") }
    }

    LoadingState { visible: CameraDetail.loading && CameraDetail.error === "" }
    ErrorState { text: CameraDetail.error }

    PageHeader {
        visible: root.ready
        title: root.c.name ?? ""
        description: root.c.description || ("Camera #" + (root.c.id ?? ""))
        StatusBadge { visible: root.ready && !root.c.enabled; status: "DISABLED"; anchors.verticalCenter: parent.verticalCenter }
        AppButton {
            text: "Recordings"; iconName: "history"; variant: "outline"
            onClicked: Router.go("playback", 0, { camera: root.c.id })
        }
        AppButton { text: "Edit"; iconName: "pencil"; onClicked: form.openFor(root.c) }
    }

    AppTabs {
        visible: root.ready
        options: [{ value: "overview", label: "Overview" }, { value: "device", label: "Device" }, { value: "video", label: "Video" }, { value: "recordings", label: "Recordings" }, { value: "assignment", label: "Assignment" }]
        current: root.tab
        onPicked: v => {
            root.tab = v
        }
    }

    // ================================================================= Overview
    ColumnLayout {
        visible: root.ready && root.tab === "overview"
        Layout.fillWidth: true
        spacing: 16

        RowLayout {
            Layout.fillWidth: true
            spacing: 16

            Card {
                title: "Live preview"
                Layout.fillWidth: true
                Layout.preferredWidth: 3
                Layout.alignment: Qt.AlignTop
                spacing: 12
                headerRight: ToggleGroup {
                    options: (root.c.streams ?? []).map(s => s.profile)
                    value: root.previewProfile
                    onPicked: v => root.previewProfile = v
                }

                VideoView {
                    id: preview
                    // Re-evaluated whenever the live URLs refresh (liveChanged).
                    readonly property var urls: {
                        CameraDetail.live
                        return CameraDetail.previewSources(root.previewProfile, Prefs.liveProtocol)
                    }
                    readonly property bool active: root.ready && root.c.enabled && root.tab === "overview" && root.visible
                    Layout.fillWidth: true
                    Layout.preferredHeight: width * 9 / 16
                    radius: Theme.radiusSm
                    source: active ? urls.source : ""
                    fallbackSource: active ? urls.fallback : ""
                    waitingText: !root.c.enabled ? "Camera is disabled" : urls.error !== "" ? urls.error : "Loading stream URLs…"
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 2
                Layout.alignment: Qt.AlignTop
                spacing: 16

                Card {
                    title: "Details"
                    Layout.fillWidth: true
                    spacing: 8
                    FieldRow {
                        label: "Media node"
                        LinkText {
                            readonly property var a: root.c.assignment
                            text: a && a.node_id ? a.node_name : "Not assigned"
                            active: !!(a && a.node_id)
                            onActivated: Router.go("node", a.node_id)
                        }
                    }
                    FieldRow { label: "Username"; value: root.c.username ?? "—" }
                    FieldRow { label: "Password"; value: root.c.has_password ? "Set" : "Not set" }
                    FieldRow { label: "Keep recordings"; value: Fmt.retention(root.c.retention_days) }
                    FieldRow { label: "Added"; value: Fmt.dateTime(root.c.created_at) }
                }

                Card {
                    title: "Live URLs (for VLC)"
                    Layout.fillWidth: true
                    spacing: 8
                    AppText {
                        visible: CameraDetail.liveError !== ""
                        text: CameraDetail.liveError
                        variant: "muted"
                        wrapMode: Text.WordWrap
                        elide: Text.ElideNone
                        Layout.fillWidth: true
                    }
                    Repeater {
                        model: CameraDetail.live.streams ?? []
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 4
                            AppText { text: modelData.profile; variant: "small" }
                            Repeater {
                                model: [modelData.rtsp, modelData.hls]
                                delegate: RowLayout {
                                    required property string modelData
                                    Layout.fillWidth: true
                                    spacing: 4
                                    Rectangle {
                                        Layout.fillWidth: true
                                        implicitHeight: 26
                                        radius: 4
                                        color: Theme.muted
                                        AppText {
                                            anchors.fill: parent
                                            anchors.leftMargin: 8
                                            anchors.rightMargin: 8
                                            verticalAlignment: Text.AlignVCenter
                                            text: modelData
                                            variant: "mono"
                                        }
                                    }
                                    AppButton {
                                        variant: "ghost"; size: "icon"; iconName: "copy"; tip: "Copy"
                                        implicitWidth: 28; implicitHeight: 28
                                        onClicked: Utils.copy(modelData, "Copied")
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        TableCard {
            columns: [
                { title: "Stream", width: 90 }, { title: "Status", width: 200 }, { title: "Source URL", width: 0 },
                { title: "Record", width: 80 }, { title: "Transport", width: 80 }, { title: "Received", width: 90 },
                { title: "Last chunk", width: 110 }, { title: "Last report", width: 110 }
            ]
            rows: root.c.streams ?? []
            rowDelegate: TableRow {
                required property var modelData
                AppText { text: modelData.profile; font.weight: Font.Medium; Layout.preferredWidth: 90 }
                ColumnLayout {
                    spacing: 2
                    Layout.preferredWidth: 200
                    Layout.maximumWidth: 200
                    StatusBadge { status: modelData.status }
                    AppText {
                        visible: !!modelData.status_detail
                        text: modelData.status_detail ?? ""
                        variant: "small"
                        font.pixelSize: 11
                        Layout.fillWidth: true
                    }
                }
                AppText { text: modelData.source_url; variant: "mono"; Layout.fillWidth: true }
                AppText { text: modelData.record ? "Yes" : "Live only"; Layout.preferredWidth: 80 }
                AppText { text: modelData.rtsp_transport.toUpperCase(); Layout.preferredWidth: 80 }
                AppText { text: Fmt.bytes(modelData.bytes_received); Layout.preferredWidth: 90 }
                AppText {
                    text: modelData.last_segment_at ? Fmt.timeAgo(modelData.last_segment_at) : "—"
                    variant: "small"
                    Layout.preferredWidth: 110
                }
                AppText {
                    text: modelData.last_status_at ? Fmt.timeAgo(modelData.last_status_at) : "—"
                    variant: "small"
                    Layout.preferredWidth: 110
                }
            }
        }
    }

    // ================================================================= ONVIF device
    DeviceTab {
        visible: root.ready && root.tab === "device"
        Layout.fillWidth: true
        camera: root.c
        active: visible
    }

    // ================================================================= H2 video settings
    VideoTab {
        visible: root.ready && root.tab === "video"
        Layout.fillWidth: true
        camera: root.c
        active: visible
    }

    // ================================================================= Recordings
    Card {
        id: recordingsTab
        readonly property var rec: CameraDetail.recordings
        visible: root.ready && root.tab === "recordings"
        title: "Last 24 hours"
        Layout.fillWidth: true
        spacing: 12
        headerRight: ToggleGroup {
            options: (root.c.streams ?? []).map(s => s.profile)
            value: CameraDetail.recordingsProfile
            onPicked: v => CameraDetail.loadRecordings(v)
        }

        Timeline {
            Layout.fillWidth: true
            ranges: recordingsTab.rec.ranges ?? []
            ticks: recordingsTab.rec.ticks ?? []
            viewStart: recordingsTab.rec.viewStart ?? Date.now() - 86400000
            viewEnd: recordingsTab.rec.viewEnd ?? Date.now()
            onSeek: ms => Router.go("playback", 0, { camera: root.c.id, profile: CameraDetail.recordingsProfile, t: ms })
        }

        Flow {
            visible: recordingsTab.rec.coverage_percent !== undefined
            Layout.fillWidth: true
            spacing: 24
            Stat { label: "Coverage"; value: (recordingsTab.rec.coverage_percent ?? 0).toFixed(1) + "%" }
            Stat { label: "Chunks"; value: (recordingsTab.rec.segments ?? []).length }
            Stat { label: "Size"; value: Fmt.bytes(recordingsTab.rec.total_size_bytes) }
            Stat { label: "Gaps"; value: (recordingsTab.rec.gaps ?? []).length }
            AppText { text: "Click the bar to open playback at that time."; variant: "muted" }
        }
    }

    // ================================================================= Assignment
    RowLayout {
        id: assignmentTab
        readonly property var a: root.c.assignment
        readonly property int leaseLeft: a && a.lease_expires_at
            ? Math.round((new Date(a.lease_expires_at).getTime() - root.now) / 1000) : NaN
        visible: root.ready && root.tab === "assignment"
        Layout.fillWidth: true
        spacing: 16

        Card {
            title: "Current owner"
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            spacing: 8
            FieldRow { label: "Media node"; value: assignmentTab.a?.node_name ?? "Not assigned" }
            FieldRow { label: "Generation"; value: assignmentTab.a?.generation ?? 0 }
            FieldRow {
                readonly property int secondsLeft: assignmentTab.leaseLeft
                label: "Lease"
                value: isNaN(secondsLeft) ? "—" : secondsLeft >= 0 ? secondsLeft + "s left" : "expired " + (-secondsLeft) + "s ago"
                valueColor: secondsLeft < 0 ? Theme.warning : Theme.foreground
            }
            AppButton {
                Layout.fillWidth: true
                Layout.topMargin: 6
                text: "Move to another node"
                iconName: "arrow-left-right"
                variant: "outline"
                enabled: root.c.enabled ?? false
                onClicked: moveDialog.openFor(root.c.id, root.c.name, assignmentTab.a?.node_id ?? null)
            }
        }

        TableCard {
            Layout.preferredWidth: 2
            Layout.alignment: Qt.AlignTop
            columns: [
                { title: "Generation", width: 100 }, { title: "Node", width: 110 }, { title: "Reason", width: 0 },
                { title: "From", width: 170 }, { title: "Until", width: 170 }
            ]
            rows: CameraDetail.history
            rowDelegate: TableRow {
                required property var modelData
                AppText { text: modelData.generation; Layout.preferredWidth: 100 }
                AppText { text: modelData.node_id ? "node " + modelData.node_id : "—"; Layout.preferredWidth: 110 }
                AppText { text: modelData.reason; Layout.fillWidth: true }
                AppText { text: Fmt.dateTime(modelData.started_at); variant: "small"; Layout.preferredWidth: 170 }
                AppText {
                    text: modelData.ended_at ? Fmt.dateTime(modelData.ended_at) : "current"
                    variant: modelData.ended_at ? "small" : "body"
                    color: modelData.ended_at ? Theme.mutedForeground : Theme.success
                    Layout.preferredWidth: 170
                }
            }
        }
    }

    CameraFormSheet { id: form }
    MoveCameraDialog {
        id: moveDialog
        onMoveRequested: (cameraId, nodeId) => CameraDetail.moveTo(nodeId)
    }

    component Stat: Row {
        property string label: ""
        property var value
        spacing: 6
        AppText { text: label }
        AppText { text: String(value); font.weight: Font.DemiBold }
    }
}
