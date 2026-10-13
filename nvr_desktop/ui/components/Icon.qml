import QtQuick
import "../theme"

// Lucide icon (assets/icons/<name>.svg) rendered in any colour by app/core/icons.py.
// An Item wrapper so layouts see exactly `size` (an Image's implicit size would be its 2x render size).
Item {
    id: icon

    property string name
    property color color: Theme.foreground
    property int size: 16

    implicitWidth: size
    implicitHeight: size

    Image {
        anchors.fill: parent
        sourceSize: Qt.size(icon.size * 2, icon.size * 2) // 2x for crisp edges on high-DPI screens
        source: icon.name ? "image://icon/" + icon.name + "/" + icon.color.toString().slice(-6) : ""
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
    }
}
