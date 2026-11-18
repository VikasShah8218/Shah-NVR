import QtQuick
import "../theme"

// Small read-only week strip (Mon on top, 00–24): `rows` = per day the runs {start, end, event} in minutes
// (green = record, amber = event recording).
Item {
    id: strip

    property var rows: [[], [], [], [], [], [], []]
    property int barHeight: 5

    implicitWidth: 160
    implicitHeight: column.implicitHeight

    Column {
        id: column
        width: strip.width
        spacing: 1
        Repeater {
            model: 7
            delegate: Rectangle {
                id: day
                required property int index
                width: column.width
                height: strip.barHeight
                radius: 1
                color: Theme.muted
                clip: true
                Repeater {
                    model: strip.rows[day.index] || []
                    delegate: Rectangle {
                        required property var modelData
                        x: day.width * modelData.start / 1440
                        width: Math.max(1, day.width * (modelData.end - modelData.start) / 1440)
                        height: day.height
                        color: modelData.event ? Theme.alpha(Theme.warning, 0.75) : Theme.alpha(Theme.success, 0.7)
                    }
                }
            }
        }
    }
}
