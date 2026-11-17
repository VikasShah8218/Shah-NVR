import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// "When to record": Always | Schedule (+ which one) | Never (port of nvr_client features/schedules/RecordingFields.tsx).
// Used by the camera form and the Apply dialog. Set `mode` / `scheduleId`; read them back after `changed`.
ColumnLayout {
    id: fields

    property string mode: "always"
    property int scheduleId: 0
    // what the camera does right now, shown while the saved setting is unchanged (camera form only)
    property var current: null  // {mode, scheduleId, recordingNow, nextChange}
    signal changed()

    readonly property var chosen: { Schedules.count; return scheduleId > 0 ? Schedules.byId(scheduleId) : null }
    readonly property bool unchanged: current !== null && current.mode === mode
        && (mode !== "schedule" || current.scheduleId === scheduleId)
    readonly property string hint: unchanged ? Schedules.nowText(current.recordingNow, current.nextChange || "")
        : mode === "always" ? "Records all the time."
        : mode === "never" ? "Never records; live view still works."
        : chosen ? "With this schedule: " + Schedules.lowerFirst(chosen.nowText) : "Pick a schedule."

    function pick(m, id) {
        mode = m
        scheduleId = id
        changed()
    }

    Component.onCompleted: Schedules.ensureLoaded()
    spacing: 6

    AppText { text: "Recording"; font.weight: Font.Medium }
    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        ToggleGroup {
            objectName: "recordingMode"
            options: [{ value: "always", label: "Always" }, { value: "schedule", label: "Schedule" }, { value: "never", label: "Never" }]
            value: fields.mode
            onPicked: v => fields.pick(v, v === "schedule"
                ? (fields.scheduleId > 0 ? fields.scheduleId : (Schedules.items.length > 0 ? Schedules.items[0].id : 0)) : 0)
        }
        AppSelect {
            objectName: "recordingSchedule"
            visible: fields.mode === "schedule" && Schedules.count > 0
            Layout.fillWidth: true
            placeholder: "Choose a schedule"
            options: Schedules.items.map(s => ({ value: s.id, label: s.name }))
            value: fields.scheduleId > 0 ? fields.scheduleId : undefined
            onPicked: v => fields.pick("schedule", v)
        }
        AppText {
            visible: fields.mode === "schedule" && Schedules.count === 0
            text: Schedules.loading ? "Loading…" : "No schedules yet. Create one on the Schedules page."
            variant: "small"
            Layout.fillWidth: true
        }
    }
    WeekStrip {
        visible: fields.mode === "schedule" && fields.chosen !== null
        Layout.fillWidth: true
        Layout.maximumWidth: 380
        rows: fields.chosen ? fields.chosen.rows : [[], [], [], [], [], [], []]
    }
    AppText {
        Layout.fillWidth: true
        variant: "small"
        wrapMode: Text.WordWrap
        text: fields.hint + (/[.:]$/.test(fields.hint) ? "" : ".") + " Applies to streams set to Record."
    }
}
