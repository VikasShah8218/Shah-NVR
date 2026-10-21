import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Port of nvr_client/src/features/dashboard/DashboardPage.tsx
PageScroll {
    id: root

    readonly property var k: Dashboard.kpis

    PageHeader {
        title: "Dashboard"
        description: "Cluster overview: cameras, recording health and media nodes."
    }

    LoadingState { visible: Cluster.loading && !Cluster.online && Cluster.error === "" }
    ErrorState { text: Cluster.error }

    // ---------------------------------------------------------------- KPI tiles
    GridLayout {
        visible: Cluster.online
        Layout.fillWidth: true
        columns: root.width > 1100 ? 5 : 3
        columnSpacing: 12
        rowSpacing: 12

        KpiCard {
            Layout.fillWidth: true
            iconName: "video"
            label: "Cameras"
            value: root.k.camerasTotal ?? 0
            hint: (root.k.camerasEnabled ?? 0) + " enabled"
        }
        KpiCard {
            Layout.fillWidth: true
            iconName: "circle-check-big"
            label: "Recording"
            value: (root.k.recording ?? 0) + " / " + (root.k.recordStreams ?? 0)
            hint: "recorded streams healthy"
            tone: (root.k.recording ?? 0) < (root.k.recordStreams ?? 0) ? "warning" : "success"
        }
        KpiCard {
            Layout.fillWidth: true
            iconName: "server"
            label: "Nodes healthy"
            value: (root.k.nodesHealthy ?? 0) + " / " + (root.k.nodesTotal ?? 0)
            tone: (root.k.nodesHealthy ?? 0) < (root.k.nodesTotal ?? 0) ? "danger" : "success"
        }
        KpiCard {
            Layout.fillWidth: true
            iconName: "database"
            label: "Chunks last hour"
            value: root.k.segmentsLastHour ?? 0
            hint: (root.k.segmentsTotal ?? 0) + " in catalog"
        }
        KpiCard {
            Layout.fillWidth: true
            iconName: "hard-drive"
            label: "Recordings stored"
            value: Fmt.bytes(root.k.storage ?? 0)
            hint: "ingest " + Fmt.mbps(root.k.ingress ?? 0)
        }
    }

    // ---------------------------------------------------------------- alerts + streams by status
    RowLayout {
        visible: Cluster.online
        Layout.fillWidth: true
        spacing: 20

        Card {
            Layout.fillWidth: true
            Layout.preferredWidth: 2
            Layout.alignment: Qt.AlignTop
            padding: 20

            RowLayout {
                spacing: 8
                Icon { name: "triangle-alert"; color: Theme.warning; size: 16 }
                AppText { text: "Alerts"; font.pixelSize: Theme.textLg; font.weight: Font.Medium }
                AppText { text: "(" + Dashboard.alerts.count + ")"; variant: "muted" }
            }

            Rectangle {
                visible: Dashboard.alerts.count === 0
                Layout.fillWidth: true
                implicitHeight: 48
                radius: Theme.radius
                color: Theme.alpha(Theme.success, 0.1)
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    spacing: 8
                    Icon { name: "circle-check-big"; color: Theme.success; size: 16 }
                    AppText { text: "All cameras are recording and all nodes are healthy."; color: Theme.success; Layout.fillWidth: true }
                }
            }

            Repeater {
                model: Dashboard.alerts
                delegate: Rectangle {
                    required property string level
                    required property string title
                    required property string detail
                    required property string page
                    required property var tab
                    required property int index
                    required property var model
                    Layout.fillWidth: true
                    implicitHeight: 52
                    color: area.containsMouse ? Theme.alpha(Theme.accent, 0.4) : "transparent"
                    radius: Theme.radiusSm
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 4
                        spacing: 12
                        Icon { name: "circle-alert"; size: 16; color: level === "danger" ? Theme.danger : Theme.warning; Layout.alignment: Qt.AlignTop; Layout.topMargin: 10 }
                        ColumnLayout {
                            spacing: 2
                            Layout.fillWidth: true
                            AppText { text: title; font.weight: Font.Medium; Layout.fillWidth: true }
                            AppText { text: detail; variant: "small"; Layout.fillWidth: true }
                        }
                    }
                    Rectangle { visible: index > 0; width: parent.width; height: 1; color: Theme.border }
                    MouseArea {
                        id: area
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: Router.go(page, model.id, tab ? { tab: tab } : {})
                    }
                }
            }
        }

        Card {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            padding: 20

            AppText { text: "Camera streams by status"; font.pixelSize: Theme.textLg; font.weight: Font.Medium }
            AppText { visible: Cluster.streamsByStatus.length === 0; text: "No cameras yet."; variant: "muted" }
            Repeater {
                model: Cluster.streamsByStatus
                delegate: ColumnLayout {
                    required property var modelData
                    readonly property int total: Cluster.streamsByStatus.reduce((a, s) => a + s.count, 0)
                    Layout.fillWidth: true
                    spacing: 6
                    RowLayout {
                        Layout.fillWidth: true
                        StatusBadge { status: modelData.status }
                        Item { Layout.fillWidth: true }
                        AppText { text: modelData.count }
                    }
                    UsageBar { Layout.fillWidth: true; percent: modelData.count / Math.max(1, total) * 100; warnAt: 101; dangerAt: 101 }
                }
            }
        }
    }

    // ---------------------------------------------------------------- node cards
    AppText { visible: Cluster.online; text: "Media nodes"; variant: "muted"; font.weight: Font.Medium }
    GridLayout {
        visible: Cluster.online
        Layout.fillWidth: true
        columns: root.width > 1100 ? 3 : 2
        columnSpacing: 16
        rowSpacing: 16
        Repeater {
            model: Nodes.listModel
            delegate: Card {
                required property var model // node row; read as model.state (`state` is a built-in QML property)
                required property int id
                required property string name
                required property var res
                required property int assigned_cameras
                required property int capacity_cameras
                required property var last_heartbeat_at
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                spacing: 12

                RowLayout {
                    Layout.fillWidth: true
                    AppText { text: name; font.weight: Font.Medium; Layout.fillWidth: true }
                    StatusBadge { status: model.state }
                }
                UsageMeter { Layout.fillWidth: true; label: "CPU"; value: Fmt.percent(res.cpuPercent); percent: res.cpuPercent }
                UsageMeter {
                    Layout.fillWidth: true
                    label: "RAM"
                    value: Fmt.bytes(res.memUsed) + " / " + Fmt.bytes(res.memTotal)
                    percent: res.memPercent
                }
                UsageMeter {
                    Layout.fillWidth: true
                    label: "Storage"
                    value: res.quota !== null && res.quota !== undefined
                        ? Fmt.bytes(res.recordings) + " / " + Fmt.bytes(res.quota)
                        : Fmt.bytes(res.recordings) + " (disk " + Fmt.percent(res.diskPercent) + ")"
                    percent: res.storagePercent
                    warnAt: 80
                    dangerAt: 95
                }
                RowLayout {
                    Layout.fillWidth: true
                    AppText { text: assigned_cameras + " / " + capacity_cameras + " cameras"; variant: "small" }
                    Item { Layout.fillWidth: true }
                    AppText { text: "heartbeat " + Fmt.timeAgo(last_heartbeat_at); variant: "small" }
                }
                TapHandler { onTapped: Router.go("node", id) }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
            }
        }
    }
}
