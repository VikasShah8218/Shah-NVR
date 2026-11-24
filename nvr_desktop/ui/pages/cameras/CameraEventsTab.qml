import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Camera events from ONVIF (port of nvr_client/src/features/cameras/CameraEventsTab.tsx;
// docs/DESKTOP_ONVIF_EVENTS_PLAN.md): switch, kinds, "store other", Save, Detect, status line.
// The draft and the status live in CameraDetail.events.
ColumnLayout {
    id: root
    required property var camera
    readonly property var ev: CameraDetail.events
    spacing: 16

    // one bordered row: title + hint on the left, a switch on the right
    component SwitchRow: Rectangle {
        id: row
        property string title: ""
        property string hint: ""
        property bool checked: false
        property bool active: true
        property string name: ""
        signal toggled(bool on)
        Layout.fillWidth: true
        implicitHeight: rowLayout.implicitHeight + 18
        radius: Theme.radiusSm
        color: "transparent"
        border.color: Theme.border
        opacity: active ? 1 : 0.6
        RowLayout {
            id: rowLayout
            anchors.fill: parent
            anchors.margins: 9
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 12
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                AppText { text: row.title; Layout.fillWidth: true }
                AppText { visible: row.hint !== ""; text: row.hint; variant: "small"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
            AppSwitch {
                objectName: row.name
                checked: row.checked
                enabled: row.active
                // a click breaks the binding: hand the value to the store, then follow it again
                onToggled: { row.toggled(checked); checked = Qt.binding(() => row.checked) }
            }
        }
    }

    Card {
        visible: !root.ev.hasHost
        Layout.fillWidth: true
        AppText {
            Layout.fillWidth: true
            variant: "muted"
            wrapMode: Text.WordWrap
            text: "This camera has no ONVIF address yet. Open the Device tab once (or add the camera through ONVIF) to use camera events."
        }
    }

    Card {
        visible: root.ev.hasHost
        Layout.fillWidth: true
        title: "Camera events"
        headerRight: AppButton {
            objectName: "detectCameraEvents"
            text: root.ev.detecting ? "Detecting…" : "Detect"
            iconName: "search"
            variant: "outline"
            size: "sm"
            enabled: !root.ev.detecting
            onClicked: CameraDetail.detectEvents()
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 20

            // ------------------------------------------------ the switches
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.alignment: Qt.AlignTop
                spacing: 8

                SwitchRow {
                    name: "cameraEventsEnabled"
                    title: "Use camera events"
                    hint: "The camera tells Shah-NVR about motion, tamper and inputs. Each event keeps video in Event mode and shows as a mark on the playback timeline."
                    checked: root.ev.enabled
                    onToggled: on => CameraDetail.setEventsEnabled(on)
                }
                Repeater {
                    model: root.ev.rows ?? []
                    delegate: SwitchRow {
                        required property var modelData
                        name: "cameraEventKind_" + modelData.kind
                        title: modelData.title
                        hint: modelData.hint
                        checked: modelData.on
                        active: root.ev.enabled
                        onToggled: on => CameraDetail.setEventKind(modelData.kind, on)
                    }
                }
                SwitchRow {
                    name: "cameraEventsStoreOther"
                    title: "Also store other camera events"
                    hint: "Any other event the camera sends (analytics…), as a grey \"Camera event\" mark. PTZ and health messages are never stored."
                    checked: root.ev.storeOther
                    active: root.ev.enabled
                    onToggled: on => CameraDetail.setEventsStoreOther(on)
                }
                AppButton {
                    objectName: "saveCameraEvents"
                    text: root.ev.saving ? "Saving…" : "Save"
                    enabled: root.ev.canSave
                    onClicked: CameraDetail.saveEvents()
                }
            }

            // ------------------------------------------------ status
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.alignment: Qt.AlignTop
                spacing: 6

                AppText {
                    objectName: "cameraEventsStatus"
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: root.ev.text ?? ""
                    color: Theme.toneColor(root.ev.tone)
                }
                FieldRow { visible: (root.ev.since ?? "") !== ""; Layout.fillWidth: true; label: "Since"; value: root.ev.since ?? "" }
                FieldRow { Layout.fillWidth: true; label: "Camera offers"; value: root.ev.offeredText ?? "" }
                Repeater {
                    model: root.ev.topics ?? []
                    delegate: ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 0
                        AppText { text: modelData.title; variant: "small" }
                        AppText { Layout.fillWidth: true; text: modelData.topic; variant: "mono"; font.pixelSize: Theme.textXs; wrapMode: Text.WrapAnywhere }
                    }
                }

                // every topic the camera lists (after Detect), folded
                ColumnLayout {
                    id: allTopics
                    property bool open: false
                    visible: (root.ev.allTopics ?? []).length > 0
                    Layout.fillWidth: true
                    Layout.topMargin: 6
                    spacing: 2
                    Row {
                        spacing: 4
                        Icon { name: allTopics.open ? "chevron-down" : "chevron-right"; size: 14; color: Theme.mutedForeground; anchors.verticalCenter: parent.verticalCenter }
                        AppText { text: "All " + (root.ev.allTopics ?? []).length + " topics the camera lists"; variant: "small" }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: allTopics.open = !allTopics.open }
                    }
                    Repeater {
                        model: allTopics.open ? root.ev.allTopics : []
                        delegate: AppText {
                            required property string modelData
                            Layout.fillWidth: true
                            text: modelData
                            variant: "mono"
                            color: Theme.mutedForeground
                            font.pixelSize: Theme.textXs
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }

                AppText {
                    Layout.fillWidth: true
                    Layout.topMargin: 6
                    variant: "small"
                    wrapMode: Text.WordWrap
                    text: "Shah-NVR does not change camera settings. If a kind is missing, enable it in the camera's own web page (for example the motion detection app on AXIS), then press Detect."
                }
            }
        }
    }
}
