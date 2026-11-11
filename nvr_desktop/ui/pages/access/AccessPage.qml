import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Port of nvr_client/src/features/access/AccessPage.tsx: which cameras each role and user may see.
// What they may *do* (live, playback, export…) comes from their role on the Auth Server.
PageScroll {
    id: root

    Component.onCompleted: Access.refresh()

    PageHeader {
        title: "Access"
        description: "Which cameras each role and user may see. What they may do (live, playback, export…) comes from their role on the Auth Server."
        AppButton { text: "Refresh"; variant: "outline"; iconName: "refresh-cw"; onClicked: Access.refresh() }
    }

    LoadingState { visible: Access.loading && Access.error === "" }
    ErrorState { text: Access.error }

    RowLayout {
        visible: !Access.loading && Access.error === ""
        Layout.fillWidth: true
        spacing: 16

        // ---------------------------------------------------------------- roles and users
        Card {
            Layout.preferredWidth: 320
            Layout.alignment: Qt.AlignTop
            padding: 8
            spacing: 2

            SectionTitle { iconName: "users"; label: "Roles" }
            AppText { visible: Access.roles.length === 0; text: "No roles yet."; variant: "muted"; Layout.leftMargin: 8 }
            Repeater {
                model: Access.roles
                delegate: SubjectRow {
                    required property var modelData
                    objectName: "role-" + modelData.name
                    iconName: "shield-check"
                    title: modelData.name
                    hint: modelData.summary
                    active: Access.selected.type === "role" && Access.selected.name === modelData.name
                    onClicked: Access.select("role", modelData.name, modelData.name)
                }
            }
            SectionTitle { iconName: "user"; label: "Users" }
            AppText {
                visible: Access.users.length === 0
                text: "No users have access to this application yet."
                variant: "muted"
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                Layout.fillWidth: true
                Layout.leftMargin: 8
            }
            Repeater {
                model: Access.users
                delegate: SubjectRow {
                    required property var modelData
                    iconName: "user"
                    title: modelData.display_name
                    sub: modelData.sub
                    hint: modelData.summary
                    active: Access.selected.type === "user" && Access.selected.name === String(modelData.id)
                    onClicked: Access.select("user", String(modelData.id), modelData.display_name + " (" + modelData.username + ")")
                }
            }
        }

        // ---------------------------------------------------------------- the selected subject
        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            spacing: 12

            EmptyState {
                visible: !Access.selected.type
                iconName: "key-round"
                title: "Choose a role or a user"
                text: "A user sees the cameras of their own grants plus those of each of their roles. Admins see everything."
            }
            LoadingState { visible: !!Access.selected.type && Access.grantsLoading }
            ErrorState { text: Access.grantsError }
            Repeater {
                // a fresh editor for every load (also after Save), so it starts from what the server has
                model: !!Access.grants && !Access.grantsLoading ? [Access.revision] : []
                delegate: editorComponent
            }
        }
    }

    Component {
        id: editorComponent

        Card {
            id: editor
            objectName: "grantEditor"
            Layout.fillWidth: true
            padding: 20
            spacing: 14

            property bool all: Access.grants.all_cameras
            property var groups: Access.grants.groups.slice()
            property var cameras: Access.grants.cameras.slice()
            readonly property bool dirty: JSON.stringify([all, groups, cameras])
                !== JSON.stringify([Access.grants.all_cameras, Access.grants.groups, Access.grants.cameras])

            function add(list, item) {
                if (list.some(x => x.id === item.id))
                    return list
                return list.concat([item]).sort((a, b) => a.name.localeCompare(b.name))
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    AppText { text: Access.selected.type === "role" ? "ROLE" : "USER"; variant: "small" }
                    AppText { text: Access.selected.label; variant: "heading"; Layout.fillWidth: true }
                    AppText {
                        visible: Access.selected.type === "user" && (Access.selected.roles || []).length > 0
                        text: "Also sees the cameras of: " + (Access.selected.roles || []).join(", ")
                        variant: "muted"
                        Layout.fillWidth: true
                    }
                }
                AppButton {
                    text: "Reset"
                    variant: "outline"
                    enabled: editor.dirty && !Access.saving
                    onClicked: {
                        editor.all = Access.grants.all_cameras
                        editor.groups = Access.grants.groups.slice()
                        editor.cameras = Access.grants.cameras.slice()
                    }
                }
                AppButton {
                    objectName: "saveGrants"
                    text: Access.saving ? "Saving…" : "Save"
                    iconName: "save"
                    enabled: editor.dirty && !Access.saving
                    onClicked: Access.save(editor.all, editor.groups.map(g => g.id), editor.cameras.map(c => c.id))
                }
            }

            Rectangle {
                visible: !!Access.selected.isAdminRole
                Layout.fillWidth: true
                implicitHeight: adminNote.implicitHeight + 16
                radius: Theme.radiusSm
                color: Theme.alpha(Theme.muted, 0.6)
                border.color: Theme.border
                AppText {
                    id: adminNote
                    anchors.fill: parent
                    anchors.margins: 8
                    text: "The Admin role has every permission (*) and always sees every camera. Grants below are not needed."
                    wrapMode: Text.WordWrap
                    elide: Text.ElideNone
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: allRow.implicitHeight + 20
                radius: Theme.radiusSm
                color: "transparent"
                border.color: Theme.border
                RowLayout {
                    id: allRow
                    anchors.fill: parent
                    anchors.margins: 10
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        AppText { text: "All cameras"; font.weight: Font.Medium }
                        AppText { text: "Every camera, including ones added later."; variant: "small" }
                    }
                    AppSwitch { checked: editor.all; onToggled: editor.all = checked }
                }
            }

            // camera groups
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8
                enabled: !editor.all
                opacity: editor.all ? 0.5 : 1
                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        AppText { text: "Camera groups"; font.weight: Font.Medium }
                        AppText { text: "A group includes all of its sub-groups."; variant: "small" }
                    }
                    GroupPicker {
                        implicitWidth: 260
                        placeholder: "Add a group…"
                        onPicked: (groupId, pathLabel) => {
                            if (groupId > 0)
                                editor.groups = editor.add(editor.groups, { id: groupId, name: pathLabel || ("Group #" + groupId) })
                        }
                    }
                }
                ItemList {
                    items: editor.groups
                    iconName: "folder"
                    empty: "No groups"
                    onRemoved: id => editor.groups = editor.groups.filter(x => x.id !== id)
                }
            }

            // single cameras
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8
                enabled: !editor.all
                opacity: editor.all ? 0.5 : 1
                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        AppText { text: "Single cameras"; font.weight: Font.Medium }
                        AppText { text: "Cameras outside the chosen groups."; variant: "small" }
                    }
                    CameraPicker {
                        implicitWidth: 260
                        store: EncoderCameras
                        label: "Add a camera…"
                        onPicked: cameraId => {
                            const option = EncoderCameras.byId(cameraId)
                            editor.cameras = editor.add(editor.cameras, { id: cameraId, name: option ? option.name : ("Camera #" + cameraId) })
                        }
                    }
                }
                ItemList {
                    items: editor.cameras
                    iconName: "camera"
                    empty: "No single cameras"
                    onRemoved: id => editor.cameras = editor.cameras.filter(x => x.id !== id)
                }
            }
        }
    }

    component SectionTitle: RowLayout {
        property string iconName: ""
        property string label: ""
        spacing: 6
        Layout.topMargin: 8
        Layout.leftMargin: 8
        Layout.bottomMargin: 2
        Icon { name: parent.iconName; size: 14; color: Theme.mutedForeground }
        AppText { text: parent.label.toUpperCase(); variant: "small"; font.weight: Font.Medium }
    }

    component SubjectRow: Rectangle {
        id: row
        property string iconName: ""
        property string title: ""
        property string sub: ""
        property string hint: ""
        property bool active: false
        signal clicked()

        Layout.fillWidth: true
        implicitHeight: rowColumn.implicitHeight + 16
        radius: Theme.radiusSm
        color: active ? Theme.accent : rowArea.containsMouse ? Theme.alpha(Theme.accent, 0.6) : "transparent"

        RowLayout {
            anchors.fill: parent
            anchors.margins: 8
            spacing: 10
            Icon { name: row.iconName; size: 16; color: Theme.mutedForeground; Layout.alignment: Qt.AlignTop }
            ColumnLayout {
                id: rowColumn
                Layout.fillWidth: true
                spacing: 1
                AppText { text: row.title; font.weight: Font.Medium; Layout.fillWidth: true }
                AppText { visible: row.sub !== ""; text: row.sub; variant: "small"; Layout.fillWidth: true }
                AppText { text: row.hint; variant: "small"; Layout.fillWidth: true }
            }
        }
        MouseArea {
            id: rowArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: row.clicked()
        }
    }

    component ItemList: ColumnLayout {
        id: list
        property var items: []
        property string iconName: ""
        property string empty: ""
        signal removed(int id)

        Layout.fillWidth: true
        spacing: 0

        Rectangle {
            visible: list.items.length === 0
            Layout.fillWidth: true
            implicitHeight: 40
            radius: Theme.radiusSm
            color: "transparent"
            border.color: Theme.border
            AppText { anchors.verticalCenter: parent.verticalCenter; x: 12; text: list.empty; variant: "muted" }
        }
        Rectangle {
            visible: list.items.length > 0
            Layout.fillWidth: true
            implicitHeight: itemsColumn.implicitHeight
            radius: Theme.radiusSm
            color: "transparent"
            border.color: Theme.border
            ColumnLayout {
                id: itemsColumn
                width: parent.width
                spacing: 0
                Repeater {
                    model: list.items
                    delegate: RowLayout {
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        Layout.leftMargin: 12
                        Layout.rightMargin: 4
                        Layout.preferredHeight: 38
                        spacing: 8
                        Icon { name: list.iconName; size: 16; color: Theme.mutedForeground }
                        AppText { text: modelData.name; Layout.fillWidth: true }
                        AppButton {
                            size: "icon"
                            variant: "ghost"
                            iconName: "x"
                            tip: "Remove " + modelData.name
                            onClicked: list.removed(modelData.id)
                        }
                    }
                }
            }
        }
    }
}
