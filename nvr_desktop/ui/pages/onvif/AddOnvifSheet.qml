import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// One login for selected devices. Probe once, review streams/retention, then add through central.
Sheet {
    id: sheet
    objectName: "addOnvifSheet"

    title: Discover.addRows.length === 1 ? "Add camera" : "Add " + Discover.addRows.length + " cameras"
    description: "Main is recorded; the optional sub stream is live-only unless you choose to record it."
    width: Math.min(parent ? parent.width * 0.95 : 760, 760)
    closePolicy: Discover.busy ? Popup.NoAutoClose : Popup.CloseOnEscape | Popup.CloseOnPressOutside
    onClosed: { password.text = ""; Discover.closeAdd() }

    Card {
        Layout.fillWidth: true
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 5
                AppText { text: "Username"; font.weight: Font.Medium }
                AppInput { id: username; Layout.fillWidth: true; text: "admin"; enabled: !Discover.busy }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 5
                AppText { text: "Password"; font.weight: Font.Medium }
                AppInput { id: password; Layout.fillWidth: true; echoMode: TextInput.Password; enabled: !Discover.busy }
            }
            AppButton {
                Layout.alignment: Qt.AlignBottom
                text: Discover.busy && Discover.uncheckedCount > 0 ? "Checking…" : "Check"
                iconName: Discover.busy ? "loader-circle" : "check"
                enabled: !Discover.busy && Discover.uncheckedCount > 0
                onClicked: Discover.checkAll(username.text, password.text)
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 7
            Icon { name: "triangle-alert"; size: 15; color: Theme.warning; Layout.alignment: Qt.AlignTop }
            AppText {
                text: "Each check makes one login attempt. A wrong password is never retried automatically because cameras may lock the account."
                variant: "small"
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                Layout.fillWidth: true
            }
        }
    }

    Repeater {
        model: Discover.addRows
        delegate: Rectangle {
            id: row
            required property var modelData
            Layout.fillWidth: true
            implicitHeight: content.implicitHeight + 24
            radius: Theme.radius
            color: modelData.status === "added" ? Theme.alpha(Theme.success, 0.06) : Theme.alpha(Theme.muted, 0.35)
            border.color: modelData.status === "added" ? Theme.alpha(Theme.success, 0.45) : Theme.border

            ColumnLayout {
                id: content
                anchors.fill: parent
                anchors.margins: 12
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Rectangle {
                        visible: Object.keys(row.modelData.probe ?? {}).length > 0
                        Layout.preferredWidth: 150
                        Layout.preferredHeight: 84
                        radius: Theme.radiusSm
                        color: Theme.video
                        clip: true
                        Image {
                            anchors.fill: parent
                            source: row.modelData.snapshotUrl ?? ""
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                        }
                        Icon {
                            visible: !row.modelData.snapshotUrl
                            anchors.centerIn: parent
                            name: "image-down"
                            color: Theme.mutedForeground
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        RowLayout {
                            Layout.fillWidth: true
                            AppText {
                                text: row.modelData.device.host + (row.modelData.device.port !== 80 ? ":" + row.modelData.device.port : "")
                                variant: "mono"
                                Layout.fillWidth: true
                            }
                            AppText {
                                text: ({ idle: "Not checked", checking: "Checking", ready: "Ready", error: "Failed", adding: "Adding", added: "Added" })[row.modelData.status]
                                color: row.modelData.status === "added" ? Theme.success
                                    : row.modelData.status === "error" ? Theme.danger
                                    : row.modelData.status === "ready" ? Theme.info : Theme.mutedForeground
                                font.weight: Font.Medium
                            }
                        }
                        AppText {
                            readonly property var info: row.modelData.probe.info ?? ({})
                            text: Object.keys(row.modelData.probe ?? {}).length > 0
                                ? [info.manufacturer, info.model, info.firmwareversion ? "fw " + info.firmwareversion : ""].filter(Boolean).join(" · ")
                                : row.modelData.device.name || row.modelData.device.hardware || "ONVIF device"
                            variant: "small"
                            Layout.fillWidth: true
                        }
                        AppText {
                            visible: row.modelData.error !== ""
                            text: row.modelData.error
                            color: Theme.danger
                            font.pixelSize: Theme.textXs
                            wrapMode: Text.WordWrap
                            elide: Text.ElideNone
                            Layout.fillWidth: true
                        }
                        AppText {
                            visible: row.modelData.status === "ready" && Math.abs(row.modelData.probe.clock?.offset_seconds ?? 0) > 10
                            text: "Camera clock is " + (row.modelData.offsetText ?? "") + " off. Fix it later on the Device tab."
                            color: Theme.warning
                            font.pixelSize: Theme.textXs
                            Layout.fillWidth: true
                        }
                        LinkText {
                            visible: row.modelData.status === "added"
                            text: "Open camera →"
                            active: true
                            onActivated: {
                                sheet.close()
                                Router.go("camera", row.modelData.cameraId)
                            }
                        }
                    }
                }

                ColumnLayout {
                    visible: row.modelData.status === "ready"
                    Layout.fillWidth: true
                    spacing: 9
                    AppText { text: "Camera name"; font.weight: Font.Medium }
                    AppInput {
                        objectName: "onvifName-" + row.modelData.endpoint
                        Layout.fillWidth: true
                        text: row.modelData.name
                        onEditingFinished: Discover.updateRow(row.modelData.endpoint, "name", text)
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 5
                            AppText { text: "Main stream (recorded)"; font.weight: Font.Medium }
                            AppSelect {
                                Layout.fillWidth: true
                                options: row.modelData.mainOptions
                                value: row.modelData.main
                                onPicked: value => Discover.updateRow(row.modelData.endpoint, "main", value)
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 5
                            AppText { text: "Sub stream"; font.weight: Font.Medium }
                            AppSelect {
                                Layout.fillWidth: true
                                options: row.modelData.subOptions
                                value: row.modelData.sub
                                onPicked: value => Discover.updateRow(row.modelData.endpoint, "sub", value)
                            }
                        }
                    }
                    RowLayout {
                        visible: row.modelData.sub !== ""
                        Layout.fillWidth: true
                        AppSwitch {
                            checked: row.modelData.recordSub
                            onToggled: Discover.updateRow(row.modelData.endpoint, "recordSub", checked)
                        }
                        AppText { text: "Record the sub stream too (otherwise live only)"; variant: "small" }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        AppSwitch {
                            checked: row.modelData.enabled
                            onToggled: Discover.updateRow(row.modelData.endpoint, "enabled", checked)
                        }
                        AppText { text: "Camera enabled"; variant: "small" }
                        Item { Layout.fillWidth: true }
                        AppText { text: "Keep recordings"; variant: "small" }
                        AppInput {
                            Layout.preferredWidth: 68
                            text: row.modelData.retentionDays
                            enabled: !row.modelData.keepUntilFull
                            validator: IntValidator { bottom: 1; top: 3650 }
                            onEditingFinished: Discover.updateRow(row.modelData.endpoint, "retentionDays", text)
                        }
                        AppText { text: "days"; variant: "small" }
                        AppSwitch {
                            checked: row.modelData.keepUntilFull
                            onToggled: Discover.updateRow(row.modelData.endpoint, "keepUntilFull", checked)
                        }
                        AppText { text: "Until full"; variant: "small" }
                    }
                }
            }
        }
    }

    footer: [
        AppButton {
            text: Discover.addedCount === Discover.addRows.length && Discover.addRows.length > 0 ? "Done" : "Add ready cameras"
            enabled: !Discover.busy && (Discover.readyCount > 0 || Discover.addedCount === Discover.addRows.length)
            onClicked: {
                if (Discover.addedCount === Discover.addRows.length) sheet.close()
                else Discover.addReady(username.text, password.text)
            }
        },
        AppButton { text: Discover.addedCount > 0 ? "Close" : "Cancel"; variant: "outline"; enabled: !Discover.busy; onClicked: sheet.close() },
        Item { Layout.fillWidth: true }
    ]
}
