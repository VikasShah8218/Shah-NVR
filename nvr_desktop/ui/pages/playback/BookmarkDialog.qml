import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Add a bookmark at a moment (openAdd) or edit one (openEdit). Port of BookmarkDialog in
// nvr_client/src/features/playback/BookmarksPanel.tsx. Editing changes note / label / colour only;
// the time stays where it was recorded.
AppDialog {
    id: dialog

    readonly property var colors: ["#f59e0b", "#ef4444", "#22c55e", "#3b82f6", "#8b5cf6"]
    readonly property var lengths: [
        { value: 0, label: "Point" }, { value: 10, label: "10 s" }, { value: 30, label: "30 s" },
        { value: 60, label: "1 min" }, { value: 300, label: "5 min" }
    ]
    property int editId: 0          // 0 = adding
    property double startMs: 0
    property int lengthSeconds: 0
    property string color: colors[0]
    readonly property bool valid: noteField.text.trim().length > 0 && (editId > 0 || startMs > 0)

    function openAdd(atMs) {
        editId = 0
        startMs = atMs > 0 ? atMs : Playback.nowMs()
        timeField.text = Qt.formatDateTime(new Date(startMs), "yyyy-MM-dd HH:mm:ss")
        lengthSeconds = 0
        noteField.text = ""
        labelField.text = ""
        color = colors[0]
        open()
        noteField.forceActiveFocus()
    }
    function openEdit(row) {
        editId = row.id
        startMs = row.startMs
        noteField.text = row.note
        labelField.text = row.label ?? ""
        color = row.color ?? colors[0]
        open()
        noteField.forceActiveFocus()
    }
    function parseLocal(text) {
        const value = Date.fromLocaleString(Qt.locale(), text, "yyyy-MM-dd HH:mm:ss")
        return value && !isNaN(value.getTime()) ? value.getTime() : 0
    }
    function save() {
        if (editId > 0)
            Bookmarks.update(editId, noteField.text, labelField.text, color)
        else
            Bookmarks.create(startMs, lengthSeconds, noteField.text, labelField.text, color)
        close()
    }

    title: editId > 0 ? "Edit bookmark" : "Add bookmark"
    description: editId > 0 ? Fmt.dateTime(startMs) : "Mark this moment with a note you can search later."

    GridLayout {
        visible: dialog.editId === 0
        columns: 2; columnSpacing: 12; rowSpacing: 6; Layout.fillWidth: true
        AppText { text: "Time"; font.weight: Font.Medium }
        AppText { text: "Length"; font.weight: Font.Medium }
        AppInput {
            id: timeField
            objectName: "bookmarkTime"
            Layout.fillWidth: true
            placeholderText: "yyyy-MM-dd HH:mm:ss"
            onTextChanged: dialog.startMs = dialog.parseLocal(text)
        }
        AppSelect {
            Layout.fillWidth: true
            options: dialog.lengths
            value: dialog.lengthSeconds
            onPicked: v => dialog.lengthSeconds = Number(v)
        }
    }
    AppText { text: "Note"; font.weight: Font.Medium }
    AppTextArea {
        id: noteField
        objectName: "bookmarkNote"
        Layout.fillWidth: true
        Layout.preferredHeight: 80
        placeholderText: "What happened?"
        onTextChanged: if (length > 4000) remove(4000, length)
    }
    GridLayout {
        columns: 2; columnSpacing: 12; rowSpacing: 6; Layout.fillWidth: true
        AppText { text: "Label (optional)"; font.weight: Font.Medium }
        AppText { text: "Colour"; font.weight: Font.Medium }
        AppInput { id: labelField; Layout.fillWidth: true; maximumLength: 64; placeholderText: "e.g. vehicle" }
        Row {
            spacing: 8
            Layout.alignment: Qt.AlignVCenter
            Repeater {
                model: dialog.colors
                delegate: Rectangle {
                    required property string modelData
                    width: 24; height: 24; radius: 12
                    color: modelData
                    border.width: dialog.color === modelData ? 2 : 0
                    border.color: Theme.foreground
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: dialog.color = parent.modelData
                    }
                }
            }
        }
    }
    footer: [
        Item { Layout.fillWidth: true },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: dialog.close() },
        AppButton { text: dialog.editId > 0 ? "Save" : "Add bookmark"; enabled: dialog.valid; onClicked: dialog.save() }
    ]
}
