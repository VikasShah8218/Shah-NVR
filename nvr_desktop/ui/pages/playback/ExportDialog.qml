import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

AppDialog {
    id: dialog
    property double startMs: 0
    property double endMs: 0
    property string mode: "original"
    property string codec: "h264"
    property string quality: "balanced"
    property string processor: "auto"
    property int maxHeight: 0
    property int maxFps: 0
    property bool includeAudio: true
    readonly property real hours: (endMs - startMs) / 3600000
    readonly property bool valid: hours > 0 && hours <= 4 && endMs <= Playback.nowMs() + 5000

    function openDefault() {
        const now = Math.min(Playback.nowMs(), Playback.day + 86400000)
        startMs = Playback.playFrom > 0 ? Playback.playFrom : Math.max(Playback.day, now - 900000)
        endMs = Playback.playFrom > 0 ? Math.min(now, startMs + 900000) : now
        startField.text = Qt.formatDateTime(new Date(startMs), "yyyy-MM-dd HH:mm:ss")
        endField.text = Qt.formatDateTime(new Date(endMs), "yyyy-MM-dd HH:mm:ss")
        open()
    }
    function parseLocal(text) {
        const value = Date.fromLocaleString(Qt.locale(), text, "yyyy-MM-dd HH:mm:ss")
        return value && !isNaN(value.getTime()) ? value.getTime() : 0
    }
    title: "Export recording"
    description: "Export up to four hours. Original preserves quality; compressed uses FFmpeg and more node resources."
    width: Math.min(600, parent ? parent.width - 40 : 600)

    GridLayout {
        columns: 2; columnSpacing: 12; rowSpacing: 10; Layout.fillWidth: true
        AppText { text: "Start"; font.weight: Font.Medium }
        AppText { text: "End"; font.weight: Font.Medium }
        AppInput { id: startField; Layout.fillWidth: true; onTextChanged: dialog.startMs = dialog.parseLocal(text) }
        AppInput { id: endField; Layout.fillWidth: true; onTextChanged: dialog.endMs = dialog.parseLocal(text) }
        AppText { text: "Export type"; font.weight: Font.Medium }
        Item { Layout.fillWidth: true }
        AppSelect { Layout.fillWidth: true; options: [{value:"original",label:"Original quality"},{value:"compressed",label:"Compressed"}]; value: dialog.mode; onPicked: v => dialog.mode = v }
        AppText { text: dialog.mode === "original" ? "No transcoding" : "Custom encoding"; variant: "small" }
        AppText { visible: dialog.mode === "compressed"; text: "Codec" }
        AppSelect { visible: dialog.mode === "compressed"; Layout.fillWidth: true; options: [{value:"h264",label:"H.264"},{value:"h265",label:"H.265"}]; value: dialog.codec; onPicked: v => dialog.codec = v }
        AppText { visible: dialog.mode === "compressed"; text: "Quality" }
        AppSelect { visible: dialog.mode === "compressed"; Layout.fillWidth: true; options: [{value:"high",label:"High"},{value:"balanced",label:"Balanced"},{value:"small",label:"Small file"}]; value: dialog.quality; onPicked: v => dialog.quality = v }
        AppText { visible: dialog.mode === "compressed"; text: "Processor" }
        AppSelect { visible: dialog.mode === "compressed"; Layout.fillWidth: true; options: [{value:"auto",label:"Auto"},{value:"cpu",label:"CPU"},{value:"gpu",label:"GPU"}]; value: dialog.processor; onPicked: v => dialog.processor = v }
        AppText { visible: dialog.mode === "compressed"; text: "Max height" }
        AppSelect { visible: dialog.mode === "compressed"; Layout.fillWidth: true; options: [0,2160,1440,1080,720,480,360].map(v => ({value:v,label:v ? v+"p" : "Original"})); value: dialog.maxHeight; onPicked: v => dialog.maxHeight = Number(v) }
        AppText { visible: dialog.mode === "compressed"; text: "Max FPS (0 = original)" }
        AppInput { visible: dialog.mode === "compressed"; Layout.fillWidth: true; text: String(dialog.maxFps); inputMethodHints: Qt.ImhDigitsOnly; onTextChanged: dialog.maxFps = Math.max(0, Math.min(120, Number(text) || 0)) }
        AppText { visible: dialog.mode === "compressed"; text: "Include audio" }
        Switch { visible: dialog.mode === "compressed"; checked: dialog.includeAudio; onToggled: dialog.includeAudio = checked }
    }
    AppText { text: dialog.valid ? dialog.hours.toFixed(2) + " hours selected" : "Select 1 second to 4 hours in the past"; color: dialog.valid ? Theme.mutedForeground : Theme.danger }
    footer: [
        Item { Layout.fillWidth: true },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: dialog.close() },
        AppButton { text: "Queue export"; enabled: dialog.valid; onClicked: { Playback.createExport(dialog.startMs, dialog.endMs, dialog.mode, dialog.codec, dialog.quality, dialog.processor, dialog.maxHeight, dialog.maxFps, dialog.includeAudio); dialog.close() } }
    ]
}
