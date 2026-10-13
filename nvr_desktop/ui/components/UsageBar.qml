import QtQuick
import "../theme"

// Horizontal usage bar: cyan, amber from warnAt %, red from dangerAt %. percent may be null.
Rectangle {
    id: bar

    property var percent: null
    property real warnAt: 75
    property real dangerAt: 90
    readonly property real p: percent === null || percent === undefined ? 0 : Math.max(0, Math.min(100, percent))

    implicitHeight: 6
    radius: 3
    color: Theme.muted

    Rectangle {
        width: bar.width * bar.p / 100
        height: parent.height
        radius: parent.radius
        color: bar.percent === null || bar.percent === undefined ? Theme.alpha(Theme.mutedForeground, 0.4)
            : bar.p >= bar.dangerAt ? Theme.danger : bar.p >= bar.warnAt ? Theme.warning : Theme.info
        Behavior on width { NumberAnimation { duration: 400 } }
    }
}
