import QtQuick
import QtQuick.Layouts
import "../theme"

// Recording timeline (port of nvr_client/src/features/playback/Timeline.tsx): recorded ranges vs gaps
// for the visible window, local-time ticks, a "now" marker, a hover line and the playhead.
// Click to seek; drag to pan (when `pannable`). All times are epoch milliseconds.
ColumnLayout {
    id: timeline

    property var ranges: []        // [{a, b}] merged recorded ranges (features/playback/timeline.py)
    property var ticks: []         // [{t, label}] aligned to local time
    property double viewStart: 0
    property double viewEnd: 1
    property double boundsStart: viewStart
    property double boundsEnd: viewEnd
    property double playhead: -1   // < 0 = no playhead
    property bool pannable: false
    property int barHeight: 56
    signal seek(double ms)
    signal pan(double viewStart)

    readonly property double span: Math.max(1, viewEnd - viewStart)
    property double now: Date.now()
    property double hover: -1

    function xOf(t) { return (t - viewStart) / span * track.width }
    function timeAt(x) { return viewStart + x / track.width * span }
    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }

    spacing: 4

    Timer { interval: 5000; running: timeline.visible; repeat: true; onTriggered: timeline.now = Date.now() }

    Item {
        id: track
        Layout.fillWidth: true
        Layout.preferredHeight: timeline.barHeight
        clip: true

        readonly property int barTop: 18
        readonly property int barH: timeline.barHeight - 26

        // gaps (background)
        Rectangle { y: track.barTop; width: parent.width; height: track.barH; radius: 4; color: Theme.muted }

        // future (after now)
        Rectangle {
            readonly property real x0: Math.max(0, timeline.xOf(timeline.now))
            visible: timeline.now < timeline.viewEnd
            x: x0
            y: track.barTop
            width: parent.width - x0
            height: track.barH
            color: Theme.background
            opacity: 0.6
        }

        // recorded ranges
        Repeater {
            model: timeline.ranges.filter(r => r.b > timeline.viewStart && r.a < timeline.viewEnd)
            delegate: Rectangle {
                required property var modelData
                readonly property real x0: Math.max(0, timeline.xOf(modelData.a))
                x: x0
                y: track.barTop
                width: Math.max(1.5, timeline.xOf(Math.min(modelData.b, timeline.viewEnd)) - x0)
                height: track.barH
                color: Theme.success
                opacity: 0.75
            }
        }

        // ticks
        Repeater {
            model: timeline.ticks
            delegate: Item {
                required property var modelData
                readonly property real px: timeline.xOf(modelData.t)
                Rectangle { x: parent.px; y: 14; width: 1; height: timeline.barHeight - 22; color: Theme.border }
                Text {
                    text: modelData.label
                    color: Theme.mutedForeground
                    font.family: Theme.font
                    font.pixelSize: 10
                    y: 0
                    x: parent.px < 20 ? parent.px : parent.px > track.width - 20 ? parent.px - width : parent.px - width / 2
                }
            }
        }

        // now
        Column {
            visible: timeline.now > timeline.viewStart && timeline.now < timeline.viewEnd
            x: timeline.xOf(timeline.now)
            y: 14
            spacing: 3
            Repeater {
                model: Math.ceil((timeline.barHeight - 18) / 6)
                Rectangle { width: 1; height: 3; color: Theme.info }
            }
        }

        // hover
        Rectangle {
            visible: timeline.hover >= 0
            x: timeline.xOf(timeline.hover)
            y: 14
            width: 1
            height: timeline.barHeight - 18
            color: Theme.alpha(Theme.foreground, 0.4)
        }

        // playhead
        Item {
            visible: timeline.playhead >= timeline.viewStart && timeline.playhead <= timeline.viewEnd
            x: timeline.xOf(timeline.playhead)
            Rectangle { x: -1; y: 12; width: 2; height: timeline.barHeight - 12; color: Theme.warning }
            Rectangle { x: -4; y: 9; width: 8; height: 8; radius: 4; color: Theme.warning }
        }

        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: timeline.pannable ? (pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor) : Qt.PointingHandCursor

            property real pressX: 0
            property double pressStart: 0
            property bool moved: false

            onPressed: mouse => { pressX = mouse.x; pressStart = timeline.viewStart; moved = false }
            onPositionChanged: mouse => {
                timeline.hover = timeline.timeAt(mouse.x)
                if (!pressed || !timeline.pannable)
                    return
                const dx = mouse.x - pressX
                if (Math.abs(dx) > 3)
                    moved = true
                if (moved) {
                    const next = pressStart - dx / track.width * timeline.span
                    timeline.pan(timeline.clamp(next, timeline.boundsStart, timeline.boundsEnd - timeline.span))
                }
            }
            onReleased: mouse => {
                if (!moved)
                    timeline.seek(timeline.clamp(timeline.timeAt(mouse.x), timeline.boundsStart, timeline.boundsEnd))
            }
            onExited: timeline.hover = -1
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Text { text: Qt.formatDateTime(new Date(timeline.viewStart), "dd MMM HH:mm"); color: Theme.mutedForeground; font.family: Theme.font; font.pixelSize: 11 }
        Item { Layout.fillWidth: true }
        Text {
            text: timeline.hover >= 0 ? Qt.formatDateTime(new Date(timeline.hover), "HH:mm:ss") : ""
            color: Theme.mutedForeground
            font.family: Theme.font
            font.pixelSize: 11
        }
        Item { Layout.fillWidth: true }
        Text { text: Qt.formatDateTime(new Date(timeline.viewEnd), "dd MMM HH:mm"); color: Theme.mutedForeground; font.family: Theme.font; font.pixelSize: 11 }
    }
}
