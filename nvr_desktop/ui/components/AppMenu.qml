import QtQuick
import QtQuick.Controls
import "../theme"

// Dropdown menu (port of shadcn DropdownMenu). Fill with AppMenuItem / MenuSeparator.
Menu {
    id: menu
    padding: 4
    implicitWidth: 230

    delegate: AppMenuItem {}

    background: Rectangle {
        implicitWidth: 230
        color: Theme.popover
        radius: Theme.radius
        border.color: Theme.border
    }
}
