import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

ColumnLayout {
    id: root
    required property var camera
    property string mode: Backfill.config.mode ?? "off"
    property string profile: Backfill.config.profile ?? "main"
    property string token: Backfill.config.recording_token ?? ""
    spacing: 16

    Component.onCompleted: Backfill.setCamera(camera.id)
    Component.onDestruction: Backfill.setCamera(0)

    Card {
        Layout.fillWidth: true
        title: "Camera SD storage"
        headerRight: AppButton { text: "Test camera storage"; iconName: "refresh-cw"; variant: "outline"; size: "sm"; onClicked: Backfill.probe() }
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                FieldRow { label: "Profile G capability"; value: Backfill.config.capability ?? "unknown" }
                FieldRow { label: "Camera recording"; value: Backfill.config.recording_token ?? "Not selected" }
                FieldRow { label: "Stored from"; value: Backfill.config.earliest ? Fmt.dateTime(Backfill.config.earliest) : "—" }
                FieldRow { label: "Stored until"; value: Backfill.config.latest ? Fmt.dateTime(Backfill.config.latest) : "—" }
                FieldRow { label: "Last tested"; value: Backfill.config.checked_at ? Fmt.dateTime(Backfill.config.checked_at) : "Never" }
                AppText { visible: !!Backfill.config.error; text: Backfill.config.error ?? ""; color: Theme.danger }
            }
            ColumnLayout {
                Layout.fillWidth: true
                AppText { text: "Recovery mode"; font.weight: Font.Medium }
                AppSelect { Layout.fillWidth: true; options: [{value:"off",label:"Off"},{value:"manual",label:"Manual"},{value:"automatic",label:"Automatic"}]; value: root.mode; onPicked: v => root.mode = v }
                AppText { visible: Backfill.recordings.length > 1; text: "Camera recording"; font.weight: Font.Medium }
                AppSelect { visible: Backfill.recordings.length > 1; Layout.fillWidth: true; options: Backfill.recordings.filter(r => r.replay_available).map(r => ({value:r.token,label:r.source_id ?? r.token})); value: root.token; onPicked: v => root.token = v }
                AppText { text: "Shah-NVR recording profile"; font.weight: Font.Medium }
                AppSelect { Layout.fillWidth: true; options: (root.camera.streams ?? []).filter(s => s.record).map(s => s.profile); value: root.profile; onPicked: v => root.profile = v }
                AppButton { text: "Save"; enabled: Backfill.config.capability === "supported" || root.mode === "off"; onClicked: Backfill.save(root.mode, root.profile, root.token) }
                AppText { text: "Automatic mode checks the latest 24 hours. Each import is bounded and copied without video transcoding."; variant: "small"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
        }
    }
    Card {
        Layout.fillWidth: true
        title: "Request manual backfill"
        RowLayout {
            Layout.fillWidth: true
            AppInput { id: startField; Layout.fillWidth: true; placeholderText: "Start: YYYY-MM-DD HH:MM" }
            AppInput { id: endField; Layout.fillWidth: true; placeholderText: "End: YYYY-MM-DD HH:MM" }
            AppButton { text: "Queue missing interval"; enabled: Backfill.config.mode !== "off"; onClicked: Backfill.queue(startField.text, endField.text, root.profile) }
        }
        AppText { text: "Times use this computer's local timezone. Maximum 15 minutes; interval must be at least five minutes old."; variant: "small" }
    }
    Card {
        Layout.fillWidth: true
        title: "Backfill jobs"
        AppText { visible: Backfill.jobs.length === 0; text: "No jobs yet."; variant: "muted" }
        Repeater {
            model: Backfill.jobs
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                AppText { text: Fmt.dateTime(modelData.start_time) + " → " + Fmt.dateTime(modelData.end_time); Layout.fillWidth: true }
                StatusBadge { status: modelData.state }
                AppText { text: Math.round(modelData.progress_percent) + "%"; Layout.preferredWidth: 50 }
                AppText { text: modelData.imported_seconds ? modelData.imported_seconds.toFixed(1) + " s" : "—"; Layout.preferredWidth: 80 }
                AppText { text: modelData.imported_bytes ? Fmt.bytes(modelData.imported_bytes) : "—"; Layout.preferredWidth: 90 }
                AppText { text: modelData.error_message ?? ("Attempt " + modelData.attempt_count); variant: "small"; Layout.preferredWidth: 220 }
            }
        }
    }
}
