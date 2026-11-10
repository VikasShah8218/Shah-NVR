import QtQuick
import "../theme"
import "../components"

// Small ↻ over live video: drops the stream's connection and starts a fresh one (MpvPlayer.reconnect).
//   RefreshButton { player: videoView.player }
AppButton {
    id: button

    property var player: null

    variant: "ghost"
    size: "icon"
    iconName: "refresh-cw"
    implicitWidth: 26
    implicitHeight: 26
    tip: "Reconnect (fresh connection)"
    enabled: !!player && player.source !== ""
    onClicked: if (player) player.reconnect()

    background: Rectangle {
        radius: Theme.radiusSm
        color: button.hovered ? Qt.rgba(1, 1, 1, 0.22) : Qt.rgba(0, 0, 0, 0.5)
    }
}
