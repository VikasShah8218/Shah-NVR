import QtQuick
import QtQuick.Layouts
import Nvr.Video
import App
import "../theme"
import "../components"

// A video view with the same overlays as the web LivePlayer: connecting / retrying states and an info
// label "1920×1080 · RTSP · d3d11va-copy". `player` exposes the MpvPlayer (seek, screenshot...);
// MpvSurface draws it with the GPU or the CPU, depending on the render mode chosen at startup.
Rectangle {
    id: view

    property string source: ""
    property string fallbackSource: ""
    property string mode: "live" // live | playback
    property bool showInfo: true
    property string waitingText: "" // shown while there is no source yet (e.g. "Camera is disabled")
    readonly property alias player: mpv
    readonly property string protocolLabel: mpv.activeSource.startsWith("rtsp") ? "RTSP"
        : mpv.activeSource.includes(".m3u8") ? (mode === "live" ? "LL-HLS" : "HLS") : ""

    color: Theme.video
    clip: true

    MpvPlayer {
        id: mpv
        mode: view.mode
        hwdec: Prefs.hwdec
        liveBufferSeconds: Prefs.hlsBufferSeconds
        fallbackSource: view.fallbackSource
        source: view.source
    }
    MpvSurface {
        anchors.fill: parent
        player: mpv
    }

    // waiting for a source
    AppText {
        visible: view.source === "" && view.waitingText !== ""
        anchors.centerIn: parent
        text: view.waitingText
        variant: "muted"
    }

    // connecting
    Row {
        visible: view.source !== "" && mpv.playState === "connecting"
        anchors.centerIn: parent
        spacing: 8
        Spinner { anchors.verticalCenter: parent.verticalCenter }
        AppText {
            text: "Connecting" + (view.protocolLabel ? " (" + view.protocolLabel + ")" : "") + "…"
            variant: "small"
        }
    }

    // stream lost / failed
    Column {
        visible: view.source !== "" && (mpv.playState === "reconnecting" || mpv.playState === "error")
        anchors.centerIn: parent
        spacing: 6
        width: Math.min(parent.width - 24, 280)
        Icon { name: "video-off"; size: 20; color: Theme.mutedForeground; anchors.horizontalCenter: parent.horizontalCenter }
        AppText {
            width: parent.width
            text: mpv.errorText
            variant: "small"
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
        }
    }

    // info overlay
    Rectangle {
        visible: view.showInfo && mpv.playState === "playing"
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 6
        radius: 4
        color: Qt.rgba(0, 0, 0, 0.55)
        implicitWidth: info.implicitWidth + 12
        implicitHeight: info.implicitHeight + 4
        Text {
            id: info
            anchors.centerIn: parent
            text: mpv.videoWidth + "×" + mpv.videoHeight + " · " + view.protocolLabel + " · "
                + (Prefs.activeRenderMode === "cpu" ? "CPU render"
                   : mpv.hwdecCurrent && mpv.hwdecCurrent !== "no" ? mpv.hwdecCurrent : "CPU decode")
            color: Qt.rgba(1, 1, 1, 0.85)
            font.family: Theme.font
            font.pixelSize: 10
        }
    }
}
