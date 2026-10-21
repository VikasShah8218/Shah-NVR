import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Port of nvr_client/src/features/nodes/NodeDetailPage.tsx
PageScroll {
    id: root
    objectName: "nodeDetail"

    function showTab(name) { NodeDetail.activeTab = name }

    readonly property var n: NodeDetail.node
    readonly property var r: n.res ?? ({})
    readonly property var s: NodeDetail.status

    Component.onCompleted: NodeDetail.nodeId = Router.id
    Component.onDestruction: NodeDetail.nodeId = 0
    Connections {
        target: Router
        function onChanged() { if (Router.page === "node") NodeDetail.nodeId = Router.id }
    }

    // back link
    Row {
        spacing: 4
        Icon { name: "arrow-left"; size: 16; color: Theme.mutedForeground; anchors.verticalCenter: parent.verticalCenter }
        AppText { text: "Media Nodes"; variant: "muted" }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: Router.go("nodes") }
    }

    LoadingState { visible: NodeDetail.loading && NodeDetail.error === "" }
    ErrorState { text: NodeDetail.error }

    PageHeader {
        visible: root.n.id !== undefined
        title: root.n.name ?? ""
        description: (root.n.api_url ?? "") + " · heartbeat " + Fmt.timeAgo(root.n.last_heartbeat_at)
        StatusBadge { status: root.n.state ?? ""; anchors.verticalCenter: parent.verticalCenter }
        NodeActions { nodeId: root.n.id ?? 0; asButton: true }
    }

    // which address clients get in every live / playback / download / VLC link
    Rectangle {
        visible: root.n.id !== undefined
        Layout.fillWidth: true
        implicitHeight: addressRow.implicitHeight + 20
        radius: Theme.radiusLg
        color: Theme.card
        border.color: Theme.border
        Flow {
            id: addressRow
            anchors.fill: parent
            anchors.margins: 10
            anchors.leftMargin: 16
            spacing: 16
            Row {
                spacing: 6
                AppText { text: "Clients connect to" }
                AppText { text: root.n.media_host ?? ""; font.family: Theme.mono; font.weight: Font.DemiBold }
                AppText { text: "(live, playback, downloads and VLC links)"; variant: "muted" }
            }
            AppText {
                visible: (root.r.otherAddresses ?? []).length > 0
                text: "Other LAN addresses of this PC: " + (root.r.otherAddresses ?? []).map(a => a.ip + " (" + a.interface + ")").join(", ")
                variant: "small"
            }
        }
    }

    // ---------------------------------------------------------------- summary cards
    RowLayout {
        visible: root.n.id !== undefined
        Layout.fillWidth: true
        spacing: 16

        Card {
            title: "Compute"
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            spacing: 12
            UsageMeter {
                Layout.fillWidth: true
                label: "CPU"
                value: Fmt.percent(root.r.cpuPercent) + (root.r.cpuCount ? " · " + root.r.cpuCount + " cores" : "")
                percent: root.r.cpuPercent
            }
            UsageMeter {
                Layout.fillWidth: true
                label: "RAM"
                value: Fmt.bytes(root.r.memUsed) + " / " + Fmt.bytes(root.r.memTotal)
                percent: root.r.memPercent
            }
            Repeater {
                model: root.r.gpus ?? []
                delegate: UsageMeter {
                    required property var modelData
                    Layout.fillWidth: true
                    label: "GPU · " + modelData.name
                    value: Fmt.percent(modelData.utilization_percent) + " · " + Fmt.bytes(modelData.memory_used_bytes) + " / " + Fmt.bytes(modelData.memory_total_bytes)
                    percent: modelData.utilization_percent
                }
            }
            FieldRow { visible: (root.r.gpus ?? []).length === 0; label: "GPU"; value: "No GPU data"; valueColor: Theme.mutedForeground }
            FieldRow { label: "Network"; value: "↓ " + Fmt.mbps(root.r.netRx) + " · ↑ " + Fmt.mbps(root.r.netTx) }
        }

        Card {
            title: "Storage"
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            spacing: 12
            UsageMeter {
                Layout.fillWidth: true
                label: (root.r.volumes ?? []).length > 1 ? "Recordings vs caps · " + root.r.volumes.length + " storages" : "Recordings vs cap"
                value: root.r.quota !== null && root.r.quota !== undefined
                    ? Fmt.bytes(root.r.recordings) + " / " + Fmt.bytes(root.r.quota)
                    : Fmt.bytes(root.r.recordings) + " · no cap"
                percent: root.r.storagePercent
                warnAt: 80
                dangerAt: 95
            }
            UsageMeter {
                Layout.fillWidth: true
                label: "Disk of the node's own folder"
                value: Fmt.bytes(root.r.diskFree) + " free of " + Fmt.bytes(root.r.diskTotal)
                percent: root.r.diskPercent
                warnAt: 85
                dangerAt: 95
            }
            FieldRow { label: "Usable for recordings"; value: Fmt.bytes(root.r.usable) }
            FieldRow { label: "Room left"; value: Fmt.bytes(root.r.remaining) }
            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true
                AppText { text: "Recording to"; variant: "muted" }
                AppText { text: root.r.writingVolume ? root.r.writingVolume.path : (root.s.recordings_dir ?? "—"); variant: "small"; wrapMode: Text.WrapAnywhere; elide: Text.ElideNone; Layout.fillWidth: true }
            }
        }

        Card {
            title: "Node agent"
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            spacing: 8
            ErrorState { text: NodeDetail.statusError }
            FieldRow {
                label: "Central connection"
                value: root.s.central_online === undefined ? "—" : root.s.central_online ? "Online" : "Offline"
                valueColor: root.s.central_online ? Theme.success : Theme.danger
            }
            FieldRow {
                label: "MediaMTX"
                value: root.s.mediamtx_running === undefined ? "—" : (root.s.mediamtx_running ? "Online " : "Offline ") + (root.s.mediamtx_version ?? "")
                valueColor: root.s.mediamtx_running ? Theme.success : Theme.danger
            }
            FieldRow { label: "Cameras assigned"; value: (root.n.assigned_cameras ?? 0) + " / " + (root.n.capacity_cameras ?? 0) }
            FieldRow { label: "Streams ready"; value: root.s.ready_paths ? root.s.ready_paths.length : "—" }
            FieldRow { label: "Chunks stored"; value: root.s.local_segments ?? "—" }
            FieldRow {
                label: "Pending uploads"
                value: root.s.pending_uploads ?? "—"
                valueColor: (root.s.pending_uploads ?? 0) > 20 ? Theme.warning : Theme.foreground
            }
            FieldRow { label: "Agent version"; value: root.n.version ?? "—" }
        }
    }

    // ---------------------------------------------------------------- live charts
    RowLayout {
        visible: root.n.id !== undefined
        Layout.fillWidth: true
        spacing: 16
        Card {
            title: "CPU & RAM (%)"
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            AreaChart {
                Layout.fillWidth: true
                Layout.preferredHeight: 190
                points: NodeDetail.history
                yMax: 100
                series: [{ key: "cpu", color: Theme.chart[0] }, { key: "mem", color: Theme.chart[3] }]
            }
        }
        Card {
            title: "Network (Mb/s)"
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            AreaChart {
                Layout.fillWidth: true
                Layout.preferredHeight: 190
                points: NodeDetail.history
                series: [{ key: "rx", color: Theme.chart[1] }, { key: "tx", color: Theme.chart[2] }]
            }
        }
    }

    // ---------------------------------------------------------------- tabs
    AppTabs {
        visible: root.n.id !== undefined
        options: [
            { value: "cameras", label: "Cameras" },
            { value: "storage", label: "Storage" },
            { value: "connectivity", label: "Connectivity" },
            { value: "onvif", label: "Virtual ONVIF" },
            { value: "paths", label: "MediaMTX paths" },
            { value: "chunks", label: "Recorded chunks" },
            { value: "logs", label: "Logs" }
        ]
        current: NodeDetail.activeTab
        onPicked: v => NodeDetail.activeTab = v
    }

    Loader {
        visible: root.n.id !== undefined
        Layout.fillWidth: true
        sourceComponent: ({ cameras: camerasTab, storage: storageTab, connectivity: connectivityTab, onvif: onvifTab, paths: pathsTab, chunks: chunksTab, logs: logsTab })[NodeDetail.activeTab]
    }

    // ---------------------------------------------------------------- tab contents
    Component {
        id: storageTab
        StorageTab { node: root.n }
    }

    Component {
        id: connectivityTab
        Card {
            title: "Client connectivity"
            spacing: 12
            AppText {
                text: "Public endpoints are shared node configuration. Which route this desktop uses is local: " + NodeDetail.route.toUpperCase() + " (" + NodeDetail.resolvedApiUrl + ")."
                variant: "muted"; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            AppText {
                text: "Forward the configured TCP ports and WebRTC UDP 8189 when browser WebRTC is required. Use HTTPS media endpoints when a public web client is served over HTTPS. Private heartbeats, assignments, and uploads remain unchanged."
                variant: "small"; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            AppSwitch { id: publicEnabled; text: "Enable public endpoints"; checked: root.n.public_enabled ?? false }
            RowLayout {
                Layout.fillWidth: true
                AppInput { id: publicApi; Layout.fillWidth: true; placeholderText: "Public API URL, e.g. http://122.168.244.70:7100"; text: root.n.public_api_url ?? "" }
                AppInput { id: publicHost; Layout.fillWidth: true; placeholderText: "Public media host or domain"; text: root.n.public_media_host ?? "" }
            }
            RowLayout {
                Layout.fillWidth: true
                AppInput { id: rtspPort; Layout.fillWidth: true; placeholderText: "RTSP port"; text: root.n.public_rtsp_port ?? "" }
                AppInput { id: hlsPort; Layout.fillWidth: true; placeholderText: "HLS port"; text: root.n.public_hls_port ?? "" }
                AppInput { id: webrtcPort; Layout.fillWidth: true; placeholderText: "WebRTC port"; text: root.n.public_webrtc_port ?? "" }
                AppSwitch { id: mediaTls; text: "Media TLS"; checked: root.n.public_media_tls ?? false }
            }
            AppButton {
                text: "Save connectivity"
                onClicked: NodeDetail.saveConnectivity({
                    public_enabled: publicEnabled.checked, public_api_url: publicApi.text,
                    public_media_host: publicHost.text, public_rtsp_port: rtspPort.text,
                    public_hls_port: hlsPort.text, public_webrtc_port: webrtcPort.text,
                    public_media_tls: mediaTls.checked
                })
            }
        }
    }

    Component {
        id: onvifTab
        ColumnLayout {
            id: onvifPane
            readonly property var o: NodeDetail.onvif
            spacing: 12
            ErrorState { text: NodeDetail.tabError }
            Card {
                title: "Virtual ONVIF NVR"
                Layout.fillWidth: true
                spacing: 10
                AppSwitch { id: onvifEnabled; text: "Advertise this node as an ONVIF device"; checked: onvifPane.o.enabled ?? false }
                AppText {
                    visible: !onvifPane.o.credentials_configured
                    text: "Configure ONVIF_SERVER_USERNAME and ONVIF_SERVER_PASSWORD in the media-node environment before enabling external access. Passwords are never sent to this desktop."
                    color: Theme.warning; wrapMode: Text.WordWrap; Layout.fillWidth: true
                }
                AppInput { id: discoveryName; Layout.fillWidth: true; placeholderText: "Discovery name"; text: onvifPane.o.discovery_name ?? "Shah-NVR" }
                AppInput { id: location; Layout.fillWidth: true; placeholderText: "Location (optional)"; text: onvifPane.o.location ?? "" }
                Flow {
                    Layout.fillWidth: true; spacing: 18
                    FieldRow { label: "Status"; value: onvifPane.o.status ?? "unknown" }
                    FieldRow { label: "Credentials"; value: onvifPane.o.credentials_configured ? "Configured" : "Not configured" }
                    FieldRow { label: "Profiles"; value: onvifPane.o.exposed_profiles ?? 0 }
                }
                FieldRow { label: "SOAP endpoint"; value: onvifPane.o.xaddr ?? "—" }
                FieldRow { label: "RTSP gateway"; value: onvifPane.o.rtsp_address ?? "—" }
                AppText { visible: !!onvifPane.o.last_error; text: onvifPane.o.last_error ?? ""; color: Theme.danger; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                AppButton { text: "Save ONVIF server"; onClicked: NodeDetail.saveOnvifServer(onvifEnabled.checked, discoveryName.text, location.text) }
            }
            Card {
                title: "Exposed cameras"
                Layout.fillWidth: true
                AppText { text: "Only selected cameras are enumerated to external VMS clients. Credentials remain hidden."; variant: "muted" }
                Repeater {
                    model: NodeDetail.assignedCameras
                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        AppText { text: modelData.name; Layout.fillWidth: true }
                        AppText { text: (modelData.streams ?? []).length + " profiles"; variant: "small" }
                        AppSwitch { checked: modelData.expose_via_onvif ?? false; onToggled: NodeDetail.setCameraExposure(modelData.id, checked) }
                    }
                }
            }
        }
    }

    Component {
        id: camerasTab
        ColumnLayout {
            spacing: 8
            ErrorState { text: NodeDetail.tabError }
            EmptyState { visible: NodeDetail.tabError === "" && NodeDetail.tabData.length === 0; title: "No cameras on this node" }
            TableCard {
                visible: NodeDetail.tabData.length > 0
                columns: [{ title: "Camera", width: 0 }, { title: "Generation", width: 140 }, { title: "Streams", width: 360 }]
                rows: NodeDetail.tabData
                rowDelegate: Component {
                    TableRow {
                        required property var modelData
                        clickable: true
                        onClicked: Router.go("camera", modelData.camera_id)
                        AppText { text: modelData.camera_name; font.weight: Font.Medium; Layout.fillWidth: true }
                        AppText { text: modelData.generation; Layout.preferredWidth: 140 }
                        Row {
                            spacing: 6
                            Layout.preferredWidth: 360
                            Repeater {
                                model: modelData.streams
                                delegate: Rectangle {
                                    required property var modelData
                                    implicitWidth: chip.implicitWidth + 16
                                    implicitHeight: 22
                                    radius: 11
                                    color: Theme.secondary
                                    AppText { id: chip; anchors.centerIn: parent; font.pixelSize: Theme.textXs; text: modelData.profile + (modelData.record ? " · rec" : " · live") }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Component {
        id: pathsTab
        ColumnLayout {
            spacing: 8
            ErrorState { text: NodeDetail.tabError }
            EmptyState { visible: NodeDetail.tabError === "" && NodeDetail.tabData.length === 0; title: "No active MediaMTX paths" }
            TableCard {
                visible: NodeDetail.tabData.length > 0
                columns: [
                    { title: "Path", width: 0 }, { title: "State", width: 120 }, { title: "Tracks", width: 110 },
                    { title: "Viewers", width: 80 }, { title: "Received", width: 110 }, { title: "Sent", width: 110 },
                    { title: "Online since", width: 140 }
                ]
                rows: NodeDetail.tabData
                rowDelegate: Component {
                    TableRow {
                        required property var modelData
                        AppText { text: modelData.name; variant: "mono"; Layout.fillWidth: true }
                        Item { Layout.preferredWidth: 120; implicitHeight: 22; StatusBadge { status: modelData.ready ? "STREAMING" : "CONNECTING" } }
                        AppText { text: modelData.tracks; Layout.preferredWidth: 110 }
                        AppText { text: modelData.readers; Layout.preferredWidth: 80 }
                        AppText { text: Fmt.bytes(modelData.bytesReceived); Layout.preferredWidth: 110 }
                        AppText { text: Fmt.bytes(modelData.bytesSent); Layout.preferredWidth: 110 }
                        AppText { text: modelData.readyTime ? Fmt.timeAgo(modelData.readyTime) : "—"; variant: "small"; Layout.preferredWidth: 140 }
                    }
                }
            }
        }
    }

    Component {
        id: chunksTab
        ColumnLayout {
            spacing: 8
            ErrorState { text: NodeDetail.tabError }
            EmptyState { visible: NodeDetail.tabError === "" && NodeDetail.tabData.length === 0; title: "No recorded chunks yet" }
            TableCard {
                visible: NodeDetail.tabData.length > 0
                columns: [
                    { title: "Start", width: 190 }, { title: "Camera", width: 0 }, { title: "Length", width: 90 },
                    { title: "Size", width: 100 }, { title: "Codec", width: 80 }, { title: "Parts", width: 60 },
                    { title: "Uploaded", width: 90 }, { title: "", width: 36 }
                ]
                rows: NodeDetail.tabData
                rowDelegate: Component {
                    TableRow {
                        required property var modelData
                        AppText { text: Fmt.dateTime(modelData.start_time); Layout.preferredWidth: 190 }
                        AppText { text: "cam-" + modelData.camera_id + "/" + modelData.profile; Layout.fillWidth: true }
                        AppText { text: Fmt.duration(modelData.duration_ms); Layout.preferredWidth: 90 }
                        AppText { text: Fmt.bytes(modelData.size_bytes); Layout.preferredWidth: 100 }
                        AppText { text: modelData.codec ?? "—"; Layout.preferredWidth: 80 }
                        AppText { text: modelData.part_count; Layout.preferredWidth: 60 }
                        AppText {
                            text: modelData.uploaded ? "In catalog" : "Pending"
                            color: modelData.uploaded ? Theme.success : Theme.warning
                            font.pixelSize: Theme.textXs
                            Layout.preferredWidth: 90
                        }
                        AppButton {
                            variant: "ghost"; size: "icon"; iconName: "download"; tip: "Download MP4"
                            Layout.preferredWidth: 36
                            onClicked: NodeDetail.download(modelData)
                        }
                    }
                }
            }
        }
    }

    Component {
        id: logsTab
        Card { LogViewer { Layout.fillWidth: true } }
    }
}
