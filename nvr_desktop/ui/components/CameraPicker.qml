import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

// Searchable camera select (port of the web CameraPicker). `store` is a CameraOptionsStore singleton
// (PlaybackCameras...): the list is searched on the server and loaded 50 at a time, never all cameras.
//   CameraPicker { store: PlaybackCameras; value: Playback.cameraId; label: Playback.cameraName; onPicked: id => ... }
AppButton {
    id: root

    property var store
    property int value: 0
    property string label: ""
    signal picked(int cameraId)

    variant: "outline"
    implicitWidth: 224
    onClicked: popup.open()

    // looks like AppSelect: name on the left, chevron on the right
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 10
        spacing: 8
        AppText {
            objectName: "cameraPickerLabel"
            text: root.label !== "" ? root.label : root.value > 0 ? "Camera #" + root.value : "Select camera"
            color: root.label !== "" || root.value > 0 ? Theme.foreground : Theme.mutedForeground
            Layout.fillWidth: true
        }
        Icon { name: "chevron-down"; size: 16; color: Theme.mutedForeground }
    }

    Popup {
        id: popup
        y: root.height + 4
        width: 288
        height: Math.min(380, content.implicitHeight + 16)
        padding: 8
        background: Rectangle { color: Theme.popover; radius: Theme.radius; border.color: Theme.border }
        onOpened: search.forceActiveFocus()

        ColumnLayout {
            id: content
            anchors.fill: parent
            spacing: 6
            AppInput {
                id: search
                objectName: "cameraPickerSearch"
                Layout.fillWidth: true
                iconName: "search"
                placeholderText: "Search name or #id"
                text: root.store ? root.store.search : ""
                onTextChanged: if (root.store) root.store.setSearch(text)
            }
            ListView {
                id: list
                Layout.fillWidth: true
                Layout.fillHeight: true
                implicitHeight: Math.min(300, contentHeight)
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: root.store ? root.store.listModel : null
                ScrollBar.vertical: AppScrollBar {}
                delegate: Rectangle {
                    id: option
                    required property var model
                    width: list.width
                    height: 32
                    radius: Theme.radiusSm
                    color: optionArea.containsMouse ? Theme.accent : "transparent"
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        spacing: 8
                        StatusDot { status: option.model.status }
                        AppText { text: option.model.name; Layout.fillWidth: true }
                        Icon { visible: option.model.id === root.value; name: "check"; size: 14; color: Theme.primary }
                    }
                    MouseArea {
                        id: optionArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            root.picked(option.model.id)
                            popup.close()
                        }
                    }
                }
                footer: AppButton {
                    visible: !!root.store && root.store.hasMore
                    width: visible ? list.width : 0
                    height: visible ? 30 : 0
                    variant: "ghost"
                    size: "sm"
                    text: root.store && root.store.loadingMore ? "Loading…" : root.store ? root.store.moreLabel : ""
                    onClicked: root.store.loadMore()
                }
            }
            AppText {
                visible: !!root.store && !root.store.loading && root.store.total === 0
                text: root.store && root.store.query !== "" ? "No cameras match." : "No cameras."
                variant: "muted"
            }
        }
    }
}
