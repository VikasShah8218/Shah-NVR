import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

// Month calendar in a popup (port of the shadcn Calendar + Popover). Future days are disabled.
Popup {
    id: popup

    property date selected: new Date()
    property int month: selected.getMonth()
    property int year: selected.getFullYear()
    signal picked(date day)

    padding: 12
    width: 280
    onOpened: { month = selected.getMonth(); year = selected.getFullYear() }

    background: Rectangle {
        color: Theme.popover
        radius: Theme.radius
        border.color: Theme.border
    }

    contentItem: ColumnLayout {
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            AppButton {
                size: "icon"; variant: "ghost"; iconName: "chevron-left"
                onClicked: { if (popup.month === 0) { popup.month = 11; popup.year-- } else popup.month-- }
            }
            AppText {
                text: new Date(popup.year, popup.month, 1).toLocaleDateString(Qt.locale(), "MMMM yyyy")
                font.weight: Font.Medium
                horizontalAlignment: Text.AlignHCenter
                Layout.fillWidth: true
            }
            AppButton {
                size: "icon"; variant: "ghost"; iconName: "chevron-right"
                enabled: new Date(popup.year, popup.month + 1, 1) <= new Date()
                onClicked: { if (popup.month === 11) { popup.month = 0; popup.year++ } else popup.month++ }
            }
        }
        DayOfWeekRow {
            Layout.fillWidth: true
            delegate: Text {
                required property string shortName
                text: shortName
                color: Theme.mutedForeground
                font.family: Theme.font
                font.pixelSize: Theme.textXs
                horizontalAlignment: Text.AlignHCenter
            }
        }
        MonthGrid {
            id: grid
            month: popup.month
            year: popup.year
            Layout.fillWidth: true
            delegate: Rectangle {
                required property var model
                readonly property bool future: model.date > new Date()
                readonly property bool isSelected: model.date.toDateString() === popup.selected.toDateString()
                implicitWidth: 34
                implicitHeight: 32
                radius: Theme.radiusSm
                color: isSelected ? Theme.primary : area.containsMouse && !future ? Theme.accent : "transparent"
                opacity: model.month === popup.month ? (future ? 0.35 : 1) : 0.4
                Text {
                    anchors.centerIn: parent
                    text: model.day
                    color: isSelected ? Theme.primaryForeground : Theme.foreground
                    font.family: Theme.font
                    font.pixelSize: Theme.textSm
                }
                MouseArea {
                    id: area
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: !future
                    onClicked: {
                        popup.selected = model.date
                        popup.picked(model.date)
                        popup.close()
                    }
                }
            }
        }
    }
}
