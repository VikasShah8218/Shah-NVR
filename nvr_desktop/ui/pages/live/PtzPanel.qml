import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

Card {
    id: root
    required property int cameraId
    required property string profile
    property real speed: 0.10
    property string preset: ""

    Component.onCompleted: Ptz.open(cameraId, profile)
    Component.onDestruction: Ptz.close()
    onCameraIdChanged: Ptz.open(cameraId, profile)
    onProfileChanged: Ptz.open(cameraId, profile)

    RowLayout {
        Layout.fillWidth: true
        AppText { text: "PTZ · " + root.profile; font.weight: Font.DemiBold; Layout.fillWidth: true }
        AppButton { text: "Reload"; size: "sm"; variant: "outline"; enabled: !Ptz.busy; onClicked: Ptz.reload() }
    }
    AppText { text: "Hold a movement button; release to stop."; variant: "small" }
    ErrorState { text: Ptz.error }
    Repeater {
        model: Ptz.state.warnings ?? []
        AppText { required property var modelData; text: modelData; color: Theme.warning; wrapMode: Text.WordWrap; Layout.fillWidth: true }
    }
    Flow {
        Layout.fillWidth: true
        spacing: 6
        MoveButton { label: "Left"; pan: -root.speed; supported: Ptz.state.capabilities?.pan_tilt ?? false }
        MoveButton { label: "Right"; pan: root.speed; supported: Ptz.state.capabilities?.pan_tilt ?? false }
        MoveButton { label: "Up"; tilt: root.speed; supported: Ptz.state.capabilities?.pan_tilt ?? false }
        MoveButton { label: "Down"; tilt: -root.speed; supported: Ptz.state.capabilities?.pan_tilt ?? false }
        MoveButton { label: "Zoom +"; zoom: root.speed; supported: Ptz.state.capabilities?.zoom ?? false }
        MoveButton { label: "Zoom −"; zoom: -root.speed; supported: Ptz.state.capabilities?.zoom ?? false }
        AppButton { text: "Stop"; size: "sm"; variant: "destructive"; enabled: !!Ptz.state.session_id; onClicked: Ptz.stop() }
    }
    RowLayout {
        AppText { text: "Speed"; variant: "small" }
        Slider { from: 0.05; to: 0.50; stepSize: 0.05; value: root.speed; onMoved: { Ptz.stop(); root.speed = value } }
        AppText { text: root.speed.toFixed(2); variant: "small" }
    }
    RowLayout {
        visible: Ptz.state.capabilities?.presets ?? false
        Layout.fillWidth: true
        AppSelect { Layout.fillWidth: true; options: (Ptz.state.presets ?? []).map(p => ({value:p.token,label:p.name})); value: root.preset; placeholder: "Select preset"; onPicked: v => root.preset = v }
        AppButton { text: "Go"; size: "sm"; enabled: root.preset !== "" && !Ptz.blocked; onClicked: Ptz.operate("preset_goto", root.preset, false) }
        AppButton { text: "Delete"; size: "sm"; variant: "outline"; enabled: root.preset !== "" && !Ptz.blocked; onClicked: removeConfirm.open() }
    }
    RowLayout {
        visible: Ptz.state.capabilities?.home ?? false
        AppButton { text: "Go home"; size: "sm"; onClicked: Ptz.operate("home_goto", "", false) }
        AppButton { visible: Ptz.state.capabilities?.home_set ?? false; text: "Set home"; size: "sm"; variant: "outline"; onClicked: homeConfirm.open() }
    }
    RowLayout {
        visible: Ptz.state.capabilities?.presets ?? false
        Layout.fillWidth: true
        AppInput { id: presetName; Layout.fillWidth: true; placeholderText: "New preset name" }
        AppButton {
            text: "Save current position"; size: "sm"; variant: "outline"
            enabled: presetName.text.trim() !== "" && !Ptz.busy && !Ptz.blocked
            onClicked: { Ptz.operate("preset_save", presetName.text, false); presetName.text = "" }
        }
    }
    AppText { visible: Ptz.message !== ""; text: Ptz.message; variant: "small" }

    ConfirmDialog { id: removeConfirm; title: "Delete camera preset?"; description: "This removes the preset from the camera."; confirmLabel: "Delete"; destructive: true; onConfirmed: Ptz.operate("preset_remove", root.preset, true) }
    ConfirmDialog { id: homeConfirm; title: "Replace home position?"; description: "Use the camera's current position as home?"; confirmLabel: "Set home"; onConfirmed: Ptz.operate("home_set", "", true) }

    component MoveButton: AppButton {
        required property string label
        property real pan: 0
        property real tilt: 0
        property real zoom: 0
        property bool supported: false
        text: label; size: "sm"; variant: "outline"
        enabled: supported && !Ptz.busy && !Ptz.blocked && !!Ptz.state.session_id
        TapHandler { onPressedChanged: if (pressed) Ptz.start(parent.pan, parent.tilt, parent.zoom); else Ptz.stop() }
    }
}
