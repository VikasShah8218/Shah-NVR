import QtQuick
import QtQuick.Layouts
import "../theme"

// The 7×24 week editor (port of nvr_client features/schedules/WeekGrid.tsx): drag a rectangle across days and hours
// to paint Record / Off in 15-minute steps. It only draws `rows` (per day, the recording runs {start, end} in
// minutes) and reports the drag (`painted`); the store does the painting. Read-only when `editable` is false.
ColumnLayout {
    id: grid

    property var rows: [[], [], [], [], [], [], []]
    property bool editable: false
    property string brush: "on"  // "on" = Record, "off" = Off
    property int nowDay: -1
    property int nowMinute: -1
    signal painted(int d0, int d1, int q0, int q1)

    readonly property var days: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    readonly property int rowHeight: 28
    property var drag: null  // {a: {d, q}, b: {d, q}} while dragging
    property var hover: null

    function hhmm(m) { return String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0") }
    function rect() {
        if (!drag)
            return null
        return { d0: Math.min(drag.a.d, drag.b.d), d1: Math.max(drag.a.d, drag.b.d),
                 q0: Math.min(drag.a.q, drag.b.q), q1: Math.max(drag.a.q, drag.b.q) }
    }
    readonly property var sel: rect()
    readonly property string tip: sel
        ? (sel.d0 === sel.d1 ? days[sel.d0] : days[sel.d0] + "–" + days[sel.d1]) + " " + hhmm(sel.q0 * 15) + "–"
          + hhmm((sel.q1 + 1) * 15) + " → " + (brush === "on" ? "Record" : "Off")
        : hover ? days[hover.d] + " " + hhmm(hover.q * 15) + "–" + hhmm((hover.q + 1) * 15) : ""

    spacing: 4

    // hour axis
    Item {
        Layout.fillWidth: true
        Layout.leftMargin: 44
        implicitHeight: 14
        Repeater {
            model: [0, 3, 6, 9, 12, 15, 18, 21, 24]
            delegate: Text {
                required property var modelData
                x: area.width * modelData / 24 - width / 2
                text: String(modelData).padStart(2, "0")
                color: Theme.mutedForeground
                font.family: Theme.font
                font.pixelSize: 10
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 4
        Column {
            Layout.preferredWidth: 40
            Layout.alignment: Qt.AlignTop
            Repeater {
                model: grid.days
                delegate: Text {
                    required property var modelData
                    height: grid.rowHeight
                    verticalAlignment: Text.AlignVCenter
                    text: modelData
                    color: Theme.mutedForeground
                    font.family: Theme.font
                    font.pixelSize: Theme.textXs
                }
            }
        }

        Rectangle {
            id: area
            objectName: "weekGridArea"
            Layout.fillWidth: true
            implicitHeight: grid.rowHeight * 7
            radius: Theme.radiusSm
            color: Theme.alpha(Theme.muted, 0.6)
            border.color: Theme.border
            clip: true

            // recording runs, one rectangle per run
            Repeater {
                model: 7
                delegate: Item {
                    id: dayRow
                    required property int index
                    y: index * grid.rowHeight
                    width: area.width
                    height: grid.rowHeight
                    Repeater {
                        model: grid.rows[dayRow.index] || []
                        delegate: Rectangle {
                            required property var modelData
                            x: area.width * modelData.start / 1440
                            width: Math.max(1, area.width * (modelData.end - modelData.start) / 1440)
                            height: dayRow.height
                            color: Theme.alpha(Theme.success, 0.6)
                        }
                    }
                    Rectangle {  // the "now" line (site time)
                        visible: grid.nowDay === dayRow.index && grid.nowMinute >= 0
                        x: area.width * grid.nowMinute / 1440 - 1
                        width: 2
                        height: dayRow.height
                        radius: 1
                        color: Theme.danger
                        z: 2
                    }
                }
            }
            // the drag preview
            Rectangle {
                visible: grid.sel !== null
                x: grid.sel ? area.width * grid.sel.q0 / 96 : 0
                y: grid.sel ? grid.sel.d0 * grid.rowHeight : 0
                width: grid.sel ? area.width * (grid.sel.q1 - grid.sel.q0 + 1) / 96 : 0
                height: grid.sel ? (grid.sel.d1 - grid.sel.d0 + 1) * grid.rowHeight : 0
                color: grid.brush === "on" ? Theme.alpha(Theme.primary, 0.6) : Theme.alpha(Theme.danger, 0.3)
                border.color: grid.brush === "on" ? Theme.primary : Theme.danger
                z: 3
            }
            // day lines and hour lines (every hour faint, every 6 h stronger)
            Repeater {
                model: 6
                delegate: Rectangle {
                    required property int index
                    y: (index + 1) * grid.rowHeight
                    width: area.width
                    height: 1
                    color: Theme.alpha(Theme.border, 0.7)
                    z: 1
                }
            }
            Repeater {
                model: 23
                delegate: Rectangle {
                    required property int index
                    x: area.width * (index + 1) / 24
                    width: 1
                    height: area.height
                    color: (index + 1) % 6 === 0 ? Theme.border : Theme.alpha(Theme.border, 0.35)
                    z: 1
                }
            }

            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                z: 4
                cursorShape: grid.editable ? Qt.CrossCursor : Qt.ArrowCursor
                function cellAt(mx, my) {
                    const x = Math.min(Math.max(mx, 0), width - 1)
                    const y = Math.min(Math.max(my, 0), height - 1)
                    return { d: Math.floor(y / height * 7), q: Math.floor(x / width * 96) }
                }
                onPressed: mouse => {
                    if (!grid.editable)
                        return
                    const c = cellAt(mouse.x, mouse.y)
                    grid.drag = { a: c, b: c }
                }
                onPositionChanged: mouse => {
                    const c = cellAt(mouse.x, mouse.y)
                    grid.hover = c
                    if (grid.drag)
                        grid.drag = { a: grid.drag.a, b: c }
                }
                onReleased: {
                    const r = grid.sel
                    grid.drag = null
                    if (r)
                        grid.painted(r.d0, r.d1, r.q0, r.q1)
                }
                onCanceled: grid.drag = null
                onExited: grid.hover = null
            }
        }
    }

    // legend + tip
    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: 44
        spacing: 14
        Row {
            spacing: 6
            Rectangle { width: 10; height: 10; radius: 2; color: Theme.alpha(Theme.success, 0.6); anchors.verticalCenter: parent.verticalCenter }
            Text { text: "Record"; color: Theme.mutedForeground; font.family: Theme.font; font.pixelSize: Theme.textXs }
        }
        Row {
            spacing: 6
            Rectangle { width: 10; height: 10; radius: 2; color: Theme.alpha(Theme.muted, 0.6); border.color: Theme.border; anchors.verticalCenter: parent.verticalCenter }
            Text { text: "Off"; color: Theme.mutedForeground; font.family: Theme.font; font.pixelSize: Theme.textXs }
        }
        Row {
            visible: grid.nowDay >= 0
            spacing: 6
            Rectangle { width: 2; height: 10; color: Theme.danger; anchors.verticalCenter: parent.verticalCenter }
            Text { text: "Now"; color: Theme.mutedForeground; font.family: Theme.font; font.pixelSize: Theme.textXs }
        }
        Item { Layout.fillWidth: true }
        Text {
            text: grid.tip
            color: Theme.foreground
            font.family: Theme.font
            font.pixelSize: Theme.textXs
            font.weight: Font.Medium
        }
    }
}
