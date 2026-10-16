import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Live ONVIF device information and explicit H1 write actions.
ColumnLayout {
    id: root

    property var camera: ({})
    property bool active: false
    readonly property var d: CameraDetail.device
    readonly property var info: Object.keys(d ?? {}).length > 0 ? (d.info ?? ({})) : ({})
    readonly property var clock: d.clock ?? ({})
    readonly property var network: d.network ?? ({})
    readonly property real offset: clock.offset_seconds ?? camera.clock_offset_seconds ?? NaN

    spacing: 14
    onActiveChanged: if (active) CameraDetail.loadDevice()

    ErrorState {
        text: CameraDetail.deviceError + (CameraDetail.deviceError && !root.camera.onvif_host
            ? " This camera was added manually; ONVIF is tried on its stream address, port 80." : "")
    }
    LoadingState { visible: CameraDetail.deviceBusy && Object.keys(root.d ?? {}).length === 0 }

    GridLayout {
        Layout.fillWidth: true
        columns: root.width > 1050 ? 3 : 1
        columnSpacing: 14
        rowSpacing: 14

        Card {
            title: "Device"
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            headerRight: AppButton {
                text: "Refresh"
                iconName: CameraDetail.deviceBusy ? "loader-circle" : "refresh-cw"
                variant: "ghost"
                size: "sm"
                enabled: !CameraDetail.deviceBusy
                onClicked: CameraDetail.loadDevice()
            }
            FieldRow { label: "Manufacturer"; value: root.info.manufacturer ?? root.camera.manufacturer ?? "—" }
            FieldRow { label: "Model"; value: root.info.model ?? root.camera.model ?? "—" }
            FieldRow { label: "Firmware"; value: root.info.firmwareversion ?? root.camera.firmware ?? "—" }
            FieldRow { label: "Serial"; value: root.info.serialnumber ?? root.camera.serial ?? "—" }
            FieldRow { label: "MAC"; value: root.network.mac ?? root.camera.mac ?? "—" }
            FieldRow { label: "Hostname"; value: root.d.hostname ?? "—" }
            FieldRow {
                label: "IP"
                value: root.network.ip ? root.network.ip + (root.network.prefix_length ? "/" + root.network.prefix_length : "")
                    + " · " + (root.network.dhcp ? "DHCP" : "static") : "—"
            }
            FieldRow {
                label: "ONVIF address"
                value: root.d.host ? root.d.host + ":" + root.d.port
                    : root.camera.onvif_host ? root.camera.onvif_host + ":" + (root.camera.onvif_port ?? 80) : "—"
            }
            Flow {
                Layout.fillWidth: true
                spacing: 6
                Repeater {
                    model: root.d.serviceNames ?? []
                    delegate: Rectangle {
                        required property string modelData
                        implicitWidth: serviceText.implicitWidth + 14
                        implicitHeight: 22
                        radius: 5
                        color: Theme.muted
                        AppText { id: serviceText; anchors.centerIn: parent; text: modelData; variant: "small" }
                    }
                }
            }
        }

        Card {
            title: "Clock"
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            FieldRow {
                label: "Offset from node"
                value: isNaN(root.offset) ? "Unknown" : (root.d.offsetText ?? (Math.round(root.offset) + " s"))
                valueColor: !isNaN(root.offset) && Math.abs(root.offset) > 10 ? Theme.warning : Theme.success
            }
            FieldRow { label: "Time source"; value: root.clock.source ?? "—" }
            FieldRow { label: "Time zone"; value: root.clock.timezone ?? "—" }
            FieldRow {
                label: "NTP"
                value: root.d.ntp ? (root.d.ntp.from_dhcp ? "From DHCP" : (root.d.ntp.servers ?? []).join(", ") || "None") : "—"
            }
            FieldRow {
                label: "Reachable"
                value: root.camera.onvif_reachable === null || root.camera.onvif_reachable === undefined
                    ? "—" : root.camera.onvif_reachable ? "Yes" : "No"
                valueColor: root.camera.onvif_reachable === false ? Theme.danger : Theme.foreground
            }
            AppText {
                visible: !isNaN(root.offset) && Math.abs(root.offset) > 10
                text: "The camera clock is off. Its on-screen time and events will not match the recordings."
                color: Theme.warning
                font.pixelSize: Theme.textXs
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 6
                AppButton {
                    text: "Sync time to node"
                    iconName: "clock"
                    size: "sm"
                    enabled: !CameraDetail.deviceBusy
                    onClicked: CameraDetail.syncTime()
                }
                AppButton {
                    text: "Use NTP…"
                    variant: "outline"
                    size: "sm"
                    enabled: !CameraDetail.deviceBusy
                    onClicked: ntpDialog.openFor(root.d.ntp ?? null)
                }
            }
            AppText {
                text: "Sync sets the clock once. NTP keeps it correct while the camera can reach the server."
                variant: "small"
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                Layout.fillWidth: true
            }
        }

        Card {
            title: "Maintenance"
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            AppText {
                text: "Restart the camera. Recording stops for about a minute and resumes automatically."
                variant: "muted"
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                Layout.fillWidth: true
            }
            AppButton {
                Layout.fillWidth: true
                text: "Reboot camera"
                iconName: "rotate-ccw"
                variant: "outline"
                enabled: !CameraDetail.deviceBusy
                onClicked: rebootConfirm.open()
            }
        }
    }

    NtpDialog { id: ntpDialog }
    ConfirmDialog {
        id: rebootConfirm
        title: "Reboot " + (root.camera.name ?? "camera") + "?"
        description: "Live view and recording stop until the camera is back, usually about a minute."
        confirmLabel: "Reboot"
        destructive: true
        onConfirmed: CameraDetail.reboot()
    }
}
