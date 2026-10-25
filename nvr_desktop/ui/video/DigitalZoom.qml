import QtQuick
import "../theme"
import "../components"

// Digital zoom / pan over a video (pure view transform: no extra decoding or bandwidth).
// Put it over the video with `anchors.fill` in a clipping parent, and bind the video item to it:
//   scale: zoomer.zoom; transformOrigin: Item.Center; transform: Translate { x: zoomer.panX; y: zoomer.panY }
// Mouse: wheel zooms (1x-4x, 0.25 steps), drag pans while zoomed, double-click resets (or emits
// doubleClicked when doubleClickResets is false). Keyboard (after a click on the video): + / - zoom,
// arrows pan, 0 resets. A press that moved more than a few pixels is a pan, not a click.
Item {
    id: zoomer

    property bool doubleClickResets: true
    property real zoom: 1
    property real panX: 0
    property real panY: 0
    readonly property real maxPanX: width * (zoom - 1) / 2
    readonly property real maxPanY: height * (zoom - 1) / 2
    readonly property real step: 0.25
    readonly property real panStep: 40

    signal clicked()
    signal doubleClicked()

    function clampPan() {
        panX = Math.max(-maxPanX, Math.min(maxPanX, panX))
        panY = Math.max(-maxPanY, Math.min(maxPanY, panY))
    }
    function setZoom(value) {
        zoom = Math.max(1, Math.min(4, value))
        if (zoom === 1) {
            panX = 0
            panY = 0
        } else {
            clampPan()
        }
    }
    function panBy(dx, dy) {
        if (zoom <= 1)
            return
        panX += dx
        panY += dy
        clampPan()
    }
    function reset() {
        zoom = 1
        panX = 0
        panY = 0
    }

    onWidthChanged: clampPan()
    onHeightChanged: clampPan()

    Keys.onPressed: event => {
        switch (event.key) {
        case Qt.Key_Plus:
        case Qt.Key_Equal:
            setZoom(zoom + step)
            break
        case Qt.Key_Minus:
        case Qt.Key_Underscore:
            setZoom(zoom - step)
            break
        case Qt.Key_0:
            reset()
            break
        case Qt.Key_Left:
            if (zoom <= 1) return
            panBy(panStep, 0)
            break
        case Qt.Key_Right:
            if (zoom <= 1) return
            panBy(-panStep, 0)
            break
        case Qt.Key_Up:
            if (zoom <= 1) return
            panBy(0, panStep)
            break
        case Qt.Key_Down:
            if (zoom <= 1) return
            panBy(0, -panStep)
            break
        default:
            return
        }
        event.accepted = true
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        // Inside a PageScroll (Flickable) the page would steal the drag after a few pixels and stop the pan.
        preventStealing: true
        cursorShape: zoomer.zoom > 1
            ? (pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor) : Qt.ArrowCursor
        property real lastX: 0
        property real lastY: 0
        property real startX: 0
        property real startY: 0
        property bool moved: false
        onPressed: mouse => {
            zoomer.forceActiveFocus()
            lastX = startX = mouse.x
            lastY = startY = mouse.y
            moved = false
        }
        onPositionChanged: mouse => {
            if (!pressed)
                return
            if (Math.abs(mouse.x - startX) > 5 || Math.abs(mouse.y - startY) > 5)
                moved = true
            if (zoomer.zoom > 1)
                zoomer.panBy(mouse.x - lastX, mouse.y - lastY)
            lastX = mouse.x
            lastY = mouse.y
        }
        onClicked: if (!moved) zoomer.clicked()
        onDoubleClicked: {
            if (zoomer.doubleClickResets)
                zoomer.reset()
            else
                zoomer.doubleClicked()
        }
        onWheel: wheel => {
            zoomer.setZoom(zoomer.zoom + (wheel.angleDelta.y > 0 ? zoomer.step : -zoomer.step))
            wheel.accepted = true
        }
    }

    Rectangle {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.rightMargin: 12
        width: 40
        height: zoomControls.implicitHeight + 12
        radius: Theme.radiusSm
        color: Qt.rgba(0, 0, 0, 0.48)
        border.color: Qt.rgba(1, 1, 1, 0.16)

        Column {
            id: zoomControls
            anchors.centerIn: parent
            spacing: 2

            AppText {
                width: 32
                text: zoomer.zoom.toFixed(1) + "×"
                color: "white"
                font.pixelSize: 10
                horizontalAlignment: Text.AlignHCenter
            }
            AppButton {
                variant: "ghost"; size: "icon"; iconName: "plus"
                implicitWidth: 32; implicitHeight: 30; focusPolicy: Qt.NoFocus; tip: "Digital zoom in (mouse wheel up, +)"
                enabled: zoomer.zoom < 4
                onClicked: zoomer.setZoom(zoomer.zoom + zoomer.step)
            }
            AppButton {
                variant: "ghost"; size: "icon"; iconName: "chevron-up"
                implicitWidth: 32; implicitHeight: 30; focusPolicy: Qt.NoFocus; tip: "Pan up (↑)"
                enabled: zoomer.zoom > 1
                onClicked: zoomer.panBy(0, zoomer.panStep)
            }
            AppButton {
                variant: "ghost"; size: "icon"; iconName: "chevron-left"
                implicitWidth: 32; implicitHeight: 30; focusPolicy: Qt.NoFocus; tip: "Pan left (←)"
                enabled: zoomer.zoom > 1
                onClicked: zoomer.panBy(zoomer.panStep, 0)
            }
            AppButton {
                variant: "ghost"; size: "icon"; iconName: "chevron-right"
                implicitWidth: 32; implicitHeight: 30; focusPolicy: Qt.NoFocus; tip: "Pan right (→)"
                enabled: zoomer.zoom > 1
                onClicked: zoomer.panBy(-zoomer.panStep, 0)
            }
            AppButton {
                variant: "ghost"; size: "icon"; iconName: "chevron-down"
                implicitWidth: 32; implicitHeight: 30; focusPolicy: Qt.NoFocus; tip: "Pan down (↓)"
                enabled: zoomer.zoom > 1
                onClicked: zoomer.panBy(0, -zoomer.panStep)
            }
            AppButton {
                variant: "ghost"; size: "icon"; iconName: "minus"
                implicitWidth: 32; implicitHeight: 30; focusPolicy: Qt.NoFocus; tip: "Digital zoom out (mouse wheel down, −)"
                enabled: zoomer.zoom > 1
                onClicked: zoomer.setZoom(zoomer.zoom - zoomer.step)
            }
            AppButton {
                variant: "ghost"; size: "icon"; iconName: "rotate-ccw"
                implicitWidth: 32; implicitHeight: 30; focusPolicy: Qt.NoFocus
                tip: zoomer.doubleClickResets ? "Reset digital view (double-click, 0)" : "Reset digital view (0)"
                enabled: zoomer.zoom > 1
                onClicked: zoomer.reset()
            }
        }
    }
}
