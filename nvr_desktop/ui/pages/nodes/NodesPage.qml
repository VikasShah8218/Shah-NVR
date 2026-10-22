import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Port of nvr_client/src/features/nodes/NodesPage.tsx: totals + per-node resources table.
PageScroll {
    id: root

    readonly property var t: Nodes.totals
    readonly property var columns: [
        { title: "Node", width: 230 },
        { title: "CPU", width: 140 },
        { title: "GPU", width: 170 },
        { title: "RAM", width: 160 },
        { title: "Storage (recordings / quota)", width: 0 },
        { title: "Cameras", width: 110 },
        { title: "Network in / out", width: 120 },
        { title: "", width: 36 }
    ]

    PageHeader {
        title: "Media Nodes"
        description: "Recording & streaming servers: resource usage, storage limits and state."
    }

    LoadingState { visible: Nodes.loading && Nodes.error === "" }
    ErrorState { text: Nodes.error }
    EmptyState {
        visible: !Nodes.loading && Nodes.error === "" && Nodes.listModel.count === 0
        iconName: "server"
        title: "No media nodes registered"
        text: "Start a media node (py main.py in media_node/); it registers itself with the central manager."
    }

    // ---------------------------------------------------------------- totals
    GridLayout {
        visible: Nodes.listModel.count > 0
        Layout.fillWidth: true
        columns: root.width > 1100 ? 5 : 3
        columnSpacing: 12
        rowSpacing: 12
        KpiCard {
            Layout.fillWidth: true
            iconName: "server"
            label: "Nodes healthy"
            value: root.t.healthy + " / " + root.t.nodes
            tone: root.t.healthy < root.t.nodes ? "warning" : "success"
        }
        KpiCard {
            Layout.fillWidth: true
            iconName: "cpu"
            label: "CPU (average)"
            value: Fmt.percent(root.t.cpuAverage)
            hint: root.t.cpuCores + " cores total"
        }
        KpiCard {
            Layout.fillWidth: true
            iconName: "memory-stick"
            label: "RAM in use"
            value: Fmt.bytes(root.t.memUsed)
            hint: "of " + Fmt.bytes(root.t.memTotal) + " (" + Fmt.percent(Fmt.ratio(root.t.memUsed, root.t.memTotal)) + ")"
        }
        KpiCard {
            Layout.fillWidth: true
            iconName: "hard-drive"
            label: "Recordings stored"
            value: Fmt.bytes(root.t.recordings)
            hint: (root.t.quota ? "quota " + Fmt.bytes(root.t.quota) + " · " : "") + "free disk " + Fmt.bytes(root.t.diskFree)
        }
        KpiCard {
            Layout.fillWidth: true
            iconName: "video"
            label: "Cameras placed"
            value: root.t.cameras + " / " + root.t.capacity
            hint: "assigned / total capacity"
        }
    }

    // ---------------------------------------------------------------- table
    Rectangle {
        visible: Nodes.listModel.count > 0
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
                model: Nodes.listModel
                delegate: TableRow {
                    id: row
                    required property var model
                    readonly property var r: model.res
                    readonly property bool stale: model.state === "UNREACHABLE" || model.state === "OFFLINE"
                    readonly property var gpu: r.gpus.length ? r.gpus[0] : null
                    clickable: true
                    onClicked: Router.go("node", model.id)

                    ColumnLayout {
                        spacing: 4
                        Layout.preferredWidth: root.columns[0].width
                        Layout.alignment: Qt.AlignTop
                        AppText { text: model.name; font.weight: Font.Medium; Layout.fillWidth: true }
                        StatusBadge { status: model.state }
                        AppText {
                            text: "heartbeat " + Fmt.timeAgo(model.last_heartbeat_at) + " · v" + (model.version ?? "?")
                                + " · MediaMTX " + (model.mediamtx_version ?? "?")
                            variant: "small"
                            font.pixelSize: 11
                            Layout.fillWidth: true
                        }
                    }
                    UsageMeter {
                        Layout.preferredWidth: root.columns[1].width
                        Layout.alignment: Qt.AlignTop
                        opacity: row.stale ? 0.5 : 1
                        alignValueLeft: true
                        value: Fmt.percent(r.cpuPercent) + (r.cpuCount ? " · " + r.cpuCount + " cores" : "")
                        percent: r.cpuPercent
                    }
                    Item {
                        Layout.preferredWidth: root.columns[2].width
                        Layout.alignment: Qt.AlignTop
                        implicitHeight: gpuMeter.visible ? gpuMeter.implicitHeight : 20
                        opacity: row.stale ? 0.5 : 1
                        UsageMeter {
                            id: gpuMeter
                            visible: row.gpu !== null
                            width: parent.width
                            alignValueLeft: true
                            value: row.gpu ? Fmt.percent(row.gpu.utilization_percent) : ""
                            percent: row.gpu ? row.gpu.utilization_percent : null
                            hint: row.gpu ? row.gpu.name + (row.gpu.memory_total_bytes
                                ? " · " + Fmt.bytes(row.gpu.memory_used_bytes) + " / " + Fmt.bytes(row.gpu.memory_total_bytes) : "") : ""
                        }
                        AppText {
                            visible: row.gpu === null
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "No GPU data"
                            variant: "small"
                        }
                    }
                    UsageMeter {
                        Layout.preferredWidth: root.columns[3].width
                        Layout.alignment: Qt.AlignTop
                        opacity: row.stale ? 0.5 : 1
                        alignValueLeft: true
                        value: Fmt.bytes(r.memUsed) + " / " + Fmt.bytes(r.memTotal)
                        percent: r.memPercent
                    }
                    UsageMeter {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        opacity: row.stale ? 0.5 : 1
                        alignValueLeft: true
                        value: r.quota !== null && r.quota !== undefined
                            ? Fmt.bytes(r.recordings) + " / " + Fmt.bytes(r.quota) + " (" + Fmt.percent(r.storagePercent) + ")"
                            : Fmt.bytes(r.recordings) + " · no quota"
                        percent: r.storagePercent
                        warnAt: 80
                        dangerAt: 95
                        hint: "disk free " + Fmt.bytes(r.diskFree) + " of " + Fmt.bytes(r.diskTotal) + " · usable " + Fmt.bytes(r.usable)
                    }
                    UsageMeter {
                        Layout.preferredWidth: root.columns[5].width
                        Layout.alignment: Qt.AlignTop
                        alignValueLeft: true
                        value: model.assigned_cameras + " / " + model.capacity_cameras
                        percent: r.camerasPercent
                    }
                    ColumnLayout {
                        spacing: 2
                        Layout.preferredWidth: root.columns[6].width
                        Layout.alignment: Qt.AlignTop
                        AppText { text: "↓ " + Fmt.mbps(r.netRx); font.pixelSize: Theme.textXs }
                        AppText { text: "↑ " + Fmt.mbps(r.netTx); variant: "small" }
                    }
                    NodeActions { nodeId: model.id; Layout.preferredWidth: root.columns[7].width }
                }
            }
        }
    }
}
