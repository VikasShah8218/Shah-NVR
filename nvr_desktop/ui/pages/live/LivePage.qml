import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"
import "../../video"

// Port of nvr_client/src/features/live/LivePage.tsx: camera list (click or drag onto a tile),
// layouts 1 / 2×2 / 3×3 / 4×4, grid protocol, clear, fullscreen, double-click → main stream.
// Layout and tiles are remembered (LiveStore → Preferences).
Item {
    id: root
    objectName: "livePage"

    property string search: ""
    property string protocol: Prefs.liveProtocol
    property var expandedCamera: null
    readonly property int columns: Math.round(Math.sqrt(Live.layout))
    readonly property var appWindow: ApplicationWindow.window

    // Set by Main.qml: the page is kept loaded but hidden after leaving Live View. Tiles pause (no network,
    // last frame kept) and resume quietly on return, so page switches are instant both ways.
    property bool away: false
    // Tiles [0, releasedTiles) have destroyed their players (keep-alive expired), one per tick so the
    // UI-thread cost (~100 ms each) never shows up as one long freeze.
    property int releasedTiles: 0
    signal playersReleased()

    function releasePlayers() {
        if (away)
            releaseTimer.start()
    }

    onAwayChanged: {
        if (away) {
            expandDialog.close()
            Live.muteAll()
            Ptz.close()
            if (appWindow)
                appWindow.immersive = false
        } else {
            releaseTimer.stop()
            releasedTiles = 0
        }
    }

    Timer {
        id: releaseTimer
        interval: 150
        repeat: true
        onTriggered: {
            if (root.releasedTiles < 16) {
                root.releasedTiles++
                // the hidden page requests no frames: render one so this tile's GL context is freed now,
                // not together with all the others on the next visible change
                if (root.appWindow)
                    root.appWindow.update()
            } else {
                stop()
                root.playersReleased()
            }
        }
    }

    function expand(cameraId) {
        expandedZoom.reset()
        expandedCamera = Cameras.byId(cameraId)
        expandDialog.open()
    }

    Component.onCompleted: { for (const id of Live.onView) Live.ensureUrls(id) }
    Component.onDestruction: { Live.muteAll(); Ptz.close(); if (appWindow) appWindow.immersive = false }
    Connections {
        target: Qt.application
        function onStateChanged() { if (Qt.application.state !== Qt.ApplicationActive) Live.muteAll() }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ============================================================ camera list
        Rectangle {
            visible: !root.appWindow || !root.appWindow.immersive
            Layout.preferredWidth: 256
            Layout.fillHeight: true
            color: Theme.alpha(Theme.card, 0.3)
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }

            ColumnLayout {
                anchors.fill: parent
                anchors.rightMargin: 1
                spacing: 0

                AppInput {
                    Layout.fillWidth: true
                    Layout.margins: 12
                    iconName: "search"
                    placeholderText: "Search cameras"
                    onTextChanged: root.search = text.toLowerCase()
                }

                LoadingState { visible: Cameras.loading && Cameras.listModel.count === 0 && Cameras.error === "" }
                ErrorState { text: Cameras.error; Layout.margins: 8 }

                ListView {
                    id: cameraList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    leftMargin: 8
                    rightMargin: 8
                    bottomMargin: 12
                    clip: true
                    model: Cameras.listModel
                    ScrollBar.vertical: AppScrollBar {}

                    delegate: Rectangle {
                        id: entry
                        required property var model
                        readonly property bool matches: root.search === "" || model.name.toLowerCase().includes(root.search)

                        width: cameraList.width - 16
                        height: matches ? 36 : 0
                        visible: matches
                        radius: Theme.radiusSm
                        color: entryArea.containsMouse && model.enabled ? Theme.accent : "transparent"
                        opacity: model.enabled ? 1 : 0.5

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            spacing: 10
                            StatusDot { status: entry.model.recordStatus }
                            AppText { text: entry.model.name; Layout.fillWidth: true }
                            AppText {
                                visible: Live.onView.includes(entry.model.id)
                                text: "on view"
                                color: Theme.primary
                                font.pixelSize: 10
                            }
                        }

                        MouseArea {
                            id: entryArea
                            anchors.fill: parent
                            enabled: entry.model.enabled
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            drag.target: ghost
                            drag.threshold: 6
                            onPressed: mouse => {
                                ghost.cameraId = entry.model.id
                                ghost.label = entry.model.name
                                const p = entry.mapToItem(root, mouse.x, mouse.y)
                                ghost.x = p.x - ghost.width / 2
                                ghost.y = p.y - ghost.height / 2
                            }
                            // drop while the ghost's Drag is still active, then end the drag
                            drag.onActiveChanged: {
                                if (!drag.active)
                                    ghost.Drag.drop()
                                ghost.dragging = drag.active
                            }
                            onClicked: Live.place(entry.model.id)
                            ToolTip.visible: containsMouse && !drag.active
                            ToolTip.delay: 800
                            ToolTip.text: "Click or drag onto a tile"
                        }
                    }

                    AppText {
                        visible: Cameras.listModel.count > 0 && !Cameras.all.some(c => c.name.toLowerCase().includes(root.search))
                        text: "No cameras."
                        variant: "muted"
                        x: 12
                        y: 8
                    }
                }
            }
        }

        // ============================================================ grid
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // toolbar
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 52
                color: "transparent"
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    spacing: 12
                    ToggleGroup {
                        spacing: 6
                        options: [{ value: 1, label: "1" }, { value: 4, label: "2×2" }, { value: 9, label: "3×3" }, { value: 16, label: "4×4" }]
                        value: Live.layout
                        onPicked: v => Live.setLayout(v)
                    }
                    AppSelect {
                        implicitWidth: 210
                        implicitHeight: 30
                        options: [
                            { value: "auto", label: "Auto (RTSP → LL-HLS)" },
                            { value: "rtsp", label: "RTSP only" },
                            { value: "hls", label: "LL-HLS only" }
                        ]
                        value: root.protocol
                        onPicked: v => root.protocol = v
                    }
                    Item { Layout.fillWidth: true }
                    AppButton { text: "Clear"; iconName: "trash-2"; variant: "outline"; size: "sm"; onClicked: Live.clearAll() }
                    AppButton {
                        readonly property bool on: root.appWindow ? root.appWindow.immersive : false
                        text: on ? "Exit fullscreen" : "Fullscreen"
                        iconName: on ? "minimize" : "maximize"
                        variant: "outline"
                        size: "sm"
                        tip: on ? "Esc" : "F11"
                        onClicked: root.appWindow.immersive = !on
                    }
                }
            }

            EmptyState {
                visible: !Cameras.loading && Cameras.error === "" && Cameras.listModel.count === 0
                Layout.margins: 24
                iconName: "camera"
                title: "No cameras yet"
                text: "Add a camera on the Cameras page, then come back here to watch it live."
            }

            // The tiles are sized from this plain Item (no implicit size), so the grid can never feed its
            // own size back into the layout.
            Item {
                id: gridArea
                visible: Cameras.listModel.count > 0
                Layout.fillWidth: true
                Layout.fillHeight: true

                Grid {
                    id: grid
                    anchors.fill: parent
                    anchors.margins: 4
                    columns: root.columns
                    spacing: 4
                    readonly property real cellW: Math.floor((gridArea.width - 8 - spacing * (columns - 1)) / columns)
                    readonly property real cellH: Math.floor((gridArea.height - 8 - spacing * (columns - 1)) / columns)

                    // 16 fixed tiles; the layout only shows/hides them (Grid skips hidden ones). Changing the
                    // layout or placing a camera never recreates the other tiles, so they keep playing.
                    // A hidden tile has no camera, which stops its video.
                    Repeater {
                        model: 16
                        delegate: LiveTile {
                            visible: index < Live.layout
                            cameraId: index < Live.layout ? Live.tiles[index] ?? null : null
                            gridProtocol: root.protocol
                            // the big main-stream view gets the whole network and decoder; hidden page: pause
                            suspended: expandDialog.visible || root.away
                            released: index < root.releasedTiles
                            width: grid.cellW
                            height: grid.cellH
                            onExpand: id => root.expand(id)
                        }
                    }
                }
            }
        }
    }

    // drag ghost: follows the mouse while a camera is dragged from the list onto a tile
    Rectangle {
        id: ghost
        property int cameraId: 0
        property string label: ""
        property bool dragging: false
        visible: dragging
        width: ghostText.implicitWidth + 24
        height: 30
        radius: Theme.radiusSm
        color: Theme.popover
        border.color: Theme.primary
        z: 100
        Drag.active: dragging
        Drag.keys: ["camera"]
        Drag.hotSpot.x: width / 2
        Drag.hotSpot.y: height / 2
        AppText { id: ghostText; anchors.centerIn: parent; text: ghost.label }
    }

    // main stream of one camera (double-click a tile / "Open main stream")
    AppDialog {
        id: expandDialog
        width: Math.min(root.width * 0.92, 1600)
        title: (root.expandedCamera ? root.expandedCamera.name : "") + " · main stream"
        onClosed: {
            expandedZoom.reset()
            root.expandedCamera = null
        }

        ColumnLayout {
            Layout.fillWidth: true
        Rectangle {
            id: expandedViewport
            Layout.fillWidth: true
            Layout.preferredHeight: width * 9 / 16
            radius: Theme.radiusSm
            color: Theme.video
            clip: true

            VideoView {
                id: expandedVideo
                readonly property var urls: {
                    Live.urlsRevision
                    return root.expandedCamera ? Live.sources(root.expandedCamera.id, "main", root.protocol) : ({})
                }
                anchors.fill: parent
                radius: Theme.radiusSm
                scale: expandedZoom.zoom
                transformOrigin: Item.Center
                transform: Translate {
                    x: expandedZoom.panX
                    y: expandedZoom.panY
                }
                source: expandDialog.opened && root.expandedCamera ? urls.source ?? "" : ""
                fallbackSource: expandDialog.opened && root.expandedCamera ? urls.fallback ?? "" : ""
                player.muted: !root.expandedCamera || Live.activeAudioCameraId !== root.expandedCamera.id
                player.volume: Prefs.liveVolume
                waitingText: "Loading stream URLs…"
            }

            DigitalZoom {
                id: expandedZoom
                anchors.fill: parent
                z: 2
            }
        }
        RowLayout {
            Layout.fillWidth: true
            AppButton {
                text: root.expandedCamera && Live.activeAudioCameraId === root.expandedCamera.id ? "Mute audio" : "Listen"
                iconName: root.expandedCamera && Live.activeAudioCameraId === root.expandedCamera.id ? "volume-2" : "volume-x"
                visible: expandedVideo.urls.audio_state === "available" || expandedVideo.urls.audio_state === "advertised_not_observed"
                onClicked: if (root.expandedCamera) Live.toggleAudio(root.expandedCamera.id)
            }
            AppButton { text: "PTZ"; iconName: "crosshair"; variant: "outline"; onClicked: expandedPtz.active = !expandedPtz.active }
            Item { Layout.fillWidth: true }
        }
        Loader {
            id: expandedPtz
            active: false
            Layout.fillWidth: true
            sourceComponent: PtzPanel { cameraId: root.expandedCamera ? root.expandedCamera.id : 0; profile: "main" }
        }
        }
    }
}
