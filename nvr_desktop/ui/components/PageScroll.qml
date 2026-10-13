import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

// Scrollable page body with the standard page padding. Children stack vertically (ColumnLayout).
ScrollView {
    id: scroll

    default property alias content: column.data
    property int gap: 16 // space between sections

    clip: true
    contentWidth: availableWidth
    contentHeight: column.implicitHeight + Theme.pagePadding * 2
    ScrollBar.vertical: AppScrollBar {}
    ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AlwaysOff }

    ColumnLayout {
        id: column
        x: Theme.pagePadding
        y: Theme.pagePadding
        width: scroll.availableWidth - Theme.pagePadding * 2
        spacing: scroll.gap
    }
}
