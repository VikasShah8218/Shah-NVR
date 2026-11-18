import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Create / edit / view a recording schedule (port of nvr_client features/schedules/ScheduleEditor.tsx): paint the
// week grid, or type exact times in the block list under it. The draft lives in Schedules.editorState.
AppDialog {
    id: dialog
    objectName: "scheduleEditor"

    readonly property var ed: Schedules.editorState
    readonly property var dayNames: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    property int cameraCount: 0

    function openFor(schedule, readOnly) {
        ed.open(schedule ?? null, readOnly)
        cameraCount = schedule ? schedule.cameraCount : 0
        nameField.text = ed.name
        descField.text = ed.description
        open()
        if (!readOnly)
            nameField.forceActiveFocus()
    }

    width: Math.min(920, parent ? parent.width - 40 : 920)
    title: ed.readOnly ? ed.name : ed.scheduleId > 0 ? "Edit " + ed.name : "New recording schedule"
    description: "Times are site time. Cameras record in the green times and keep video around events in the amber times; a change applies within a few seconds"
        + (cameraCount > 0 ? " to the " + cameraCount + " camera" + (cameraCount === 1 ? "" : "s") + " using it." : ".")

    Connections {
        target: Schedules
        function onSaved(id) { if (dialog.opened) dialog.close() }
    }

    Flickable {
        id: scroller
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(content.implicitHeight, (dialog.parent ? dialog.parent.height : 800) - 220)
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: AppScrollBar {}

        ColumnLayout {
            id: content
            width: scroller.width - 12
            spacing: 14

            RowLayout {
                visible: !dialog.ed.readOnly
                Layout.fillWidth: true
                spacing: 12
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 5
                    AppText { text: "Name"; font.weight: Font.Medium }
                    AppInput {
                        id: nameField
                        objectName: "scheduleName"
                        Layout.fillWidth: true
                        placeholderText: "e.g. Office hours"
                        maximumLength: 64
                        onTextEdited: dialog.ed.setName(text)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 5
                    AppText { text: "Description (optional)"; font.weight: Font.Medium }
                    AppInput {
                        id: descField
                        Layout.fillWidth: true
                        maximumLength: 1000
                        onTextEdited: dialog.ed.setDescription(text)
                    }
                }
            }

            RowLayout {
                visible: !dialog.ed.readOnly
                Layout.fillWidth: true
                spacing: 8
                AppText { text: "Start from"; variant: "small" }
                Repeater {
                    model: Schedules.templates
                    delegate: AppButton {
                        required property var modelData
                        text: modelData.label
                        tip: modelData.hint
                        size: "sm"
                        variant: "outline"
                        onClicked: dialog.ed.applyTemplate(modelData.key)
                    }
                }
                AppButton { text: "Clear"; iconName: "eraser"; size: "sm"; variant: "ghost"; onClicked: dialog.ed.clear() }
                Item { Layout.fillWidth: true }
                ToggleGroup {
                    objectName: "scheduleBrush"
                    options: [{ value: "on", label: "Paint record" }, { value: "event", label: "Paint event" },
                              { value: "off", label: "Paint off" }]
                    value: dialog.ed.brush
                    onPicked: v => dialog.ed.setBrush(v)
                }
            }

            WeekGrid {
                objectName: "scheduleGrid"
                Layout.fillWidth: true
                rows: dialog.ed.rows
                editable: !dialog.ed.readOnly
                brush: dialog.ed.brush
                nowDay: Schedules.siteNowDay
                nowMinute: Schedules.siteNowMinute
                onPainted: (d0, d1, q0, q1) => dialog.ed.paint(d0, d1, q0, q1)
            }
            AppText {
                Layout.fillWidth: true
                variant: "small"
                wrapMode: Text.WordWrap
                text: (dialog.ed.readOnly ? "" : "Drag across days and hours to paint (15-minute steps). ") + dialog.ed.hoursText
            }

            RowLayout {
                Layout.fillWidth: true
                AppText { text: "Blocks"; font.weight: Font.Medium }
                AppText { text: "(exact times; end before start runs past midnight)"; variant: "small"; Layout.fillWidth: true }
                AppButton {
                    visible: !dialog.ed.readOnly
                    enabled: dialog.ed.canAddBlock
                    text: "Add block"; iconName: "plus"; size: "sm"; variant: "outline"
                    onClicked: dialog.ed.addBlock()
                }
            }
            Rectangle {
                visible: dialog.ed.blocks.length === 0
                Layout.fillWidth: true
                implicitHeight: 40
                radius: Theme.radiusSm
                color: "transparent"
                border.color: Theme.border
                AppText {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    verticalAlignment: Text.AlignVCenter
                    variant: "muted"
                    text: "No blocks: cameras on this schedule never record."
                }
            }
            Repeater {
                model: dialog.ed.blocks
                delegate: Rectangle {
                    id: blockRow
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: blockLayout.implicitHeight + 16
                    radius: Theme.radiusSm
                    color: "transparent"
                    border.color: Theme.border

                    RowLayout {
                        id: blockLayout
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 8
                        AppText { visible: dialog.ed.readOnly; text: blockRow.modelData.label; Layout.fillWidth: true }
                        Row {
                            visible: !dialog.ed.readOnly
                            spacing: 4
                            Repeater {
                                model: 7
                                delegate: Rectangle {
                                    required property int index
                                    readonly property bool on: blockRow.modelData.days.indexOf(index) >= 0
                                    width: 38
                                    height: 28
                                    radius: Theme.radiusSm
                                    color: on ? Theme.alpha(Theme.primary, 0.2) : dayArea.containsMouse ? Theme.accent : "transparent"
                                    border.color: Theme.border
                                    Text {
                                        anchors.centerIn: parent
                                        text: dialog.dayNames[index]
                                        color: on ? Theme.primary : Theme.foreground
                                        font.family: Theme.font
                                        font.pixelSize: Theme.textXs
                                        font.weight: Font.Medium
                                    }
                                    MouseArea {
                                        id: dayArea
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: dialog.ed.toggleDay(blockRow.modelData.index, index)
                                    }
                                }
                            }
                        }
                        AppInput {
                            visible: !dialog.ed.readOnly
                            Layout.preferredWidth: 76
                            font.family: Theme.mono
                            text: blockRow.modelData.start
                            placeholderText: "08:00"
                            maximumLength: 5
                            color: blockRow.modelData.startBad ? Theme.danger : Theme.foreground
                            onEditingFinished: if (text !== blockRow.modelData.start) dialog.ed.setTime(blockRow.modelData.index, "start", text)
                        }
                        AppText { visible: !dialog.ed.readOnly; text: "–"; variant: "muted" }
                        AppInput {
                            visible: !dialog.ed.readOnly
                            Layout.preferredWidth: 76
                            font.family: Theme.mono
                            text: blockRow.modelData.end
                            placeholderText: "18:00"
                            maximumLength: 5
                            color: blockRow.modelData.endBad ? Theme.danger : Theme.foreground
                            onEditingFinished: if (text !== blockRow.modelData.end) dialog.ed.setTime(blockRow.modelData.index, "end", text)
                        }
                        AppSelect {
                            visible: !dialog.ed.readOnly
                            objectName: "blockMode"
                            Layout.preferredWidth: 104
                            options: [{ value: "continuous", label: "Record" }, { value: "event", label: "Event" }, { value: "off", label: "Off" }]
                            value: blockRow.modelData.mode
                            onPicked: v => dialog.ed.setMode(blockRow.modelData.index, v)
                        }
                        AppText {
                            visible: !dialog.ed.readOnly && (blockRow.modelData.hint !== "" || blockRow.modelData.error !== "")
                            text: blockRow.modelData.error || blockRow.modelData.hint
                            color: blockRow.modelData.error ? Theme.danger : Theme.mutedForeground
                            variant: "small"
                        }
                        Item { visible: !dialog.ed.readOnly; Layout.fillWidth: true }
                        AppButton {
                            visible: !dialog.ed.readOnly
                            size: "icon"; variant: "ghost"; iconName: "trash-2"; tip: "Remove block"
                            onClicked: dialog.ed.removeBlock(blockRow.modelData.index)
                        }
                    }
                }
            }
        }
    }

    footer: [
        Item { Layout.fillWidth: true },
        AppButton { text: dialog.ed.readOnly ? "Close" : "Cancel"; variant: "outline"; onClicked: dialog.close() },
        AppButton {
            objectName: "scheduleSave"
            visible: !dialog.ed.readOnly
            text: dialog.ed.busy ? "Saving…" : dialog.ed.scheduleId > 0 ? "Save" : "Create"
            enabled: dialog.ed.canSave
            onClicked: dialog.ed.save()
        }
    ]
}
