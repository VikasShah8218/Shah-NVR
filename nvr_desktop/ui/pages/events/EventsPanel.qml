import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Event list: this camera (Playback) or every camera (Events page), newest first, filter by type.
// Click a row to play it from the camera's pre-event seconds (`opened(row)`). Port of nvr_client
// features/events/EventsPanel.tsx.
Card {
    id: panel
    objectName: "eventsPanel"

    property bool allCameras: false  // Events page: no scope toggle, always every visible camera
    property int maxListHeight: 320
    property var pendingDelete: null
    signal opened(var row)

    readonly property bool showCamera: allCameras || Events.scope === "all"

    spacing: 10

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        Icon { name: "flag"; size: 16; color: Theme.foreground }
        AppText { text: "Events"; font.weight: Font.Medium }
        Spinner { visible: Events.loading; size: 14 }
        Item { Layout.fillWidth: true }
        AppSelect {
            objectName: "eventTypeFilter"
            implicitWidth: 160
            options: Events.typeOptions
            value: Events.type
            onPicked: v => Events.setType(v)
        }
        ToggleGroup {
            visible: !panel.allCameras
            options: [{ value: "camera", label: "This camera" }, { value: "all", label: "All cameras" }]
            value: Events.scope
            onPicked: v => Events.setScope(v)
        }
    }

    ErrorState { text: Events.error }
    AppText {
        visible: Events.error === "" && Events.rows.length === 0
        text: Events.type !== "" ? "No events of this type."
            : "No events yet. Use “Mark event”, or wait for a camera event (e.g. video loss)."
        variant: "muted"
    }

    ListView {
        id: list
        objectName: "eventsList"
        visible: Events.rows.length > 0
        Layout.fillWidth: true
        Layout.preferredHeight: panel.maxListHeight > 0 ? Math.min(contentHeight, panel.maxListHeight) : contentHeight
        clip: true
        spacing: 6
        boundsBehavior: Flickable.StopAtBounds
        interactive: panel.maxListHeight > 0
        model: Events.rows
        ScrollBar.vertical: AppScrollBar {}
        delegate: Rectangle {
            id: row
            required property var modelData
            width: list.width
            implicitHeight: rowLayout.implicitHeight + 20
            radius: Theme.radius
            color: rowHover.hovered ? Theme.alpha(Theme.accent, 0.45) : "transparent"
            border.color: Theme.border

            HoverHandler { id: rowHover }
            MouseArea {  // under the row's content: the buttons on top keep their own clicks
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: panel.opened(row.modelData)
            }

            RowLayout {
                id: rowLayout
                anchors.fill: parent
                anchors.margins: 10
                spacing: 10
                Rectangle {
                    Layout.alignment: Qt.AlignTop
                    Layout.topMargin: 4
                    width: 10; height: 10; radius: 5
                    color: row.modelData.color
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    RowLayout {
                        spacing: 8
                        AppText { text: Fmt.dateTime(row.modelData.startMs); variant: "small" }
                        AppText {
                            visible: row.modelData.duration !== ""
                            text: row.modelData.duration
                            variant: "small"
                            color: row.modelData.ongoing ? Theme.warning : Theme.mutedForeground
                        }
                        AppText {
                            visible: panel.showCamera
                            text: row.modelData.camera_name
                            font.weight: Font.Medium
                            font.pixelSize: Theme.textXs
                        }
                        AppText { text: row.modelData.source; variant: "small"; elide: Text.ElideRight; Layout.maximumWidth: 200 }
                    }
                    AppText { text: row.modelData.title; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true }
                }
                AppButton {
                    visible: Auth.allowed["4"] === true && row.modelData.ongoing
                    variant: "ghost"; size: "icon"; iconName: "square"; tip: "End this event now"
                    onClicked: Events.end(row.modelData.id)
                }
                AppButton {
                    visible: Auth.allowed["4"] === true
                    variant: "ghost"; size: "icon"; iconName: "bookmark-plus"; tip: "Save as bookmark"
                    onClicked: Events.saveAsBookmark(row.modelData)
                }
                AppButton {
                    visible: Auth.allowed["20"] === true
                    variant: "ghost"; size: "icon"; iconName: "trash-2"; tip: "Delete event mark"
                    onClicked: { panel.pendingDelete = row.modelData; confirmDelete.open() }
                }
            }
        }
    }

    Pager {
        objectName: "eventsPager"
        Layout.fillWidth: true
        page: Events.page
        pageSize: Events.pageSize
        total: Events.total
        onPaged: p => Events.setPage(p)
    }

    ConfirmDialog {
        id: confirmDelete
        title: "Delete this event mark?"
        description: "Video already kept for it stays until its retention ends."
        confirmLabel: "Delete"
        destructive: true
        onConfirmed: if (panel.pendingDelete) Events.remove(panel.pendingDelete.id)
    }
}
