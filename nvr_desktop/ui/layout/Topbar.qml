import QtQuick
import QtQuick.Layouts
import App
import "../theme"
import "../components"

// Top bar (port of AppLayout.tsx Topbar): central status, nodes healthy, cameras recording, clock.
Rectangle {
    id: bar

    property date now: new Date()

    implicitHeight: 56
    color: Theme.alpha(Theme.card, 0.4)

    Timer { interval: 1000; running: true; repeat: true; onTriggered: bar.now = new Date() }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 20
        anchors.rightMargin: 20
        spacing: 20

        // central connection pill
        Rectangle {
            implicitHeight: 26
            implicitWidth: pill.implicitWidth + 24
            radius: 13
            color: Theme.muted
            Row {
                id: pill
                anchors.centerIn: parent
                spacing: 8
                Rectangle {
                    width: 8
                    height: 8
                    radius: 4
                    anchors.verticalCenter: parent.verticalCenter
                    color: Cluster.online ? Theme.success : Theme.danger
                    SequentialAnimation on opacity {
                        running: !Cluster.online
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.3; duration: 700 }
                        NumberAnimation { to: 1; duration: 700 }
                    }
                }
                AppText {
                    text: Cluster.online ? "Central online" : Cluster.loading ? "Connecting…" : "Central offline"
                    font.pixelSize: Theme.textXs
                }
            }
            AppToolTip { visible: hover.hovered; text: Prefs.centralUrl }
            HoverHandler { id: hover }
        }

        AppText {
            visible: Cluster.online
            textFormat: Text.StyledText
            color: Theme.mutedForeground
            text: "Nodes <font color='" + (Cluster.nodesHealthy < Cluster.nodesTotal ? Theme.warning : Theme.foreground) + "'><b>"
                + Cluster.nodesHealthy + "/" + Cluster.nodesTotal + "</b></font> healthy"
        }
        AppText {
            visible: Cluster.online
            textFormat: Text.StyledText
            color: Theme.mutedForeground
            text: "Cameras <font color='" + Theme.foreground + "'><b>" + Cluster.recording + "</b></font> recording of " + Cluster.camerasEnabled
        }

        Item { Layout.fillWidth: true }

        Row {
            spacing: 8
            Icon { name: "clock"; size: 16; color: Theme.mutedForeground; anchors.verticalCenter: parent.verticalCenter }
            AppText {
                text: Qt.formatTime(bar.now, "HH:mm:ss")
                color: Theme.mutedForeground
                font.features: { "tnum": 1 }
            }
        }
    }
}
