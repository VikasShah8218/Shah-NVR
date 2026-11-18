import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Port of nvr_client/src/features/schedules/SchedulesPage.tsx: weekly recording plans. Open with perm 20 (edit) or
// 40 (view). Set a camera to a schedule in its Edit form, or a whole group from the Groups page.
PageScroll {
    id: root
    objectName: "schedulesPage"

    readonly property bool canEdit: Auth.allowed["20"] === true
    readonly property var columns: [
        { title: "Name", width: 0 }, { title: "Week (Mon–Sun)", width: 180 }, { title: "Now", width: 290 },
        { title: "Cameras", width: 70 }, { title: "", width: 40 }
    ]

    // Rows are passed by id: a delegate's `model` is a QML object, not the plain dict the Python editor needs
    // (bug 2026-11-17: Edit did not open the editor).
    function openEditor(id) {
        const s = Schedules.byId(id)
        if (s)
            editor.openFor(s, !root.canEdit)
    }

    Component.onCompleted: Schedules.setActive(true)
    Component.onDestruction: Schedules.setActive(false)

    PageHeader {
        title: "Recording schedules"
        description: "Weekly plans for when cameras record. Set a camera to a schedule in its Edit form, or a whole group "
            + "from the Groups page." + (Schedules.siteText ? " " + Schedules.siteText : "")
        AppButton {
            visible: root.canEdit
            objectName: "newSchedule"
            text: "New schedule"
            iconName: "plus"
            onClicked: editor.openFor(null, false)
        }
    }

    LoadingState { visible: Schedules.loading && Schedules.error === "" && Schedules.count === 0 }
    ErrorState { text: Schedules.error }
    EmptyState {
        visible: !Schedules.loading && Schedules.error === "" && Schedules.count === 0
        iconName: "calendar-clock"
        title: "No schedules yet"
        text: "Cameras record all the time until you give them a schedule. Create one, e.g. office hours or nights only."
    }

    Rectangle {
        visible: Schedules.count > 0
        Layout.fillWidth: true
        implicitHeight: table.implicitHeight
        radius: Theme.radiusLg
        color: Theme.card
        border.color: Theme.border
        clip: true

        ColumnLayout {
            id: table
            width: parent.width
            spacing: 0
            TableHeader { columns: root.columns }
            Repeater {
                model: Schedules.listModel
                delegate: TableRow {
                    id: row
                    required property var model
                    objectName: "scheduleRow-" + row.model.id
                    clickable: true
                    onClicked: root.openEditor(row.model.id)
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        spacing: 2
                        AppText { text: row.model.name; font.weight: Font.Medium; Layout.fillWidth: true }
                        AppText { text: row.model.summary; variant: "small"; Layout.fillWidth: true }
                    }
                    Item {
                        Layout.preferredWidth: 180
                        implicitHeight: strip.implicitHeight
                        WeekStrip { id: strip; width: 160; rows: row.model.rows }
                    }
                    RowLayout {
                        Layout.fillWidth: false  // nested layouts fill by default; the Name column must get the space
                        Layout.preferredWidth: 290
                        spacing: 6
                        readonly property color tone: row.model.state === "continuous" ? Theme.success
                            : row.model.state === "event" ? Theme.warning : Theme.mutedForeground
                        Rectangle { width: 6; height: 6; radius: 3; color: parent.tone }
                        AppText {
                            text: row.model.nowText
                            color: parent.tone
                            Layout.fillWidth: true
                        }
                    }
                    AppText { text: String(row.model.cameraCount); horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 70 }
                    AppButton {
                        Layout.preferredWidth: 40
                        variant: "ghost"; size: "icon"; iconName: "ellipsis"
                        onClicked: rowMenu.openFor(Schedules.byId(row.model.id), this)
                    }
                }
            }
        }
    }

    AppMenu {
        id: rowMenu
        property var schedule: ({})
        function openFor(s, button) {
            schedule = s
            popup(button, button.width - width, button.height + 4)
        }
        AppMenuItem { visible: root.canEdit; height: visible ? implicitHeight : 0; text: "Edit"; iconName: "pencil"; onTriggered: root.openEditor(rowMenu.schedule.id) }
        AppMenuItem { visible: !root.canEdit; height: visible ? implicitHeight : 0; text: "View"; iconName: "eye"; onTriggered: root.openEditor(rowMenu.schedule.id) }
        AppMenuItem {
            visible: root.canEdit; height: visible ? implicitHeight : 0
            text: "Delete"; iconName: "trash-2"; danger: true
            onTriggered: deleteDialog.openFor(rowMenu.schedule)
        }
    }

    ScheduleEditorDialog { id: editor }

    ConfirmDialog {
        id: deleteDialog
        property var schedule: ({})
        function openFor(s) { schedule = s; open() }
        title: 'Delete "' + (schedule.name ?? "") + '"?'
        description: (schedule.cameraCount ?? 0) > 0
            ? schedule.cameraCount + (schedule.cameraCount === 1 ? " camera uses" : " cameras use")
              + " this schedule. Move them to another schedule (or Always) first."
            : "No camera uses this schedule."
        confirmLabel: "Delete"
        destructive: true
        onConfirmed: Schedules.remove(schedule.id)
    }
}
