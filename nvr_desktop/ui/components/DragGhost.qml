import QtQuick
import "../theme"

// Label that follows the mouse while a camera or a group is dragged (onto a live tile, or onto another group).
// Drop targets use DropArea { keys: ["camera"] / ["group"] } and read drop.source.cameraId / groupId / label.
// A MouseArea starts the drag with `drag.target: ghost` and calls ghost.begin(...) on press.
Rectangle {
    id: ghost

    property string kind: "camera"  // "camera" | "group"
    property int cameraId: 0
    property int groupId: 0
    property string label: ""
    property var payload: ({})  // the dragged row (a group's path / parent, for the move dialog)
    property bool dragging: false

    // Put the ghost under the mouse at `point` (in the ghost's parent coordinates) before a drag starts.
    function begin(kind, id, label, point) {
        ghost.kind = kind
        ghost.cameraId = kind === "camera" ? id : 0
        ghost.groupId = kind === "group" ? id : 0
        ghost.label = label
        ghost.x = point.x - width / 2
        ghost.y = point.y - height / 2
    }

    visible: dragging
    width: ghostRow.implicitWidth + 24
    height: 30
    radius: Theme.radiusSm
    color: Theme.popover
    border.color: Theme.primary
    z: 100
    Drag.active: dragging
    Drag.keys: [kind]
    Drag.hotSpot.x: width / 2
    Drag.hotSpot.y: height / 2

    Row {
        id: ghostRow
        anchors.centerIn: parent
        spacing: 6
        Icon { visible: ghost.kind === "group"; name: "folder"; size: 14; color: Theme.primary; anchors.verticalCenter: parent.verticalCenter }
        AppText { text: ghost.label; anchors.verticalCenter: parent.verticalCenter }
    }
}
