import QtQuick
import QtQuick.Controls
import "../theme"

TextArea {
    id: area
    padding: 10
    wrapMode: TextEdit.Wrap
    color: Theme.foreground
    placeholderTextColor: Theme.mutedForeground
    font.family: Theme.font
    font.pixelSize: Theme.textSm
    background: Rectangle {
        radius: Theme.radiusSm + 2
        color: Theme.alpha(Theme.input, 0.25)
        border.width: area.activeFocus ? 2 : 1
        border.color: area.activeFocus ? Theme.alpha(Theme.ring, 0.8) : Theme.input
    }
}
