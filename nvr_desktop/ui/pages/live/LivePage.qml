import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"
import "../../video"

// Port of nvr_client/src/features/live/LivePage.tsx: camera list (click or drag onto a tile),
// layouts 1 / 2×2 / 3×3 / 4×4, grid protocol, clear, fullscreen, double-click → main stream.
// Layout and tiles are remembered (LiveStore → Preferences). The camera list is searched on the server and
// loaded 50 at a time (LiveCameras); ‹ › fill the grid with the next page of cameras.
// Sidebar tabs (docs/GROUPING_PLAN.md): Groups = the lazy group tree (LiveGroups: each expanded group loads its own
// sub-groups and cameras), All cameras = the flat list. ▶ / dragging a group onto a tile plays the group: ‹ › then
// page through that group's cameras.
Item {
    id: root
    objectName: "livePage"

    property string protocol: Prefs.liveProtocol
    property var expandedCamera: null
    readonly property int columns: Math.round(Math.sqrt(Live.layout))
    readonly property var appWindow: ApplicationWindow.window

    // Set by Main.qml: the page is kept loaded but hidden after leaving Live View. Tiles pause (no network,
    // last frame kept) and resume quietly on return, so page switches are instant both ways.
    property bool away: false
    readonly property bool searching: sidebarSearch.text.trim() !== ""

    // Tiles [0, releasedTiles) have destroyed their players (keep-alive expired), one per tick so the
    // UI-thread cost (~100 ms each) never shows up as one long freeze.
    property int releasedTiles: 0
    signal playersReleased()

    function releasePlayers() {
        if (away)
            releaseTimer.start()
    }

    onAwayChanged: {
        LiveGroups.setActive(!away)
        if (away) {
            expandDialog.close()
            Live.muteAll()
            Ptz.close()
            PtzWs.close()
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
        expandedCamera = Cameras.byId(cameraId)  // on view, so cached; PtzOverlay resets itself on cameraId change
        expandDialog.open()
    }

    Component.onCompleted: { LiveGroups.setActive(true); for (const id of Live.onView) Live.ensureUrls(id) }
    Component.onDestruction: { LiveGroups.setActive(false); Live.muteAll(); Ptz.close(); PtzWs.close(); if (appWindow) appWindow.immersive = false }
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
                    id: sidebarSearch
                    objectName: "liveSearch"
                    Layout.fillWidth: true
                    Layout.margins: 12
                    Layout.bottomMargin: 8
                    iconName: "search"
                    placeholderText: "Search cameras or groups"
                    onTextChanged: { LiveCameras.setSearch(text); LiveGroups.setSearch(text) }
                }

                ToggleGroup {
                    objectName: "liveSidebarTabs"
                    visible: !root.searching
                    Layout.leftMargin: 12
                    Layout.bottomMargin: 8
                    options: [{ value: "groups", label: "Groups" }, { value: "all", label: "All cameras" }]
                    value: Prefs.liveSidebarTab
                    onPicked: v => Prefs.liveSidebarTab = v
                }

                GroupTree {
                    objectName: "liveGroupTree"
                    visible: !root.searching && Prefs.liveSidebarTab === "groups"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.leftMargin: 8
                    Layout.rightMargin: 8
                    Layout.bottomMargin: 12
                    store: LiveGroups
                    showActions: true
                    dragItems: true
                    dragGhost: ghost
                    dragRoot: root
                    onView: Live.onView
                    emptyText: "No groups yet. Create them on the Groups page, or use All cameras."
                    onCameraClicked: row => Live.place(row.id)
                    onPlayGroup: row => Live.playGroup(row.id, row.name)
                    onManageGroup: row => Router.go("groups", row.id)
                }

                // search: matching groups (click = show in the tree, ▶ = play) above the matching cameras
                ColumnLayout {
                    visible: root.searching && LiveGroups.searchModel.count > 0
                    Layout.fillWidth: true
                    Layout.leftMargin: 8
                    Layout.rightMargin: 8
                    spacing: 0
                    AppText {
                        text: "GROUPS" + (LiveGroups.searchTotal > LiveGroups.searchModel.count
                                          ? " (" + LiveGroups.searchModel.count + " of " + LiveGroups.searchTotal + ")" : "")
                        variant: "small"
                        font.letterSpacing: 0.6
                        Layout.leftMargin: 6
                        Layout.bottomMargin: 2
                    }
                    Repeater {
                        model: LiveGroups.searchModel
                        delegate: Rectangle {
                            id: groupHit
                            required property var model
                            Layout.fillWidth: true
                            implicitHeight: 42
                            radius: Theme.radiusSm
                            color: groupHitHover.hovered ? Theme.accent : "transparent"
                            HoverHandler { id: groupHitHover }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    LiveGroups.reveal(groupHit.model.path, true)
                                    Prefs.liveSidebarTab = "groups"
                                    sidebarSearch.text = ""
                                }
                            }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 4
                                spacing: 8
                                Icon { name: "folder"; size: 15; color: Theme.alpha(Theme.primary, 0.85) }
                                ColumnLayout {
                                    spacing: 0
                                    Layout.fillWidth: true
                                    AppText { text: groupHit.model.name; Layout.fillWidth: true }
                                    AppText {
                                        text: groupHit.model.pathLabel + (groupHit.model.countLabel ? " · " + groupHit.model.countLabel : "")
                                        variant: "small"
                                        Layout.fillWidth: true
                                    }
                                }
                                AppButton {
                                    variant: "ghost"; size: "icon"; iconName: "play"; implicitHeight: 26
                                    tip: "Play on the grid"
                                    enabled: groupHit.model.camerasTotal > 0
                                    onClicked: Live.playGroup(groupHit.model.id, groupHit.model.name)
                                }
                            }
                        }
                    }
                    Separator { Layout.fillWidth: true; Layout.topMargin: 4; Layout.bottomMargin: 4 }
                }

                LoadingState {
                    visible: (root.searching || Prefs.liveSidebarTab === "all")
                             && LiveCameras.loading && LiveCameras.listModel.count === 0 && LiveCameras.error === ""
                }
                ErrorState { visible: root.searching || Prefs.liveSidebarTab === "all"; text: LiveCameras.error; Layout.margins: 8 }

                ListView {
                    id: cameraList
                    visible: root.searching || Prefs.liveSidebarTab === "all"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    leftMargin: 8
                    rightMargin: 8
                    bottomMargin: 12
                    clip: true
                    model: LiveCameras.listModel
                    ScrollBar.vertical: AppScrollBar {}

                    delegate: Rectangle {
                        id: entry
                        required property var model

                        width: cameraList.width - 16
                        height: root.searching && !!model.group_path ? 44 : 36
                        radius: Theme.radiusSm
                        color: entryArea.containsMouse && model.enabled ? Theme.accent : "transparent"
                        opacity: model.enabled ? 1 : 0.5

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            spacing: 10
                            StatusDot { status: entry.model.status }
                            ColumnLayout {
                                spacing: 0
                                Layout.fillWidth: true
                                AppText { text: entry.model.name; Layout.fillWidth: true }
                                AppText {
                                    visible: root.searching && !!entry.model.group_path
                                    text: entry.model.group_path ?? ""
                                    variant: "small"
                                    Layout.fillWidth: true
                                }
                            }
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
                            onPressed: mouse => ghost.begin("camera", entry.model.id, entry.model.name,
                                                            entry.mapToItem(root, mouse.x, mouse.y))
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

                    footer: AppButton {
                        visible: LiveCameras.hasMore
                        width: visible ? cameraList.width - 16 : 0
                        height: visible ? 32 : 0
                        variant: "ghost"
                        size: "sm"
                        text: LiveCameras.loadingMore ? "Loading…" : LiveCameras.moreLabel
                        enabled: !LiveCameras.loadingMore
                        onClicked: LiveCameras.loadMore()
                    }

                    AppText {
                        visible: !LiveCameras.loading && LiveCameras.error === "" && LiveCameras.listModel.count === 0
                        text: LiveCameras.query !== "" ? "No cameras match." : "No cameras."
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
                    // the played group: ‹ › page through its cameras; ✕ = back to all cameras
                    Rectangle {
                        objectName: "liveScopeChip"
                        visible: Live.scopeId > 0
                        implicitHeight: 30
                        implicitWidth: scopeRow.implicitWidth + 12
                        radius: Theme.radiusSm
                        color: Theme.alpha(Theme.accent, 0.5)
                        border.color: Theme.border
                        RowLayout {
                            id: scopeRow
                            anchors.verticalCenter: parent.verticalCenter
                            x: 8
                            spacing: 4
                            Icon { name: "folder"; size: 14; color: Theme.alpha(Theme.primary, 0.85) }
                            AppText { text: Live.scopeName; Layout.maximumWidth: 160 }
                            AppButton {
                                variant: "ghost"; size: "icon"; iconName: "x"; implicitHeight: 24
                                tip: "Stop playing this group"
                                onClicked: Live.clearScope()
                            }
                        }
                    }
                    // grid pages: the next 4 / 9 / 16 enabled cameras by name
                    RowLayout {
                        visible: Live.gridTotal > 0
                        spacing: 2
                        AppButton {
                            objectName: "gridPrev"
                            variant: "ghost"; size: "icon"; iconName: "chevron-left"; implicitHeight: 30
                            tip: Live.scopeId > 0 ? "Previous cameras of " + Live.scopeName : "Previous cameras"
                            enabled: !Live.gridPaging
                            onClicked: Live.prevGridPage()
                        }
                        AppText {
                            objectName: "gridPageLabel"
                            text: Live.gridPaging ? "Loading…" : Live.gridPage > 0 ? "Page " + Live.gridPage + " / " + Live.gridPages
                                                                               : Live.gridPages + " pages"
                            variant: "small"
                            horizontalAlignment: Text.AlignHCenter
                            Layout.minimumWidth: 78
                        }
                        AppButton {
                            objectName: "gridNext"
                            variant: "ghost"; size: "icon"; iconName: "chevron-right"; implicitHeight: 30
                            tip: Live.scopeId > 0 ? "Next cameras of " + Live.scopeName : "Next cameras"
                            enabled: !Live.gridPaging
                            onClicked: Live.nextGridPage()
                        }
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
                visible: Live.scopeId === 0 && Live.gridTotal === 0 && LiveCameras.query === "" && LiveCameras.total === 0
                Layout.margins: 24
                iconName: "camera"
                title: "No cameras yet"
                text: "Add a camera on the Cameras page, then come back here to watch it live."
            }

            // The tiles are sized from this plain Item (no implicit size), so the grid can never feed its
            // own size back into the layout.
            Item {
                id: gridArea
                visible: Live.scopeId > 0 || Live.gridTotal !== 0 || LiveCameras.total > 0
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

    // drag ghost: follows the mouse while a camera or a group is dragged from the sidebar onto a tile
    DragGhost { id: ghost }

    // main stream of one camera (double-click a tile / "Open main stream")
    AppDialog {
        id: expandDialog
        width: Math.min(root.width * 0.92, 1600)
        title: (root.expandedCamera ? root.expandedCamera.name : "") + " · main stream"
        onClosed: {
            ptzOverlay.open = false   // stops the camera and closes the WS session
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

            // ↻ fresh connection for the main stream (above the zoom / PTZ layers)
            RefreshButton {
                objectName: "expandRefresh"
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.margins: 8
                z: 4
                player: expandedVideo.player
            }

            PtzOverlay {
                id: ptzOverlay
                anchors.fill: parent
                z: 3
                visible: !!root.expandedCamera && root.expandedCamera.has_ptz
                cameraId: root.expandedCamera ? root.expandedCamera.id : 0
                profile: "main"
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
            Item { Layout.fillWidth: true }
        }
        }
    }
}
