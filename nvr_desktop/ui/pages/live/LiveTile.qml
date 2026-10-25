import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"
import "../../video"

// One grid cell of the Live View (port of LiveTile in LivePage.tsx): the video, a hover header
// (name, REC, profile, menu), selection ring, drop target and the empty-tile hint.
Rectangle {
    id: tile

    required property int index
    property var cameraId: null         // null = empty tile
    property string gridProtocol: "auto"
    property bool suspended: false      // the main-stream dialog is open or the page is hidden: freeze, free the network
    property bool released: false       // hidden page kept too long: destroy the player (LivePage.releasePlayers)
    readonly property var video: videoLoader.item
    signal expand(int cameraId)

    readonly property var camera: {
        Cameras.all // subscribe to camera updates, not just changes of the tile ID
        return cameraId ? Cameras.byId(cameraId) : null
    }
    readonly property bool selected: Live.selected === index
    property string protocolOverride: "" // "" = same as the grid
    readonly property string protocol: protocolOverride || gridProtocol
    // Fixed policy: one-up uses main; every multi-camera grid uses sub when present.
    readonly property string profile: camera && Live.layout > 1
        && camera.streams.some(s => s.profile === "sub") ? "sub" : "main"
    readonly property var urls: {
        Live.urlsRevision // re-evaluate when the URLs refresh
        return cameraId ? Live.sources(cameraId, profile, protocol) : ({})
    }
    readonly property bool recording: !!camera && camera.streams.some(s => s.record && s.status === "RECORDING")

    color: Theme.video
    radius: Theme.radiusSm
    clip: true

    onCameraIdChanged: protocolOverride = ""

    Loader {
        id: videoLoader
        active: !tile.released
        visible: !!tile.camera
        anchors.fill: parent
        sourceComponent: VideoView {
            source: tile.camera ? tile.urls.source ?? "" : ""
            fallbackSource: tile.camera ? tile.urls.fallback ?? "" : ""
            waitingText: tile.urls.error ? tile.urls.error : "Loading stream URLs…"
            suspended: tile.suspended
            showInfo: hover.hovered || Live.layout <= 4
            player.muted: Live.activeAudioCameraId !== tile.cameraId
            player.volume: Prefs.liveVolume
        }
    }

    // frozen behind the main-stream dialog
    Rectangle {
        visible: tile.suspended && !!tile.camera
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 6
        radius: 4
        color: Qt.rgba(0, 0, 0, 0.55)
        implicitWidth: pausedRow.implicitWidth + 12
        implicitHeight: 18
        Row {
            id: pausedRow
            anchors.centerIn: parent
            spacing: 4
            Icon { name: "pause"; size: 10; color: "white"; anchors.verticalCenter: parent.verticalCenter }
            Text { text: "Paused"; color: Qt.rgba(1, 1, 1, 0.85); font.family: Theme.font; font.pixelSize: 10 }
        }
    }

    // empty tile
    Row {
        visible: !tile.camera
        anchors.centerIn: parent
        spacing: 6
        Icon { name: "plus"; size: 16; color: Theme.mutedForeground; anchors.verticalCenter: parent.verticalCenter }
        AppText { text: "Click a camera or drop it here"; variant: "small"; anchors.verticalCenter: parent.verticalCenter }
    }

    // selection: click selects, double-click opens the main stream
    HoverHandler { id: hover }
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onClicked: Live.select(tile.index)
        onDoubleClicked: if (tile.camera) tile.expand(tile.cameraId)
    }

    // header (name, REC, profile, menu)
    Rectangle {
        visible: !!tile.camera
        width: parent.width
        height: 30
        gradient: Gradient {
            GradientStop { position: 0; color: Qt.rgba(0, 0, 0, 0.6) }
            GradientStop { position: 1; color: "transparent" }
        }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 4
            spacing: tile.width < 260 ? 4 : 8
            Text {
                text: tile.camera ? tile.camera.name : ""
                color: "white"
                font.family: Theme.font
                font.pixelSize: Theme.textXs
                font.weight: Font.Medium
                elide: Text.ElideRight
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
            }
            Rectangle {
                visible: tile.recording && tile.width >= 220
                implicitWidth: recRow.implicitWidth + 8
                implicitHeight: 16
                radius: 3
                color: Theme.alpha(Theme.danger, 0.8)
                Row {
                    id: recRow
                    anchors.centerIn: parent
                    spacing: 4
                    Rectangle {
                        width: 6; height: 6; radius: 3; color: "white"
                        anchors.verticalCenter: parent.verticalCenter
                        SequentialAnimation on opacity {
                            loops: Animation.Infinite
                            NumberAnimation { to: 0.3; duration: 900 }
                            NumberAnimation { to: 1; duration: 900 }
                        }
                    }
                    Text { text: "REC"; color: "white"; font.family: Theme.font; font.pixelSize: 10; font.weight: Font.DemiBold }
                }
            }
            Text {
                visible: tile.width >= 180
                text: tile.profile
                color: Qt.rgba(1, 1, 1, 0.6)
                font.family: Theme.font
                font.pixelSize: Theme.textXs
            }
            AppButton {
                visible: (hover.hovered || Live.activeAudioCameraId === tile.cameraId) && (tile.urls.audio_state === "available" || tile.urls.audio_state === "advertised_not_observed")
                variant: "ghost"; size: "icon"; implicitWidth: 24; implicitHeight: 24
                iconName: Live.activeAudioCameraId === tile.cameraId ? "volume-2" : "volume-x"
                tip: Live.activeAudioCameraId === tile.cameraId ? "Mute audio" : "Listen to this camera"
                onClicked: Live.toggleAudio(tile.cameraId)
            }
            AppButton {
                id: menuButton
                visible: hover.hovered || menu.visible
                variant: "ghost"
                size: "icon"
                iconName: "ellipsis-vertical"
                implicitWidth: 24
                implicitHeight: 24
                onClicked: menu.popup(menuButton, menuButton.width - menu.width, menuButton.height + 4)
            }
        }
    }

    // selection ring (drawn above the video)
    Rectangle {
        anchors.fill: parent
        color: "transparent"
        radius: tile.radius
        border.width: dropArea.containsDrag || tile.selected ? 2 : 1
        border.color: dropArea.containsDrag || tile.selected ? Theme.primary : Theme.border
    }

    DropArea {
        id: dropArea
        anchors.fill: parent
        keys: ["camera"]
        onDropped: drop => Live.place(drop.source.cameraId, tile.index)
    }

    AppMenu {
        id: menu
        MenuSectionLabel { text: "Protocol" }
        AppMenuItem { text: "Same as grid"; radio: true; marked: tile.protocolOverride === ""; onTriggered: tile.protocolOverride = "" }
        AppMenuItem { text: "RTSP"; radio: true; marked: tile.protocolOverride === "rtsp"; onTriggered: tile.protocolOverride = "rtsp" }
        AppMenuItem { text: "LL-HLS"; radio: true; marked: tile.protocolOverride === "hls"; onTriggered: tile.protocolOverride = "hls" }
        MenuSeparator {}
        AppMenuItem { text: "Open main stream"; iconName: "maximize"; onTriggered: tile.expand(tile.cameraId) }
        AppMenuItem { text: "PTZ controls"; iconName: "crosshair"; onTriggered: ptzDialog.open() }
        AppMenuItem {
            text: "Snapshot"
            iconName: "image-down"
            onTriggered: {
                const path = Live.snapshotPath(tile.camera.name)
                if (tile.video && tile.video.player.playState === "playing" && tile.video.player.screenshot(path))
                    Toasts.success("Snapshot saved to " + path)
                else
                    Toasts.error("No video frame yet")
            }
        }
        AppMenuItem {
            text: "Copy RTSP URL"
            iconName: "copy"
            onTriggered: tile.urls.rtsp ? Utils.copy(tile.urls.rtsp, "RTSP URL copied (open it in VLC)") : Toasts.error("Stream URL not available")
        }
        AppMenuItem { text: "Camera details"; iconName: "external-link"; onTriggered: Router.go("camera", tile.cameraId) }
        MenuSeparator {}
        AppMenuItem { text: "Remove from view"; iconName: "x"; onTriggered: Live.clearTile(tile.index) }
    }

    AppDialog {
        id: ptzDialog
        width: Math.min(620, Overlay.overlay.width - 40)
        title: (tile.camera ? tile.camera.name : "Camera") + " · PTZ"
        onClosed: Ptz.close()
        Loader {
            active: ptzDialog.opened && !!tile.camera
            Layout.fillWidth: true
            sourceComponent: PtzPanel { cameraId: tile.cameraId ?? 0; profile: tile.profile }
        }
    }

    component MenuSectionLabel: Text {
        leftPadding: 10
        topPadding: 6
        bottomPadding: 4
        color: Theme.mutedForeground
        font.family: Theme.font
        font.pixelSize: Theme.textXs
        font.weight: Font.Medium
    }
}
