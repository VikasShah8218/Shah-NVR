import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// PTZ control cluster overlaid on the main-stream (big view). Opens a direct WebSocket to the
// media node via the PtzWs store; holding a pad button pans/tilts continuously, release stops.
// Pan/tilt speed is chosen by the node from the live zoom (shown in the meter); zoom/focus are fixed.
// Lives above the DigitalZoom layer; empty areas pass through so digital zoom still works.
Item {
    id: overlay

    property int cameraId: 0
    property string profile: "main"
    property bool open: false

    readonly property var caps: PtzWs.caps
    readonly property bool ready: PtzWs.ready

    onOpenChanged: open ? PtzWs.open(cameraId, profile) : PtzWs.close()
    onCameraIdChanged: open = false            // never carry control to another camera
    Component.onDestruction: PtzWs.close()

    // ---- collapsed: a small toggle pill -------------------------------------
    Rectangle {
        visible: !overlay.open
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 12
        radius: height / 2
        implicitWidth: toggleRow.implicitWidth + 22
        implicitHeight: 32
        color: Qt.rgba(0, 0, 0, 0.55)
        border.color: Qt.rgba(1, 1, 1, 0.18)
        Row {
            id: toggleRow
            anchors.centerIn: parent
            spacing: 6
            Icon { name: "crosshair"; size: 14; color: "white"; anchors.verticalCenter: parent.verticalCenter }
            Text { text: "PTZ"; color: "white"; font.family: Theme.font; font.pixelSize: Theme.textXs; font.weight: Font.Medium; anchors.verticalCenter: parent.verticalCenter }
        }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: overlay.open = true }
    }

    // ---- expanded: the control panel ----------------------------------------
    Rectangle {
        id: panel
        visible: overlay.open
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 12
        width: 224
        radius: 16
        color: Qt.rgba(0, 0, 0, 0.58)
        border.color: Qt.rgba(1, 1, 1, 0.18)
        implicitHeight: content.implicitHeight + 20

        MouseArea { anchors.fill: parent }   // absorb stray clicks so digital zoom doesn't grab them

        ColumnLayout {
            id: content
            anchors.fill: parent
            anchors.margins: 10
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                Text { text: "PTZ"; color: "white"; font.family: Theme.font; font.pixelSize: Theme.textXs; font.weight: Font.DemiBold; Layout.fillWidth: true }
                Text { visible: PtzWs.phase === "connecting"; text: "connecting…"; color: Qt.rgba(1, 1, 1, 0.6); font.family: Theme.font; font.pixelSize: 10 }
                Text { visible: PtzWs.phase === "reconnecting"; text: "reconnecting…"; color: Theme.warning; font.family: Theme.font; font.pixelSize: 10 }
                MouseArea {
                    implicitWidth: 18; implicitHeight: 18
                    cursorShape: Qt.PointingHandCursor
                    onClicked: overlay.open = false
                    Icon { anchors.centerIn: parent; name: "x"; size: 14; color: "white" }
                }
            }

            RowLayout {
                spacing: 8
                // 8-way pad with a centre Stop
                GridLayout {
                    columns: 3
                    rowSpacing: 4
                    columnSpacing: 4
                    HoldButton { glyph: "↖"; active: panel.ptActive; onPressedDown: PtzWs.hold(-1, 1, 0); onReleasedUp: PtzWs.release() }
                    HoldButton { glyph: "↑"; active: panel.ptActive; onPressedDown: PtzWs.hold(0, 1, 0); onReleasedUp: PtzWs.release() }
                    HoldButton { glyph: "↗"; active: panel.ptActive; onPressedDown: PtzWs.hold(1, 1, 0); onReleasedUp: PtzWs.release() }
                    HoldButton { glyph: "←"; active: panel.ptActive; onPressedDown: PtzWs.hold(-1, 0, 0); onReleasedUp: PtzWs.release() }
                    StopButton { active: overlay.ready; onTapped: PtzWs.stop() }
                    HoldButton { glyph: "→"; active: panel.ptActive; onPressedDown: PtzWs.hold(1, 0, 0); onReleasedUp: PtzWs.release() }
                    HoldButton { glyph: "↙"; active: panel.ptActive; onPressedDown: PtzWs.hold(-1, -1, 0); onReleasedUp: PtzWs.release() }
                    HoldButton { glyph: "↓"; active: panel.ptActive; onPressedDown: PtzWs.hold(0, -1, 0); onReleasedUp: PtzWs.release() }
                    HoldButton { glyph: "↘"; active: panel.ptActive; onPressedDown: PtzWs.hold(1, -1, 0); onReleasedUp: PtzWs.release() }
                }
                // zoom
                ColumnLayout {
                    spacing: 4
                    HoldButton { glyph: "+"; active: panel.zoomActive; onPressedDown: PtzWs.hold(0, 0, 1); onReleasedUp: PtzWs.release() }
                    HoldButton { glyph: "−"; active: panel.zoomActive; onPressedDown: PtzWs.hold(0, 0, -1); onReleasedUp: PtzWs.release() }
                }
                // focus (ONVIF Imaging) — only when supported
                ColumnLayout {
                    visible: overlay.caps ? !!overlay.caps.focus : false
                    spacing: 4
                    HoldButton { glyph: "N"; active: overlay.ready; onPressedDown: PtzWs.holdFocus(1); onReleasedUp: PtzWs.release() }
                    HoldButton { glyph: "F"; active: overlay.ready; onPressedDown: PtzWs.holdFocus(-1); onReleasedUp: PtzWs.release() }
                }
            }

            // auto-speed meter (node-derived from zoom)
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "speed (auto)"; color: Qt.rgba(1, 1, 1, 0.6); font.family: Theme.font; font.pixelSize: 10; Layout.fillWidth: true }
                    Text {
                        text: PtzWs.speed.toFixed(2) + (PtzWs.zoomPct >= 0 ? "  ·  zoom " + PtzWs.zoomPct + "%" : "")
                        color: Qt.rgba(1, 1, 1, 0.75); font.family: Theme.font; font.pixelSize: 10
                    }
                }
                Rectangle {
                    Layout.fillWidth: true
                    height: 5
                    radius: 3
                    color: Qt.rgba(1, 1, 1, 0.15)
                    Rectangle {
                        height: parent.height
                        radius: 3
                        color: Theme.primary
                        width: parent.width * Math.max(0, Math.min(1, PtzWs.speed / 0.5))
                        Behavior on width { NumberAnimation { duration: 180 } }
                    }
                }
            }

            Text {
                visible: PtzWs.error !== ""
                text: PtzWs.error
                color: Theme.danger
                font.family: Theme.font; font.pixelSize: 10
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            Repeater {
                model: PtzWs.error === "" ? (PtzWs.warnings ?? []) : []
                delegate: Text {
                    required property var modelData
                    text: modelData
                    color: Theme.warning
                    font.family: Theme.font; font.pixelSize: 10
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }
        }

        readonly property bool ptActive: (overlay.caps ? !!overlay.caps.pan_tilt : false) && overlay.ready
        readonly property bool zoomActive: (overlay.caps ? !!overlay.caps.zoom : false) && overlay.ready
    }

    // ---- reusable press-and-hold / stop buttons -----------------------------
    component HoldButton: Rectangle {
        property string glyph: ""
        property bool active: true
        signal pressedDown()
        signal releasedUp()
        implicitWidth: 34
        implicitHeight: 34
        radius: 8
        color: tap.pressed ? Theme.primary : Qt.rgba(1, 1, 1, 0.08)
        border.color: Qt.rgba(1, 1, 1, 0.18)
        opacity: active ? 1 : 0.4
        Text { anchors.centerIn: parent; text: parent.glyph; color: "white"; font.pixelSize: 15 }
        TapHandler {
            id: tap
            enabled: parent.active
            onPressedChanged: pressed ? parent.pressedDown() : parent.releasedUp()
        }
    }

    component StopButton: Rectangle {
        property bool active: true
        signal tapped()
        implicitWidth: 34
        implicitHeight: 34
        radius: 8
        color: Qt.rgba(1, 1, 1, 0.06)
        border.color: Qt.rgba(1, 1, 1, 0.18)
        opacity: active ? 1 : 0.4
        Rectangle { anchors.centerIn: parent; width: 10; height: 10; radius: 2; color: "white" }
        TapHandler { enabled: parent.active; onTapped: parent.tapped() }
    }
}
