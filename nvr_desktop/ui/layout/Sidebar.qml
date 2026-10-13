import QtQuick
import QtQuick.Layouts
import App
import "../theme"
import "../components"

// Left navigation (port of AppLayout.tsx sidebar). Collapses to icons; the state is remembered.
Rectangle {
    id: sidebar

    readonly property bool collapsed: Prefs.sidebarCollapsed
    readonly property var items: [
        { page: "dashboard", label: "Dashboard", icon: "gauge" },
        { page: "live", label: "Live View", icon: "monitor-play" },
        { page: "playback", label: "Playback", icon: "history" },
        { page: "cameras", label: "Cameras", icon: "camera" },
        { page: "nodes", label: "Media Nodes", icon: "server" },
        { page: "assignments", label: "Assignments", icon: "arrow-left-right" },
        { page: "settings", label: "Settings", icon: "settings" }
    ]
    // detail pages highlight their parent section
    readonly property string section: Router.page === "camera" ? "cameras" : Router.page === "node" ? "nodes" : Router.page

    implicitWidth: collapsed ? 64 : 224
    color: Theme.sidebar
    Behavior on implicitWidth { NumberAnimation { duration: 160 } }

    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.sidebarAccent }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // brand
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 56
            Layout.leftMargin: 16
            spacing: 10
            Rectangle {
                width: 32
                height: 32
                radius: Theme.radius
                color: Theme.primary
                Icon { anchors.centerIn: parent; name: "video"; size: 18; color: Theme.primaryForeground }
            }
            AppText {
                visible: !sidebar.collapsed
                text: "Shah-NVR"
                font.pixelSize: Theme.textBase
                font.weight: Font.DemiBold
                Layout.fillWidth: true
            }
        }

        // navigation
        ColumnLayout {
            Layout.fillWidth: true
            Layout.margins: 8
            spacing: 4
            Repeater {
                model: sidebar.items
                delegate: Rectangle {
                    required property var modelData
                    readonly property bool active: sidebar.section === modelData.page

                    Layout.fillWidth: true
                    implicitHeight: 36
                    radius: Theme.radiusSm + 2
                    color: active ? Theme.sidebarAccent : area.containsMouse ? Theme.alpha(Theme.sidebarAccent, 0.6) : "transparent"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: sidebar.collapsed ? 0 : 12
                        spacing: 12
                        Item { visible: sidebar.collapsed; Layout.fillWidth: true }
                        Icon {
                            name: modelData.icon
                            size: 18
                            color: active ? Theme.primary : Theme.sidebarForeground
                        }
                        AppText {
                            visible: !sidebar.collapsed
                            text: modelData.label
                            color: active ? Theme.primary : Theme.sidebarForeground
                            font.weight: active ? Font.Medium : Font.Normal
                            Layout.fillWidth: true
                        }
                        Item { visible: sidebar.collapsed; Layout.fillWidth: true }
                    }
                    MouseArea {
                        id: area
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: Router.go(modelData.page)
                    }
                    AppToolTip {
                        visible: sidebar.collapsed && area.containsMouse
                        text: modelData.label
                        x: parent.width + 8
                        y: (parent.height - height) / 2
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }

        AppButton {
            Layout.fillWidth: true
            Layout.margins: 8
            variant: "ghost"
            size: "sm"
            iconName: sidebar.collapsed ? "panel-left-open" : "panel-left-close"
            text: sidebar.collapsed ? "" : "Collapse"
            onClicked: Prefs.sidebarCollapsed = !Prefs.sidebarCollapsed
        }
    }
}
