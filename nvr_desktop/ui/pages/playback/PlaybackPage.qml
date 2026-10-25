import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"
import "../../video"

// Port of nvr_client/src/features/playback/PlaybackPage.tsx (+ VodPlayer.tsx):
// camera / profile / day pickers, HH:MM:SS go-to, VLC URL, the recording player with its wall clock,
// the day timeline (zoom, pan, click-to-play) and the chunks in view (click to play, download MP4).
PageScroll {
    id: root
    objectName: "playbackPage"

    readonly property var appWindow: ApplicationWindow.window
    readonly property bool fullscreen: !!appWindow && appWindow.immersive
    readonly property var player: video.player
    readonly property bool hasSource: Playback.playlistUrl !== ""
    readonly property var zooms: [
        { value: 86400000, label: "24h" }, { value: 21600000, label: "6h" },
        { value: 3600000, label: "1h" }, { value: 600000, label: "10m" }
    ]

    function openFromRouter() {
        const p = Router.params ?? {}
        if (p.camera)
            Playback.openAt(p.camera, p.profile ?? "", p.t ?? 0)
    }

    Component.onCompleted: openFromRouter()
    Component.onDestruction: if (appWindow) appWindow.immersive = false
    Connections {
        target: Router
        function onChanged() { if (Router.page === "playback") root.openFromRouter() }
    }

    PageHeader { title: "Playback"; description: "Browse and play recordings. Click the timeline to play from that moment." }

    EmptyState {
        visible: !Cameras.loading && Cameras.error === "" && Cameras.listModel.count === 0
        iconName: "film"
        title: "No cameras yet"
        text: "Add a camera first; its recordings will appear here."
    }

    // ================================================================= toolbar
    RowLayout {
        visible: Cameras.listModel.count > 0
        Layout.fillWidth: true
        spacing: 8

        AppSelect {
            implicitWidth: 224
            options: Cameras.all.map(c => ({ value: c.id, label: c.name }))
            value: Playback.cameraId || null
            placeholder: "Select camera"
            onPicked: v => Playback.setCamera(v)
        }
        AppSelect {
            implicitWidth: 112
            options: Playback.profiles
            value: Playback.profile
            onPicked: v => Playback.setProfile(v)
        }

        // day: ‹ [calendar] ›
        Row {
            spacing: -1
            AppButton { variant: "outline"; size: "icon"; iconName: "chevron-left"; tip: "Previous day"; onClicked: Playback.previousDay() }
            AppButton {
                id: dayButton
                variant: "outline"
                iconName: "calendar-days"
                text: Fmt.day(Playback.day)
                onClicked: calendar.open()
                CalendarPopup {
                    id: calendar
                    y: dayButton.height + 4
                    selected: new Date(Playback.day)
                    onPicked: d => { Playback.setDay(d.getTime()); calendar.close() }
                }
            }
            AppButton {
                variant: "outline"; size: "icon"; iconName: "chevron-right"; tip: "Next day"
                enabled: !Playback.isToday
                onClicked: Playback.nextDay()
            }
        }

        AppInput {
            id: gotoField
            implicitWidth: 112
            placeholderText: "HH:MM:SS"
            onAccepted: Playback.goTo(text)
        }
        AppButton { text: "Go"; variant: "outline"; onClicked: Playback.goTo(gotoField.text) }

        Item { Layout.fillWidth: true }
        AppButton {
            text: "Export"
            iconName: "download"
            enabled: Playback.cameraId > 0 && Playback.hasTimeline
            onClicked: exportDialog.openDefault()
        }
        AppButton {
            text: "VLC URL"
            iconName: "copy"
            variant: "outline"
            enabled: root.hasSource
            onClicked: Utils.copy(Playback.playlistUrl, "Playlist URL copied (open it in VLC)")
        }
    }

    // ================================================================= player
    // Placeholder in the page; the player itself moves to the window overlay in fullscreen.
    Item {
        id: playerSlot
        visible: Cameras.listModel.count > 0
        Layout.fillWidth: true
        // Height-capped so the timeline below stays on screen (web: max-w-[calc(55vh*16/9)]).
        readonly property real videoHeight: Math.min(width * 9 / 16, (root.appWindow ? root.appWindow.height : 900) * 0.55)
        implicitHeight: videoHeight + controls.implicitHeight

        Rectangle {
            id: playerFrame
            parent: root.fullscreen ? Overlay.overlay : playerSlot
            anchors.fill: parent
            z: root.fullscreen ? 500 : 0
            color: Theme.video
            radius: root.fullscreen ? 0 : Theme.radiusLg
            border.color: root.fullscreen ? "transparent" : Theme.border
            clip: true

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: playerFrame.border.color === "transparent" ? 0 : 1
                spacing: 0

                // viewport: the video is scaled/panned inside it (digital zoom); overlays stay unscaled
                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true

                    VideoView {
                        id: video
                        anchors.fill: parent
                        mode: "playback"
                        source: Playback.playlistUrl
                        player.muted: !Playback.hasAudio
                        player.volume: Prefs.playbackVolume
                        showInfo: false
                        waitingText: "Click on the timeline to start playback"
                        scale: playbackZoom.zoom
                        transformOrigin: Item.Center
                        transform: Translate {
                            x: playbackZoom.panX
                            y: playbackZoom.panY
                        }

                        // the real recorded time of the frame on screen → playhead
                        Connections {
                            target: video.player
                            function onTimePosChanged() {
                                if (root.hasSource && video.player.playState === "playing")
                                    Playback.setPlayhead(video.player.wallClockMs())
                            }
                        }
                    }

                    // wall clock overlay
                    Rectangle {
                        visible: root.hasSource && video.player.playState === "playing"
                        anchors.top: parent.top
                        anchors.right: parent.right
                        anchors.margins: 8
                        z: 3
                        radius: 4
                        color: Qt.rgba(0, 0, 0, 0.55)
                        implicitWidth: wallText.implicitWidth + 16
                        implicitHeight: wallText.implicitHeight + 8
                        Text {
                            id: wallText
                            anchors.centerIn: parent
                            text: Fmt.dateTime(Playback.playhead)
                            color: "white"
                            font.family: Theme.font
                            font.pixelSize: Theme.textSm
                            font.weight: Font.Medium
                        }
                    }

                    // click = play/pause, double-click = fullscreen, wheel/drag/keys = digital zoom and pan
                    DigitalZoom {
                        id: playbackZoom
                        objectName: "playbackZoom"
                        anchors.fill: parent
                        z: 2
                        visible: root.hasSource
                        doubleClickResets: false
                        onClicked: video.player.paused = !video.player.paused
                        onDoubleClicked: root.appWindow.immersive = !root.appWindow.immersive
                        onVisibleChanged: if (!visible) reset()
                    }
                    Connections {
                        target: Playback
                        function onSelectionChanged() { playbackZoom.reset() }
                    }
                }

                // control bar
                Rectangle {
                    id: controls
                    Layout.fillWidth: true
                    implicitHeight: 48
                    color: Theme.alpha(Theme.card, 0.6)
                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 6
                        AppButton { variant: "ghost"; size: "icon"; iconName: "skip-back"; tip: "Back 1 min"; enabled: root.hasSource; onClicked: video.player.seekRelative(-60) }
                        AppButton { variant: "ghost"; size: "icon"; iconName: "rewind"; tip: "Back 10 s"; enabled: root.hasSource; onClicked: video.player.seekRelative(-10) }
                        AppButton {
                            size: "icon"
                            iconName: video.player.paused ? "play" : "pause"
                            implicitWidth: 36
                            implicitHeight: 36
                            radius: 18
                            enabled: root.hasSource
                            onClicked: video.player.paused = !video.player.paused
                        }
                        AppButton { variant: "ghost"; size: "icon"; iconName: "fast-forward"; tip: "Forward 10 s"; enabled: root.hasSource; onClicked: video.player.seekRelative(10) }
                        AppButton { variant: "ghost"; size: "icon"; iconName: "skip-forward"; tip: "Forward 1 min"; enabled: root.hasSource; onClicked: video.player.seekRelative(60) }
                        AppText {
                            Layout.leftMargin: 8
                            text: root.hasSource && Playback.playhead ? Fmt.dateTime(Playback.playhead) : "—"
                            variant: "muted"
                        }
                        Item { Layout.fillWidth: true }
                        AppButton {
                            visible: Playback.hasAudio
                            variant: "ghost"; size: "icon"
                            iconName: video.player.muted ? "volume-x" : "volume-2"
                            tip: video.player.muted ? "Listen to recorded audio" : "Mute audio"
                            onClicked: video.player.muted = !video.player.muted
                        }
                        Slider {
                            id: volumeSlider
                            visible: Playback.hasAudio && !video.player.muted
                            implicitWidth: 100
                            implicitHeight: 24
                            leftPadding: 0
                            rightPadding: 0
                            from: 0; to: 1; value: Prefs.playbackVolume
                            onMoved: Prefs.playbackVolume = value

                            background: Rectangle {
                                x: volumeSlider.leftPadding
                                y: volumeSlider.topPadding + (volumeSlider.availableHeight - height) / 2
                                width: volumeSlider.availableWidth
                                height: 4
                                radius: 2
                                color: Theme.muted

                                Rectangle {
                                    width: volumeSlider.visualPosition * parent.width
                                    height: parent.height
                                    radius: parent.radius
                                    color: Theme.primary
                                }
                            }

                            handle: Rectangle {
                                x: volumeSlider.leftPadding
                                    + volumeSlider.visualPosition * (volumeSlider.availableWidth - width)
                                y: volumeSlider.topPadding + (volumeSlider.availableHeight - height) / 2
                                implicitWidth: 10
                                implicitHeight: 10
                                radius: 5
                                color: Theme.primary
                                border.width: 1
                                border.color: Theme.card
                            }
                        }
                        AppSelect {
                            implicitWidth: 84
                            implicitHeight: 30
                            options: [0.5, 1, 2, 4, 8].map(r => ({ value: r, label: r + "×" }))
                            value: video.player.speed
                            onPicked: v => video.player.speed = v
                        }
                        AppButton {
                            variant: "ghost"
                            size: "icon"
                            iconName: root.fullscreen ? "minimize" : "maximize"
                            tip: root.fullscreen ? "Exit fullscreen (Esc)" : "Fullscreen"
                            onClicked: root.appWindow.immersive = !root.appWindow.immersive
                        }
                    }
                }
            }
        }
    }

    // ================================================================= timeline
    Card {
        visible: Cameras.listModel.count > 0
        Layout.fillWidth: true
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            ToggleGroup {
                options: root.zooms
                value: Playback.zoom
                onPicked: v => Playback.setZoom(v)
            }
            AppButton {
                visible: Playback.isToday
                text: "Now"
                iconName: "crosshair"
                variant: "ghost"
                size: "sm"
                onClicked: Playback.jumpToNow()
            }
            Item { Layout.fillWidth: true }
            Legend { swatch: Theme.alpha(Theme.success, 0.75); label: "recorded" }
            Legend { swatch: Theme.primary; label: "camera SD backfill" }
            Legend { swatch: Theme.muted; label: "no recording"; outlined: true }
            AppText {
                visible: Playback.hasTimeline
                text: "Coverage " + Playback.coverage.toFixed(1) + "% · " + Playback.totalSize
                variant: "small"
            }
        }

        ErrorState { text: Playback.error }
        Timeline {
            visible: Playback.error === ""
            Layout.fillWidth: true
            barHeight: 64
            ranges: Playback.ranges
            accentRanges: Playback.backfillRanges
            ticks: Playback.ticks
            viewStart: Playback.viewStart
            viewEnd: Playback.viewEnd
            boundsStart: Playback.day
            boundsEnd: Playback.day + 86400000
            playhead: root.hasSource ? Playback.playhead : -1
            pannable: Playback.zoom < 86400000
            onSeek: ms => Playback.seek(ms)
            onPan: start => Playback.pan(start)
        }
    }

    // ================================================================= chunks in view
    Card {
        visible: Cameras.listModel.count > 0
        Layout.fillWidth: true
        padding: 0
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 16
            spacing: 6
            AppText { text: "Chunks in view"; font.weight: Font.Medium }
            AppText { text: "(" + Playback.chunks.length + ")"; variant: "muted" }
        }
        AppText {
            visible: Playback.chunks.length === 0
            text: "No recordings in this window."
            variant: "muted"
            Layout.leftMargin: 16
            Layout.bottomMargin: 16
        }

        TableHeader {
            visible: Playback.chunks.length > 0
            columns: chunkList.columns
        }
        ListView {
            id: chunkList
            readonly property var columns: [
                { title: "Start", width: 0 }, { title: "End", width: 140 }, { title: "Length", width: 110 },
                { title: "Size", width: 100 }, { title: "Audio", width: 100 }, { title: "Origin", width: 100 }, { title: "Node", width: 90 }, { title: "", width: 36 }
            ]
            visible: Playback.chunks.length > 0
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(contentHeight, 320)
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: Playback.chunks
            ScrollBar.vertical: AppScrollBar {}
            delegate: TableRow {
                required property var modelData
                width: chunkList.width
                clickable: true
                onClicked: Playback.seek(modelData.startMs)
                AppText { text: Fmt.time(modelData.startMs); Layout.fillWidth: true }
                AppText { text: Fmt.time(modelData.endMs); Layout.preferredWidth: 140 }
                AppText { text: Fmt.duration(modelData.duration_ms); Layout.preferredWidth: 110 }
                AppText { text: Fmt.bytes(modelData.size_bytes); Layout.preferredWidth: 100 }
                AppText { text: modelData.audio_codec ?? "—"; Layout.preferredWidth: 100 }
                AppText { text: modelData.origin === "CAMERA_SD" ? "Camera SD" : "NVR"; color: modelData.origin === "CAMERA_SD" ? Theme.primary : Theme.foreground; Layout.preferredWidth: 100 }
                AppText { text: "node " + modelData.node_id; variant: "muted"; Layout.preferredWidth: 90 }
                AppButton {
                    variant: "ghost"; size: "icon"; iconName: "download"; tip: "Download MP4"
                    Layout.preferredWidth: 36
                    onClicked: Playback.download(modelData.id, modelData.node_id)
                }
            }
        }
    }

    // ================================================================= export jobs
    Card {
        visible: Playback.exports.length > 0
        Layout.fillWidth: true
        spacing: 10
        AppText { text: "Exports"; font.weight: Font.Medium }
        Repeater {
            model: Playback.exports
            delegate: Rectangle {
                id: exportJob
                required property var modelData
                readonly property bool active: ["QUEUED", "CLAIMED", "PROCESSING", "FINALIZING"].indexOf(modelData.state) >= 0
                Layout.fillWidth: true
                implicitHeight: exportRow.implicitHeight + 20
                radius: Theme.radius
                color: "transparent"
                border.color: Theme.border
                RowLayout {
                    id: exportRow
                    anchors.fill: parent; anchors.margins: 10; spacing: 10
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 4
                        RowLayout {
                            AppText { text: (modelData.mode === "original" ? "Original" : "Compressed") + " · " + modelData.profile; font.weight: Font.Medium }
                            AppText { text: Fmt.dateTime(modelData.start_time) + " – " + Fmt.dateTime(modelData.end_time); variant: "small" }
                            AppText { text: modelData.state; color: modelData.state === "FAILED" ? Theme.danger : modelData.state === "READY" ? Theme.success : Theme.mutedForeground }
                        }
                        ProgressBar { visible: exportJob.active; Layout.fillWidth: true; from: 0; to: 100; value: modelData.progress_percent }
                        AppText { visible: !!modelData.error_message; text: modelData.error_message ?? ""; color: Theme.danger; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        AppText { visible: modelData.gap_seconds > 2; text: "Contains " + Math.round(modelData.gap_seconds) + " seconds without recordings."; color: Theme.warning }
                    }
                    AppButton { visible: modelData.state === "READY"; text: "Download " + Fmt.bytes(modelData.output_size_bytes); iconName: "download"; onClicked: Playback.downloadExport(modelData.id, modelData.output_name ?? "") }
                    AppButton { visible: exportJob.active; text: "Cancel"; variant: "outline"; onClicked: Playback.cancelExport(modelData.id) }
                }
            }
        }
    }

    component Legend: Row {
        property color swatch
        property string label
        property bool outlined: false
        spacing: 6
        Rectangle {
            width: 10; height: 10; radius: 2
            color: swatch
            border.width: outlined ? 1 : 0
            border.color: Theme.border
            anchors.verticalCenter: parent.verticalCenter
        }
        AppText { text: label; variant: "small"; anchors.verticalCenter: parent.verticalCenter }
    }

    ExportDialog { id: exportDialog }
}
