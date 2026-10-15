import QtQuick
import QtQuick.Layouts
import "../../theme"
import "../../components"

// "Cap for recordings (GB)" + "Use whole disk" switch, shared by the add-storage and edit-cap dialogs.
ColumnLayout {
    id: cap

    property alias unlimited: unlimitedSwitch.checked
    property alias gbText: gbField.text
    /** GB for the API, or null for "use the whole disk". */
    readonly property var value: unlimited ? null : Number(gbText)
    readonly property bool valid: unlimited || Number(gbText) > 0

    function reset(quotaBytes) {
        unlimited = quotaBytes === null || quotaBytes === undefined
        gbText = unlimited ? "500" : String(Math.round(quotaBytes / 1024 ** 3 * 100) / 100)
    }

    spacing: 6
    Layout.fillWidth: true
    RowLayout {
        Layout.fillWidth: true
        AppText { text: "Cap for recordings (GB)"; font.weight: Font.Medium; Layout.fillWidth: true }
        AppSwitch { id: unlimitedSwitch }
        AppText { text: "Use whole disk"; variant: "small" }
    }
    AppInput { id: gbField; Layout.fillWidth: true; enabled: !unlimitedSwitch.checked; inputMethodHints: Qt.ImhFormattedNumbersOnly }
    AppText { text: "Recording moves to the next storage at 95% of the cap."; variant: "small" }
}
