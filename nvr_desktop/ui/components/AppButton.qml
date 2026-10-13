import QtQuick
import QtQuick.Controls
import "../theme"

// Button styled like the web client's shadcn Button.
// variant: default | outline | ghost | secondary | destructive     size: sm | md | icon
Button {
    id: control

    property string variant: "default"
    property string size: "md"
    property string iconName: ""
    property string tip: ""
    property real radius: Theme.radiusSm + 2

    readonly property color fg: variant === "default" ? Theme.primaryForeground
        : variant === "destructive" ? "#ffffff" : Theme.foreground

    implicitHeight: size === "sm" ? 30 : 36
    implicitWidth: size === "icon" ? implicitHeight : row.implicitWidth + (size === "sm" ? 20 : 28)
    hoverEnabled: true
    padding: 0
    opacity: enabled ? 1 : 0.5
    font.family: Theme.font
    font.pixelSize: Theme.textSm
    font.weight: Font.Medium

    contentItem: Item {
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 6
            Icon {
                visible: control.iconName !== ""
                name: control.iconName
                color: control.fg
                size: control.size === "sm" ? 14 : 16
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                visible: control.text !== ""
                text: control.text
                color: control.fg
                font: control.font
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    background: Rectangle {
        radius: control.radius
        border.width: control.variant === "outline" ? 1 : 0
        border.color: Theme.border
        color: {
            const hover = control.hovered || control.down
            switch (control.variant) {
            case "default": return hover ? Theme.alpha(Theme.primary, 0.88) : Theme.primary
            case "destructive": return hover ? Theme.alpha(Theme.danger, 0.88) : Theme.danger
            case "secondary": return hover ? Qt.lighter(Theme.secondary, 1.12) : Theme.secondary
            default: return hover ? Theme.accent : "transparent" // outline, ghost
            }
        }
    }

    AppToolTip {
        visible: control.tip !== "" && control.hovered
        text: control.tip
    }
}
