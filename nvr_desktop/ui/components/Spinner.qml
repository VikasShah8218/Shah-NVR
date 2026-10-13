import QtQuick
import "../theme"

Icon {
    name: "loader-circle"
    color: Theme.mutedForeground
    size: 16
    RotationAnimation on rotation {
        from: 0
        to: 360
        duration: 900
        loops: Animation.Infinite
        running: visible
    }
}
