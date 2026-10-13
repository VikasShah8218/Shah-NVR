import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Move a camera to another media node (port of MoveCameraDialog.tsx).
AppDialog {
    id: dialog

    property int cameraId: 0
    property string cameraName: ""
    property var currentNodeId: null
    property var target: null
    signal moveRequested(int cameraId, int nodeId)

    readonly property var movable: ["READY", "ACTIVE", "CORDONED"]
    readonly property var options: Nodes.all
        .filter(n => n.id !== currentNodeId)
        .map(n => ({ value: n.id, label: n.name + " · " + n.state + " · " + n.assigned_cameras + "/" + n.capacity_cameras + " cameras", state: n.state }))

    function openFor(id, name, nodeId) {
        cameraId = id
        cameraName = name
        currentNodeId = nodeId
        target = null
        open()
    }

    title: "Move " + cameraName
    description: "The new node starts pulling and recording the camera; the old node stops within a few seconds. Existing recordings stay where they are and remain playable."

    AppSelect {
        Layout.fillWidth: true
        options: dialog.options.filter(o => dialog.movable.includes(o.state))
        value: dialog.target
        placeholder: "Choose a media node"
        onPicked: v => dialog.target = v
    }
    AppText {
        visible: dialog.options.length === 0
        text: "There is no other media node to move to."
        variant: "muted"
    }

    footer: [
        Item { Layout.fillWidth: true },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: dialog.close() },
        AppButton {
            text: "Move camera"
            enabled: dialog.target !== null
            onClicked: {
                dialog.moveRequested(dialog.cameraId, dialog.target)
                dialog.close()
            }
        }
    ]
}
