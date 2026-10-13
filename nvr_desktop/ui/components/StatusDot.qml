import QtQuick
import App
import "../theme"

Rectangle {
    property string status: ""
    width: 8
    height: 8
    radius: 4
    color: Theme.toneColor(Status.tone(status))
}
