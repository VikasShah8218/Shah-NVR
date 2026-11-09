import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Searchable bookmark list: this camera or all cameras, newest first. Click a row to play it (switches
// camera / profile / day). Port of BookmarksPanel in nvr_client/src/features/playback/BookmarksPanel.tsx.
Card {
    id: panel
    objectName: "bookmarksPanel"

    property var dialog            // the page's BookmarkDialog (shared with the toolbar's "Bookmark")
    property var pendingDelete: null

    spacing: 10

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        Icon { name: "bookmark"; size: 16; color: Theme.foreground }
        AppText { text: "Bookmarks"; font.weight: Font.Medium }
        Item { Layout.fillWidth: true }
        AppInput {
            implicitWidth: 224
            iconName: "search"
            placeholderText: "Search notes"
            text: Bookmarks.query
            onTextEdited: Bookmarks.setQuery(text)
        }
        ToggleGroup {
            options: [{ value: "camera", label: "This camera" }, { value: "all", label: "All cameras" }]
            value: Bookmarks.scope
            onPicked: v => Bookmarks.setScope(v)
        }
    }

    ErrorState { text: Bookmarks.error }
    AppText {
        visible: Bookmarks.error === "" && Bookmarks.rows.length === 0
        text: Bookmarks.query.trim() !== "" ? "No bookmarks match."
            : "No bookmarks yet. Use “Bookmark” above the player to mark a moment."
        variant: "muted"
    }

    ListView {
        id: list
        visible: Bookmarks.rows.length > 0
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(contentHeight, 320)
        clip: true
        spacing: 6
        boundsBehavior: Flickable.StopAtBounds
        model: Bookmarks.rows
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
            // under the row's content: the edit / delete buttons on top keep their own clicks
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: Playback.openBookmark(row.modelData.camera_id, row.modelData.profile ?? "", row.modelData.startMs)
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
                    color: row.modelData.color ? row.modelData.color : Theme.primary
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    RowLayout {
                        spacing: 8
                        AppText { text: Fmt.dateTime(row.modelData.startMs); variant: "small" }
                        AppText { visible: row.modelData.endMs > 0; text: "→ " + Fmt.time(row.modelData.endMs); variant: "small" }
                        AppText {
                            visible: Bookmarks.scope === "all"
                            text: row.modelData.camera_name
                            font.weight: Font.Medium
                            font.pixelSize: Theme.textXs
                        }
                        Rectangle {
                            visible: !!row.modelData.label
                            radius: 3
                            color: Theme.muted
                            implicitWidth: chip.implicitWidth + 10
                            implicitHeight: chip.implicitHeight + 4
                            AppText { id: chip; anchors.centerIn: parent; text: row.modelData.label ?? ""; font.pixelSize: 11 }
                        }
                    }
                    AppText { text: row.modelData.note; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true }
                }
                AppButton {
                    variant: "ghost"; size: "icon"; iconName: "pencil"; tip: "Edit bookmark"
                    onClicked: panel.dialog.openEdit(row.modelData)
                }
                AppButton {
                    variant: "ghost"; size: "icon"; iconName: "trash-2"; tip: "Delete bookmark"
                    onClicked: { panel.pendingDelete = row.modelData; confirmDelete.open() }
                }
            }
        }
    }

    ConfirmDialog {
        id: confirmDelete
        title: "Delete this bookmark?"
        description: panel.pendingDelete ? panel.pendingDelete.note : ""
        confirmLabel: "Delete"
        destructive: true
        onConfirmed: if (panel.pendingDelete) Bookmarks.remove(panel.pendingDelete.id)
    }
}
