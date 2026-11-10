import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../theme"

// Group select (port of the web GroupPicker): a lazy tree (expand to drill down) plus server-side name search,
// never every group. Group id 0 = none ("No group" / "Top level" when `noneLabel` is set).
//   GroupPicker { value: groupId; label: groupPath; noneLabel: "No group"; onPicked: (id, label) => ... }
AppButton {
    id: root

    property int value: 0
    property string label: ""         // path label of `value` (the caller keeps it from the pick)
    property string noneLabel: ""
    property string placeholder: "Select group"
    property var isDisabled: null     // function(row: {id, path, ...}) -> bool
    signal picked(int groupId, string pathLabel)

    function pick(id, pathLabel) {
        popup.close()
        root.picked(id, pathLabel)
    }

    variant: "outline"
    implicitWidth: 224
    onClicked: popup.open()

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 10
        spacing: 8
        Icon { visible: root.value > 0; name: "folder"; size: 14; color: Theme.alpha(Theme.primary, 0.85) }
        AppText {
            objectName: "groupPickerLabel"
            text: root.value > 0 ? (root.label !== "" ? root.label : "Group #" + root.value)
                                 : root.noneLabel !== "" ? root.noneLabel : root.placeholder
            color: root.value > 0 || root.noneLabel !== "" ? Theme.foreground : Theme.mutedForeground
            Layout.fillWidth: true
        }
        Icon { name: "chevron-down"; size: 16; color: Theme.mutedForeground }
    }

    Popup {
        id: popup
        y: root.height + 4
        width: Math.max(root.width, 320)
        height: 400
        padding: 8
        background: Rectangle { color: Theme.popover; radius: Theme.radius; border.color: Theme.border }
        onAboutToShow: {
            PickerGroups.resetSearch()
            PickerGroups.collapseAll()
            PickerGroups.setActive(true)
            search.text = ""
        }
        onOpened: search.forceActiveFocus()
        onClosed: PickerGroups.setActive(false)

        ColumnLayout {
            anchors.fill: parent
            spacing: 6
            AppInput {
                id: search
                objectName: "groupPickerSearch"
                Layout.fillWidth: true
                iconName: "search"
                placeholderText: "Search groups"
                onTextChanged: PickerGroups.setSearch(text)
            }
            // "No group" / "Top level"
            Rectangle {
                visible: root.noneLabel !== "" && PickerGroups.query === ""
                Layout.fillWidth: true
                implicitHeight: 32
                radius: Theme.radiusSm
                color: root.value === 0 ? Theme.accent : noneArea.containsMouse ? Theme.alpha(Theme.accent, 0.7) : "transparent"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    spacing: 8
                    Icon { name: "inbox"; size: 15; color: Theme.mutedForeground }
                    AppText { text: root.noneLabel; font.italic: true; Layout.fillWidth: true }
                }
                MouseArea {
                    id: noneArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.pick(0, "")
                }
            }
            GroupTree {
                visible: PickerGroups.query === ""
                Layout.fillWidth: true
                Layout.fillHeight: true
                store: PickerGroups
                selectable: true
                selectedGroupId: root.value
                isDisabled: root.isDisabled
                onGroupClicked: row => root.pick(row.id, row.pathLabel)
            }
            // search results: name + path
            ListView {
                id: results
                visible: PickerGroups.query !== ""
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: PickerGroups.searchModel
                ScrollBar.vertical: AppScrollBar {}
                delegate: Rectangle {
                    id: result
                    required property var model
                    readonly property bool off: !!root.isDisabled && root.isDisabled(model)
                    width: results.width
                    height: 44
                    radius: Theme.radiusSm
                    opacity: off ? 0.45 : 1
                    color: model.id === root.value ? Theme.accent : resultArea.containsMouse && !off ? Theme.alpha(Theme.accent, 0.7) : "transparent"
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        spacing: 8
                        Icon { name: "folder"; size: 15; color: Theme.alpha(Theme.primary, 0.85); Layout.alignment: Qt.AlignTop; Layout.topMargin: 6 }
                        ColumnLayout {
                            spacing: 1
                            Layout.fillWidth: true
                            AppText { text: result.model.name; Layout.fillWidth: true }
                            AppText { text: result.model.pathLabel; variant: "small"; Layout.fillWidth: true }
                        }
                    }
                    MouseArea {
                        id: resultArea
                        anchors.fill: parent
                        enabled: !result.off
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.pick(result.model.id, result.model.pathLabel)
                    }
                }
                footer: AppText {
                    visible: PickerGroups.searchTotal > results.count
                    width: results.width
                    height: visible ? 24 : 0
                    text: results.count + " of " + PickerGroups.searchTotal + " shown: type more to narrow down."
                    variant: "small"
                }
                AppText {
                    visible: PickerGroups.query !== "" && PickerGroups.searchTotal === 0 && results.count === 0
                    text: "No groups match."
                    variant: "muted"
                    x: 8
                    y: 8
                }
            }
        }
    }
}
