import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

// Recording timeline (port of nvr_client/src/features/playback/Timeline.tsx): recorded ranges vs gaps
// for the visible window, local-time ticks, a "now" marker, markers (bookmarks), a hover line with a
// preview picture, and the playhead. Click to seek (a click on a marker seeks to its exact start);
// drag to pan (when `pannable`). All times are epoch milliseconds.
ColumnLayout {
    id: timeline

    property var ranges: []        // [{a, b}] merged recorded ranges (features/playback/timeline.py)
    property var accentRanges: []  // optional provenance overlay, e.g. camera SD backfill
    property var ticks: []         // [{t, label}] aligned to local time
    property double viewStart: 0
    property double viewEnd: 1
    property double boundsStart: viewStart
    property double boundsEnd: viewEnd
    property double playhead: -1   // < 0 = no playhead
    property bool pannable: false
    // Placed markers [{id, t, x, width, color, label}] (features/playback/markers.py): x/width are 0..1,
    // width null = a point in time.
    property var markers: []
    // Hover preview: function(ms) -> {url, at} or {} (gap); null = no previews.
    property var thumbAt: null
    property int barHeight: 56
    signal seek(double ms)
    signal pan(double viewStart)

    readonly property double span: Math.max(1, viewEnd - viewStart)
    property double now: Date.now()
    property double hover: -1
    property var hoverMarker: null
    // Debounced hover time for the preview (150 ms after the pointer settles, none while dragging).
    property double thumbTime: -1
    readonly property var thumb: thumbTime >= 0 && thumbAt ? thumbAt(thumbTime) : null

    function xOf(t) { return (t - viewStart) / span * track.width }
    function timeAt(x) { return viewStart + x / track.width * span }
    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }
    // The marker under the pointer: a point within 5 px, or a range band under the bar.
    function markerAt(x, y) {
        for (let i = markers.length - 1; i >= 0; i--) {
            const m = markers[i], mx = m.x * track.width
            if (m.width === null || m.width === undefined) {
                if (Math.abs(x - mx) <= 5) return m
            } else if (x >= mx && x <= mx + m.width * track.width && y >= timeline.barHeight - 14) {
                return m
            }
        }
        return null
    }

    spacing: 4

    Timer { interval: 5000; running: timeline.visible; repeat: true; onTriggered: timeline.now = Date.now() }
    Timer { id: thumbTimer; interval: 150; onTriggered: timeline.thumbTime = timeline.hover }

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

        Repeater {
            model: timeline.accentRanges.filter(r => r.b > timeline.viewStart && r.a < timeline.viewEnd)
            delegate: Rectangle {
                required property var modelData
                readonly property real x0: Math.max(0, timeline.xOf(modelData.a))
                x: x0
                y: track.barTop
                width: Math.max(1.5, timeline.xOf(Math.min(modelData.b, timeline.viewEnd)) - x0)
                height: track.barH
                color: Theme.primary
                opacity: 0.9
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

        // markers (bookmarks; motion / ONVIF events later): a range is a band under the bar, a point a pin
        Repeater {
            model: timeline.markers
            delegate: Item {
                required property var modelData
                readonly property color tint: modelData.color ? modelData.color : Theme.primary
                readonly property bool isRange: modelData.width !== null && modelData.width !== undefined
                x: modelData.x * track.width
                Rectangle {
                    visible: parent.isRange
                    y: timeline.barHeight - 12
                    width: parent.isRange ? modelData.width * track.width : 0
                    height: 5
                    radius: 2
                    color: parent.tint
                    opacity: 0.85
                }
                Rectangle { visible: !parent.isRange; x: -1; y: 16; width: 2; height: timeline.barHeight - 22; color: parent.tint }
                Rectangle { visible: !parent.isRange; x: -3.5; y: timeline.barHeight - 10.5; width: 7; height: 7; radius: 3.5; color: parent.tint }
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
                timeline.hoverMarker = timeline.markerAt(mouse.x, mouse.y)
                if (!moved)
                    thumbTimer.restart()
                if (!pressed || !timeline.pannable)
                    return
                const dx = mouse.x - pressX
                if (Math.abs(dx) > 3 && !moved) {
                    moved = true
                    thumbTimer.stop()
                    timeline.thumbTime = -1
                }
                if (moved) {
                    const next = pressStart - dx / track.width * timeline.span
                    timeline.pan(timeline.clamp(next, timeline.boundsStart, timeline.boundsEnd - timeline.span))
                }
            }
            onReleased: mouse => {
                if (moved)
                    return
                const marker = timeline.markerAt(mouse.x, mouse.y)
                const t = marker ? marker.t : timeline.timeAt(mouse.x)
                timeline.seek(timeline.clamp(t, timeline.boundsStart, timeline.boundsEnd))
            }
            onExited: {
                timeline.hover = -1
                timeline.hoverMarker = null
                thumbTimer.stop()
                timeline.thumbTime = -1
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Text { text: Qt.formatDateTime(new Date(timeline.viewStart), "dd MMM HH:mm"); color: Theme.mutedForeground; font.family: Theme.font; font.pixelSize: 11 }
        Item { Layout.fillWidth: true }
        Text {
            text: timeline.hover < 0 ? "" : Qt.formatDateTime(new Date(timeline.hover), "HH:mm:ss")
                  + (timeline.hoverMarker ? "  ·  " + timeline.hoverMarker.label : "")
            elide: Text.ElideRight
            Layout.maximumWidth: track.width * 0.6
            color: Theme.mutedForeground
            font.family: Theme.font
            font.pixelSize: 11
        }
        Item { Layout.fillWidth: true }
        Text { text: Qt.formatDateTime(new Date(timeline.viewEnd), "dd MMM HH:mm"); color: Theme.mutedForeground; font.family: Theme.font; font.pixelSize: 11 }
    }

    // Hover preview. A Popup lives in the window overlay, so the track's clip and the page Card can't
    // cut it off (the bug the web client had); it sits just above the hover point, inside the window.
    Popup {
        id: thumbPopup
        readonly property bool wanted: !!timeline.thumb && !!timeline.thumb.url && timeline.hover >= 0
        readonly property point anchor: wanted && parent
            ? track.mapToItem(parent, timeline.xOf(timeline.hover), 0) : Qt.point(0, 0)
        parent: Overlay.overlay
        visible: wanted
        width: 168
        padding: 4
        modal: false
        focus: false
        closePolicy: Popup.NoAutoClose
        x: parent ? timeline.clamp(anchor.x - width / 2, 8, parent.width - width - 8) : 0
        y: anchor.y - height - 6
        background: Rectangle { color: Theme.card; radius: Theme.radiusSm + 2; border.color: Theme.border }
        contentItem: Column {
            spacing: 3
            Rectangle {
                width: 160
                height: 90
                radius: 3
                color: Theme.video
                clip: true
                Image {
                    id: thumbImage
                    anchors.fill: parent
                    source: thumbPopup.wanted ? timeline.thumb.url : ""
                    asynchronous: true
                    cache: true
                    fillMode: Image.PreserveAspectCrop
                    sourceSize.width: 240
                    visible: status === Image.Ready
                }
                Text {
                    anchors.centerIn: parent
                    visible: thumbImage.status !== Image.Ready
                    text: thumbImage.status === Image.Error ? "No preview" : "Loading…"
                    color: Theme.mutedForeground
                    font.family: Theme.font
                    font.pixelSize: 11
                }
            }
            Text {
                width: 160
                horizontalAlignment: Text.AlignHCenter
                text: thumbPopup.wanted ? Qt.formatDateTime(new Date(timeline.thumb.at), "HH:mm:ss") : ""
                color: Theme.mutedForeground
                font.family: Theme.font
                font.pixelSize: 11
            }
        }
    }
}
