import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

ColumnLayout {
    id: root
    objectName: "encoderTab"
    property var camera: ({})
    property bool active: false
    property string profile: ""
    property string mapping: ""
    readonly property var v: Encoder.view
    readonly property int cameraId: camera.id ?? 0
    readonly property bool available: !!camera.onvif_host
    spacing: 16

    function syncTarget() {
        const streams = camera.streams ?? []
        if (!streams.some(s => s.profile === profile))
            profile = streams.length ? streams[0].profile : ""
        Encoder.setTarget(active && available ? cameraId : 0, active ? profile : "")
    }
    onActiveChanged: syncTarget()
    onCameraChanged: syncTarget()
    onCameraIdChanged: { profile = ""; syncTarget() }
    onProfileChanged: syncTarget()
    Component.onCompleted: syncTarget()
    Component.onDestruction: Encoder.setTarget(0, "")
    Connections {
        target: Encoder
        function onTargetChanged() { confirmation.close(); root.mapping = "" }
        function onReviewReady() { confirmation.open() }
    }
    Timer { interval: 5000; repeat: true; running: root.active && root.available; onTriggered: Encoder.refreshStatus() }

    AppText {
        visible: !root.available
        text: "Video settings require an ONVIF-linked camera. Add or link the camera through Discovery first."
        wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true
    }
    Card {
        visible: root.available
        Layout.fillWidth: true
        title: "Video encoder · " + root.profile
        spacing: 14
        AppText {
            text: "Changes are written to the camera, not transcoded by the NVR. Applying may briefly interrupt all streams on this device and create a recording gap."
            wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true
        }
        RowLayout {
            Layout.fillWidth: true
            AppText { text: "NVR stream" }
            AppSelect {
                id: streamSelect
                objectName: "encoderStream"
                Layout.preferredWidth: 160
                options: (root.camera.streams ?? []).map(s => ({value: s.profile, label: s.profile}))
                Binding { target: streamSelect; property: "value"; value: root.profile }
                onPicked: v => root.profile = v
            }
            AppButton { text: root.v.busy ? "Working…" : "Reload / discard draft"; variant: "outline"; enabled: !root.v.busy; onClicked: { root.mapping = ""; Encoder.reload() } }
        }
        ErrorState { text: root.v.error }
        ErrorState { text: (root.v.errors ?? []).join("\n") }
        AppText {
            visible: (root.v.state.warnings ?? []).length > 0
            text: (root.v.state.warnings ?? []).join("\n")
            color: Theme.warning; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true
        }
        RowLayout {
            Layout.fillWidth: true
            AppText { text: "ONVIF profile mapping" }
            AppSelect {
                id: mappingSelect
                objectName: "encoderMapping"
                Layout.fillWidth: true
                enabled: !root.v.busy && !root.v.locked
                options: (root.v.state.profiles ?? []).map(p => ({value: p.token, label: (p.name || p.token) + " (" + p.token + ")"}))
                Binding { target: mappingSelect; property: "value"; value: root.mapping || root.v.state.profile_token || "" }
                onPicked: v => root.mapping = v
            }
            AppButton {
                text: "Save mapping"; variant: "outline"
                enabled: !root.v.busy && !root.v.locked && root.mapping !== "" && root.mapping !== root.v.state.profile_token
                onClicked: Encoder.saveMapping(root.mapping)
            }
        }
        AppText {
            text: "Mapping does not change the RTSP URL. Encoder: " + (root.v.state.encoder_token || "not mapped") + " · " + (root.v.state.api || "")
            variant: "small"; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true
        }
        RowLayout {
            visible: (root.v.options ?? []).length > 1
            AppText { text: "Advertised option" }
            AppSelect {
                id: optionSelect
                objectName: "encoderOption"
                Layout.fillWidth: true; enabled: !root.v.busy
                options: root.v.options ?? []
                Binding { target: optionSelect; property: "value"; value: root.v.option }
                onPicked: v => Encoder.selectOption(Number(v))
            }
        }
        AppText {
            visible: (root.v.options ?? []).length > 1
            text: "Options are separate compatible combinations. A proposal must fit one complete option; limits are never combined."
            variant: "small"; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true
        }
        GridLayout {
            visible: !!root.v.state.current
            columns: root.width > 850 ? 3 : 2
            columnSpacing: 20; rowSpacing: 14; Layout.fillWidth: true
            Repeater {
                // Stable delegates: history polling must not destroy focused inputs.
                model: ["encoding", "resolution", "fps", "bitrate_kbps", "gop", "quality", "rate_control", "codec_profile"]
                ColumnLayout {
                    required property string modelData
                    readonly property var field: root.v.fields.find(f => f.key === modelData)
                    id: fieldRow
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    AppText { text: fieldRow.field.label }
                    AppSelect {
                        id: fieldSelect
                        objectName: "encoder-" + fieldRow.field.key
                        visible: fieldRow.field.select
                        Layout.fillWidth: true
                        enabled: fieldRow.field.enabled && !root.v.busy
                        options: fieldRow.field.choices
                        Binding { target: fieldSelect; property: "value"; value: fieldRow.field.value }
                        onPicked: v => Encoder.edit(fieldRow.field.key, v)
                    }
                    AppInput {
                        id: fieldInput
                        objectName: "encoderInput-" + fieldRow.field.key
                        visible: !fieldRow.field.select
                        Layout.fillWidth: true
                        enabled: fieldRow.field.enabled && !root.v.busy
                        Binding { target: fieldInput; property: "text"; value: fieldRow.field.value; when: !fieldInput.activeFocus; restoreMode: Binding.RestoreNone }
                        placeholderText: "Not exposed"
                        onTextEdited: Encoder.edit(fieldRow.field.key, text)
                    }
                    AppText {
                        text: fieldRow.field.hint
                        visible: text !== ""
                        variant: "small"; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true
                    }
                }
            }
        }
        Flow {
            Layout.fillWidth: true; spacing: 8
            Repeater {
                model: ["Storage saver", "Best quality", "Low-bandwidth substream"]
                AppButton {
                    required property string modelData
                    text: modelData; variant: "outline"; enabled: !root.v.busy && !!root.v.state.current
                    onClicked: Encoder.preset(modelData)
                }
            }
        }
        AppText { text: root.v.storage; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true }
        AppText {
            text: "Video only, decimal GB at configured bitrate. VBR varies; audio/overhead are extra. Presets are editable proposals. H265 playback depends on decoder support; an H264 substream does not change H265 recordings."
            variant: "small"; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true
        }
        AppText {
            visible: root.v.shared
            text: "Shared encoder: " + (root.v.state.shared_profiles ?? []).join(", ") + " · use count " + (root.v.state.use_count ?? 0)
            color: Theme.warning; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true
        }
        AppSwitch {
            id: sharedAck
            visible: root.v.shared; enabled: !root.v.busy
            text: "I acknowledge changes affect the shared profiles"
            Binding { target: sharedAck; property: "checked"; value: root.v.ack }
            onToggled: Encoder.acknowledge(checked)
        }
        AppText {
            text: root.v.proposal || "No draft changes"
            variant: "small"; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true
        }
        AppButton { objectName: "encoderReview"; text: "Review and apply…"; enabled: root.v.canApply; onClicked: Encoder.prepare("") }
    }

    Card {
        visible: root.available
        Layout.fillWidth: true; title: "Apply this draft to other cameras"; spacing: 10
        AppText {
            text: "Select up to 20 targets. Only edited fields are copied to the same NVR stream name (" + root.profile + "). Each target is checked separately; unsupported or shared encoders are skipped. Changes run sequentially and stop after an unverified result."
            wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true
        }
        Flow {
            Layout.fillWidth: true; spacing: 16
            Repeater {
                model: Cameras.all.filter(c => c.id !== root.cameraId && c.onvif_host)
                CheckBox {
                    required property var modelData
                    id: bulkCheck
                    text: modelData.name
                    enabled: !root.v.busy && (checked || root.v.selected.length < 20)
                    Binding { target: bulkCheck; property: "checked"; value: root.v.selected.includes(bulkCheck.modelData.id) }
                    onToggled: Encoder.selectCamera(modelData.id, checked)
                }
            }
        }
        AppButton { text: "Check selected cameras…"; enabled: !root.v.busy && !root.v.locked && root.v.selected.length > 0 && root.v.proposal !== "" && root.v.errors.length === 0; onClicked: Encoder.prepareBulk() }
    }
    Card {
        visible: root.available
        Layout.fillWidth: true; title: "Results and recovery"; spacing: 10
        AppText { text: root.v.message; visible: text !== ""; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true }
        ErrorState { text: root.v.statusError }
        AppText {
            visible: !!root.v.pending || root.v.uncertain
            text: "An operation is pending or uncertain. Wait at least two minutes, then request fresh readback on the affected camera. For a bulk result, open that camera's Video tab. Do not retry the write."
            color: Theme.warning; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true
        }
        RowLayout {
            AppButton { text: "Refresh status"; variant: "outline"; onClicked: Encoder.refreshStatus() }
            AppButton { text: "Resolve / fresh readback"; variant: "outline"; enabled: !root.v.busy; onClicked: Encoder.resolve() }
        }
        AppText {
            text: "Stream: " + (root.v.recovery.status ?? "unknown") + " · fresh status: " + (root.v.recovery.fresh_status ? "yes" : "not yet") + " · new recording: " + (root.v.recovery.recording_expected ? (root.v.recovery.new_recording ? "yes" : "not yet") : "not expected")
            wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true
        }
        AppText { text: root.v.recovery.message ?? ""; variant: "small"; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true }
        Repeater {
            model: root.v.bulk ?? []
            AppText {
                required property var modelData
                text: modelData.name + ": " + modelData.status + " — " + modelData.message
                wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true
            }
        }
        AppText { text: "Recent changes"; variant: "heading" }
        Repeater {
            model: root.v.history ?? []
            RowLayout {
                required property var modelData
                id: historyRow
                Layout.fillWidth: true
                AppText {
                    text: historyRow.modelData.created_at + " · " + historyRow.modelData.status + "\n" + (historyRow.modelData.result?.message ?? "")
                    wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true
                }
                AppButton {
                    text: "Restore before…"; variant: "outline"
                    enabled: !root.v.busy && !root.v.locked && !!historyRow.modelData.before?.current && !!root.v.state.revision
                    onClicked: Encoder.prepare(historyRow.modelData.id)
                }
            }
        }
    }
    ConfirmDialog {
        id: confirmation
        objectName: "encoderConfirmation"
        title: "Apply camera video settings?"
        description: "Preflight passed for " + root.v.reviewCount + " target(s). " + root.v.message + ". All streams on each affected device may briefly stop, leaving a recording gap. Continue?"
        confirmLabel: "Apply to camera"
        AppText { text: root.v.reviewTargets; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true }
        AppText { text: root.v.reviewValues; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true }
        onConfirmed: Encoder.confirm()
    }
}
