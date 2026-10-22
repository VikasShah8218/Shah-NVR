import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "theme"
import "layout"
import "components"

// App shell (port of AppLayout.tsx): sidebar + top bar + the current page, toasts on top.
ApplicationWindow {
    id: window

    readonly property var pages: ({
        dashboard: "pages/dashboard/DashboardPage.qml",
        live: "pages/live/LivePage.qml",
        playback: "pages/playback/PlaybackPage.qml",
        cameras: "pages/cameras/CamerasPage.qml",
        camera: "pages/cameras/CameraDetailPage.qml",
        discover: "pages/onvif/DiscoverPage.qml",
        nodes: "pages/nodes/NodesPage.qml",
        node: "pages/nodes/NodeDetailPage.qml",
        assignments: "pages/assignments/AssignmentsPage.qml",
        settings: "pages/settings/SettingsPage.qml"
    })

    // Live View fullscreen: hide the sidebar and top bar and fill the screen (F11 / Esc).
    property bool immersive: false
    property int visibilityBeforeImmersive: Window.Windowed
    onImmersiveChanged: {
        if (immersive) {
            visibilityBeforeImmersive = visibility
            showFullScreen()
        } else {
            visibility = visibilityBeforeImmersive === Window.FullScreen ? Window.Windowed : visibilityBeforeImmersive
        }
    }

    width: 1480
    height: 920
    minimumWidth: 1100
    minimumHeight: 700
    visible: true
    title: ProductName
    color: Theme.background
    font.family: Theme.font

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Sidebar { visible: !window.immersive; Layout.fillHeight: true }

        ColumnLayout {
            spacing: 0
            Layout.fillWidth: true
            Layout.fillHeight: true

            Topbar { visible: !window.immersive; Layout.fillWidth: true }

            Loader {
                id: page
                Layout.fillWidth: true
                Layout.fillHeight: true
                source: window.pages[Router.page]
                asynchronous: false
            }
        }
    }

    Toaster {
        parent: Overlay.overlay
        z: 1000
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 16
    }

    Shortcut { sequence: "Alt+Left"; onActivated: Router.back() }
    Shortcut { sequence: "F11"; enabled: Router.page === "live"; onActivated: window.immersive = !window.immersive }
    Shortcut { sequence: "Esc"; enabled: window.immersive; onActivated: window.immersive = false }
    Shortcut { sequence: "F5"; onActivated: { Cluster.refresh(); Cameras.refresh(); Nodes.refresh() } }
}
