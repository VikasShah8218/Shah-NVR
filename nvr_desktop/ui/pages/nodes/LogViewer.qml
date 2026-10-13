import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Live node logs (port of LogViewer.tsx): Agent/MediaMTX, All/Warnings+/Errors, filter, pause, copy.
ColumnLayout {
    id: viewer

    property string level: "all"
    readonly property var lines: NodeDetail.logs.filter(l =>
        (level === "all" || (level === "error" ? l.level === "error" : l.level !== "info"))
        && (filter.text === "" || l.text.toLowerCase().includes(filter.text.toLowerCase())))

    spacing: 10

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        ToggleGroup {
            options: [{ value: "agent", label: "Agent" }, { value: "mediamtx", label: "MediaMTX" }]
            value: NodeDetail.logSource
            onPicked: v => NodeDetail.logSource = v
        }
        ToggleGroup {
            options: [{ value: "all", label: "All" }, { value: "warn", label: "Warnings+" }, { value: "error", label: "Errors" }]
            value: viewer.level
            onPicked: v => viewer.level = v
        }
        Item { Layout.fillWidth: true }
        AppInput { id: filter; iconName: "search"; placeholderText: "Filter…"; implicitWidth: 220; implicitHeight: 32 }
        AppButton {
            variant: "outline"
            size: "sm"
            iconName: NodeDetail.logsPaused ? "play" : "pause"
            text: NodeDetail.logsPaused ? "Resume" : "Pause"
            onClicked: NodeDetail.logsPaused = !NodeDetail.logsPaused
        }
        AppButton {
            variant: "outline"
            size: "sm"
            iconName: "copy"
            text: "Copy"
            onClicked: Utils.copy(viewer.lines.map(l => l.text).join("\n"), "Copied " + viewer.lines.length + " lines")
        }
    }

    ErrorState { text: NodeDetail.tabError }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: 440
        radius: Theme.radius
        color: Theme.video
        border.color: Theme.border

        ListView {
            id: list
            anchors.fill: parent
            anchors.margins: 12
            clip: true
            model: viewer.lines
            ScrollBar.vertical: AppScrollBar {}
            onCountChanged: if (!NodeDetail.logsPaused) positionViewAtEnd()
            delegate: Text {
                required property var modelData
                width: list.width - 12
                text: modelData.text
                wrapMode: Text.WrapAnywhere
                color: modelData.level === "error" ? Theme.danger : modelData.level === "warn" ? Theme.warning : Theme.alpha(Theme.foreground, 0.85)
                font.family: Theme.mono
                font.pixelSize: 12
                lineHeight: 1.25
            }
        }
        AppText {
            visible: viewer.lines.length === 0
            anchors.centerIn: parent
            text: "No log lines."
            variant: "muted"
        }
    }

    AppText {
        text: viewer.lines.length + " lines " + (NodeDetail.logsPaused ? "· paused" : "· refreshing every 3 s")
        variant: "small"
    }
}
