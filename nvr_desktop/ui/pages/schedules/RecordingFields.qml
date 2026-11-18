import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// "When to record": Always | Schedule (+ which one) | Event | Never, plus the event seconds and the event marks
// switch (port of nvr_client features/schedules/RecordingFields.tsx). Used by the camera form and the Apply dialog.
// Set `mode` / `scheduleId` / `events`; read them back after `changed`. `events` null = no event fields.
ColumnLayout {
    id: fields

    property string mode: "always"
    property int scheduleId: 0
    property var events: null  // {pre, post, marking}
    // what the camera does right now, shown while the saved setting is unchanged (camera form only)
    property var current: null  // {mode, scheduleId, state, nextChange}
    signal changed()

    readonly property var chosen: { Schedules.count; return scheduleId > 0 ? Schedules.byId(scheduleId) : null }
    readonly property bool unchanged: current !== null && current.mode === mode
        && (mode !== "schedule" || current.scheduleId === scheduleId)
    readonly property bool usesEvents: mode === "event" || (mode === "schedule" && chosen !== null && chosen.usesEvents)
    readonly property bool eventsValid: events === null || Schedules.eventSettingsValid(events)
    readonly property string hint: unchanged ? Schedules.nowText(current.state, current.nextChange || "")
        : mode === "always" ? "Records all the time."
        : mode === "never" ? "Never records; live view still works."
        : mode === "event" ? "Keeps video only around events (the seconds before and after below)."
        : chosen ? "With this schedule: " + Schedules.lowerFirst(chosen.nowText) : "Pick a schedule."

    function pick(m, id) {
        mode = m
        scheduleId = id
        changed()
    }
    function setEvents(patch) {
        events = Object.assign({}, events, patch)
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
            options: [{ value: "always", label: "Always" }, { value: "schedule", label: "Schedule" },
                      { value: "event", label: "Event" }, { value: "never", label: "Never" }]
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

    // event seconds: only when the mode (or the chosen schedule) keeps video around events
    Rectangle {
        objectName: "eventSeconds"
        visible: fields.events !== null && fields.usesEvents
        Layout.fillWidth: true
        implicitHeight: secondsRow.implicitHeight + 20
        radius: Theme.radius
        color: "transparent"
        border.color: Theme.border
        Flow {
            id: secondsRow
            anchors.fill: parent
            anchors.margins: 10
            spacing: 8
            AppText { text: "Keep"; height: 32; verticalAlignment: Text.AlignVCenter }
            AppInput {
                objectName: "eventPre"
                width: 72; implicitHeight: 32
                text: fields.events ? String(fields.events.pre) : ""
                inputMethodHints: Qt.ImhDigitsOnly
                onTextEdited: fields.setEvents({ pre: text === "" ? -1 : Number(text) })
            }
            AppText { text: "s before,"; height: 32; verticalAlignment: Text.AlignVCenter }
            AppInput {
                objectName: "eventPost"
                width: 72; implicitHeight: 32
                text: fields.events ? String(fields.events.post) : ""
                inputMethodHints: Qt.ImhDigitsOnly
                onTextEdited: fields.setEvents({ post: text === "" ? -1 : Number(text) })
            }
            AppText { text: "s after each event"; height: 32; verticalAlignment: Text.AlignVCenter }
            AppText {
                visible: !fields.eventsValid
                text: "Before: 0–60 s, after: 0–600 s."
                color: Theme.danger
                variant: "small"
                height: 32
                verticalAlignment: Text.AlignVCenter
            }
        }
    }

    // event marks on the timeline: every mode
    Rectangle {
        visible: fields.events !== null
        Layout.fillWidth: true
        implicitHeight: markRow.implicitHeight + 20
        radius: Theme.radius
        color: "transparent"
        border.color: Theme.border
        RowLayout {
            id: markRow
            anchors.fill: parent
            anchors.margins: 10
            spacing: 12
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                AppText { text: "Show events on the timeline" }
                AppText {
                    Layout.fillWidth: true
                    variant: "small"
                    wrapMode: Text.WordWrap
                    text: "Logs camera events (video loss; motion and inputs later) as marks in playback. Marks you add by hand are always kept."
                }
            }
            AppSwitch {
                objectName: "eventMarking"
                checked: fields.events ? fields.events.marking : true
                onToggled: fields.setEvents({ marking: checked })
            }
        }
    }
}
