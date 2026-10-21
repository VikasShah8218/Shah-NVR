import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// ONVIF H1: scan the media nodes' LANs, select new devices and open the lockout-safe add flow.
PageScroll {
    id: root
    objectName: "discoverPage"
    Component.onDestruction: Discover.closeAdd()

    property int nodeId: 0 // 0 = all online nodes
    readonly property var onlineNodes: (Nodes.all ?? []).filter(n =>
        ["READY", "ACTIVE", "DRAINING", "CORDONED"].includes(n.state))
    readonly property var nodeOptions: [{ value: 0, label: "All online nodes" }].concat(
        onlineNodes.map(n => ({ value: n.id, label: n.name })))

    PageHeader {
        title: "Discover cameras"
        description: "Find ONVIF cameras on the media nodes' networks and add them with their streams filled in."
        AppSelect {
            width: 200
            options: root.nodeOptions
            value: root.nodeId
            onPicked: value => root.nodeId = Number(value)
        }
        AppButton {
            text: Discover.scanning ? "Scanning…" : "Scan network"
            iconName: Discover.scanning ? "loader-circle" : "search"
            enabled: !Discover.scanning && root.onlineNodes.length > 0
            onClicked: Discover.scan(root.nodeId)
        }
    }

    ErrorState {
        visible: root.onlineNodes.length === 0
        text: "No media node is online. ONVIF discovery runs from a media node on the camera network."
    }
    ErrorState { text: Discover.scanError }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        AppInput {
            id: address
            Layout.preferredWidth: 340
            placeholderText: "Not listed? Camera IP, e.g. 192.168.1.64:80"
            onAccepted: addAddress()
            function addAddress() {
                if (Discover.addAddress(text, root.nodeId)) text = ""
            }
        }
        AppButton {
            text: "Add address"
            iconName: "plus"
            variant: "outline"
            enabled: address.text.trim() !== "" && root.onlineNodes.length > 0
            onClicked: address.addAddress()
        }
        AppText {
            text: "Discovery only reaches cameras on the node's own subnet."
            variant: "muted"
            Layout.fillWidth: true
        }
    }

    LoadingState { visible: Discover.scanning }
    EmptyState {
        visible: !Discover.scanning && Discover.rows.length === 0
        iconName: "search"
        title: Discover.scanned ? "No ONVIF cameras answered" : "Scan to find cameras"
        text: Discover.scanned
            ? "Check that ONVIF is enabled and the cameras are on the same network as the media node."
            : "The media node sends a WS-Discovery probe on its LAN; cameras answer within a few seconds."
    }

    TableCard {
        visible: Discover.rows.length > 0
        columns: [
            { title: "", width: 54 }, { title: "Address", width: 170 }, { title: "Device", width: 0 },
            { title: "Profiles", width: 120 }, { title: "Found by", width: 160 }, { title: "In Shah-NVR", width: 170 }
        ]
        rows: Discover.rows
        rowDelegate: TableRow {
            id: deviceRow
            required property var modelData
            opacity: modelData.camera_id ? 0.65 : 1
            AppSwitch {
                Layout.preferredWidth: 54
                enabled: !deviceRow.modelData.camera_id
                checked: {
                    Discover.selectedCount
                    return Discover.isSelected(deviceRow.modelData.endpoint)
                }
                onToggled: Discover.select(deviceRow.modelData.endpoint, checked)
            }
            AppText {
                text: modelData.host + (modelData.port !== 80 ? ":" + modelData.port : "")
                variant: "mono"
                Layout.preferredWidth: 170
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                AppText {
                    text: modelData.name || modelData.hardware || (String(modelData.endpoint).startsWith("manual:") ? "Added by address" : "ONVIF device")
                    font.weight: Font.Medium
                    Layout.fillWidth: true
                }
                AppText {
                    visible: !!modelData.name && !!modelData.hardware && modelData.hardware !== modelData.name
                    text: modelData.hardware ?? ""
                    variant: "small"
                    Layout.fillWidth: true
                }
            }
            AppText { text: (modelData.profileLabels ?? []).join(", ") || "—"; Layout.preferredWidth: 120 }
            AppText { text: modelData.node_name; variant: "small"; Layout.preferredWidth: 160 }
            LinkText {
                text: modelData.camera_id ? modelData.camera_name : "New"
                active: !!modelData.camera_id
                Layout.preferredWidth: 170
                onActivated: Router.go("camera", modelData.camera_id)
            }
        }
    }

    RowLayout {
        visible: Discover.rows.length > 0
        Layout.fillWidth: true
        AppButton {
            text: "Select all new"
            variant: "ghost"
            onClicked: Discover.selectAll(true)
        }
        AppButton {
            text: "Clear selection"
            variant: "ghost"
            enabled: Discover.selectedCount > 0
            onClicked: Discover.selectAll(false)
        }
        Item { Layout.fillWidth: true }
        AppText { text: Discover.selectedCount + " selected"; variant: "muted" }
        AppButton {
            text: Discover.selectedCount === 1 ? "Add camera…" : "Add " + Discover.selectedCount + " cameras…"
            iconName: "plus"
            enabled: Discover.selectedCount > 0
            onClicked: {
                Discover.beginAdd()
                addSheet.open()
            }
        }
    }

    AddOnvifSheet { id: addSheet }
}
