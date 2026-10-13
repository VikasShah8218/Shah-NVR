import QtQuick
import QtQuick.Controls
import "../theme"

// Dropdown. options: [{value, label}] (or plain strings). Bind `value`; `picked(value)` fires on user choice.
ComboBox {
    id: box

    property var options: []
    property var value
    property string placeholder: "Select…"
    signal picked(var value)

    readonly property var items: (options || []).map(o => typeof o === "object" ? o : ({ value: o, label: String(o) }))

    model: items
    textRole: "label"
    valueRole: "value"
    implicitHeight: 36
    implicitWidth: 180
    font.family: Theme.font
    font.pixelSize: Theme.textSm
    currentIndex: items.findIndex(o => o.value === value)
    displayText: currentIndex >= 0 ? items[currentIndex].label : placeholder
    onActivated: index => {
        box.value = items[index].value
        box.picked(items[index].value)
    }

    delegate: ItemDelegate {
        required property var modelData
        required property int index
        width: box.popup.width - 8
        height: 32
        hoverEnabled: true
        contentItem: Text {
            text: modelData.label
            color: Theme.foreground
            font: box.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: Theme.radiusSm
            color: parent.hovered || box.currentIndex === index ? Theme.accent : "transparent"
        }
    }
    contentItem: Text {
        leftPadding: 12
        rightPadding: 32
        text: box.displayText
        color: box.currentIndex >= 0 ? Theme.foreground : Theme.mutedForeground
        font: box.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: Icon {
        name: "chevron-down"
        color: Theme.mutedForeground
        size: 16
        x: box.width - width - 10
        anchors.verticalCenter: parent.verticalCenter
    }
    background: Rectangle {
        radius: Theme.radiusSm + 2
        color: box.hovered ? Theme.alpha(Theme.input, 0.4) : Theme.alpha(Theme.input, 0.25)
        border.color: box.activeFocus ? Theme.alpha(Theme.ring, 0.8) : Theme.input
    }
    popup: Popup {
        y: box.height + 4
        width: Math.max(box.width, 160)
        padding: 4
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 320)
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: box.popup.visible ? box.delegateModel : null
            currentIndex: box.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
        background: Rectangle {
            color: Theme.popover
            radius: Theme.radius
            border.color: Theme.border
        }
    }
}
