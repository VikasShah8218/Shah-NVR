import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

AppDialog {
    id: dialog

    title: "Use NTP"
    description: "The camera sets its own clock from an NTP server and keeps it correct."

    function openFor(current) {
        fromDhcp.checked = current ? !!current.from_dhcp : false
        servers.text = current && current.servers ? current.servers.join(", ") : ""
        open()
    }

    RowLayout {
        Layout.fillWidth: true
        AppSwitch { id: fromDhcp }
        AppText { text: "Use the NTP server given by DHCP"; Layout.fillWidth: true }
    }
    ColumnLayout {
        visible: !fromDhcp.checked
        Layout.fillWidth: true
        spacing: 6
        AppText { text: "NTP servers"; font.weight: Font.Medium }
        AppInput { id: servers; Layout.fillWidth: true; placeholderText: "192.168.1.3, pool.ntp.org" }
        AppText { text: "IP addresses or host names, separated by commas."; variant: "small" }
    }

    footer: [
        Item { Layout.fillWidth: true },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: dialog.close() },
        AppButton {
            text: "Save"
            enabled: !CameraDetail.deviceBusy && (fromDhcp.checked || servers.text.trim() !== "")
            onClicked: {
                CameraDetail.setNtp(fromDhcp.checked, servers.text)
                dialog.close()
            }
        }
    ]
}
