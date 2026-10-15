import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Add / edit a camera (port of CameraFormSheet.tsx). Validation and the stream diff run in Python
// (app/features/cameras/forms.py) so both clients behave the same.
Sheet {
    id: sheet

    property var camera: null // null = add
    property var errors: []

    title: camera ? "Edit " + camera.name : "Add camera"
    description: "The scheduler assigns the camera to a media node within a few seconds; recorded streams start recording right away."
    width: 600

    function openFor(cam) {
        camera = cam
        errors = []
        nameField.text = cam ? cam.name : ""
        descField.text = cam ? (cam.description ?? "") : ""
        userField.text = cam ? (cam.username ?? "") : ""
        passField.text = ""
        untilFullSwitch.checked = !!cam && (cam.retention_days === null || cam.retention_days === undefined)
        retentionField.text = String(cam && cam.retention_days ? cam.retention_days : 7)
        enabledSwitch.checked = cam ? cam.enabled : true
        streams.clear()
        if (cam) {
            for (const s of cam.streams)
                streams.append({ profile: s.profile, source_url: s.source_url, record: s.record, rtsp_transport: s.rtsp_transport, existing: true })
        } else {
            streams.append({ profile: "main", source_url: "", record: true, rtsp_transport: "tcp", existing: false })
            streams.append({ profile: "sub", source_url: "", record: false, rtsp_transport: "tcp", existing: false })
        }
        open()
    }

    function formData() {
        const list = []
        for (let i = 0; i < streams.count; i++) {
            const s = streams.get(i)
            list.push({ profile: s.profile, source_url: s.source_url, record: s.record, rtsp_transport: s.rtsp_transport, existing: s.existing })
        }
        return {
            name: nameField.text, description: descField.text, username: userField.text, password: passField.text,
            retention_days: retentionField.text, keep_until_full: untilFullSwitch.checked,
            enabled: enabledSwitch.checked, streams: list
        }
    }

    function save() {
        const form = formData()
        errors = Cameras.validate(form)
        if (errors.length > 0)
            return
        if (camera)
            Cameras.update(camera.id, form)
        else
            Cameras.create(form)
    }

    Connections {
        target: Cameras
        function onSaved(cameraId) { if (sheet.opened) sheet.close() }
    }

    ListModel { id: streams }

    // ---------------------------------------------------------------- fields
    FormField { label: "Name"; AppInput { id: nameField; placeholderText: "Gate camera"; Layout.fillWidth: true } }
    FormField {
        label: "Description"
        AppTextArea { id: descField; placeholderText: "Optional"; Layout.fillWidth: true; Layout.preferredHeight: 64 }
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: 12
        FormField { label: "Username"; AppInput { id: userField; placeholderText: "admin"; Layout.fillWidth: true } }
        FormField {
            label: "Password"
            AppInput {
                id: passField
                echoMode: TextInput.Password
                placeholderText: sheet.camera && sheet.camera.has_password ? "•••••• (unchanged)" : ""
                Layout.fillWidth: true
            }
        }
    }
    // retention: N days counted back from the latest recording, or until storage is full
    ColumnLayout {
        Layout.fillWidth: true
        spacing: 6
        AppText { text: "Keep recordings"; font.weight: Font.Medium }
        RowLayout {
            spacing: 10
            AppInput { id: retentionField; implicitWidth: 110; enabled: !untilFullSwitch.checked; inputMethodHints: Qt.ImhDigitsOnly }
            AppText { text: "days"; variant: untilFullSwitch.checked ? "muted" : "body" }
            Item { implicitWidth: 8 }
            AppSwitch { id: untilFullSwitch; text: "Until storage is full" }
        }
        AppText {
            text: untilFullSwitch.checked
                ? "Recordings are never deleted by age; the oldest are replaced only when all storage is full."
                : "Days count back from the camera's latest recording, so a stopped camera keeps its history. When all storage is full the oldest recordings are always replaced."
            variant: "small"
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
            Layout.fillWidth: true
        }
    }
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: enabledRow.implicitHeight + 20
        radius: Theme.radiusSm
        color: "transparent"
        border.color: Theme.border
        RowLayout {
            id: enabledRow
            anchors.fill: parent
            anchors.margins: 10
            anchors.leftMargin: 12
            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true
                AppText { text: "Camera enabled" }
                AppText { text: "Off: the camera is not pulled; no live view, no new recording."; variant: "small" }
            }
            AppSwitch { id: enabledSwitch }
        }
    }

    Separator {}

    // ---------------------------------------------------------------- streams
    RowLayout {
        Layout.fillWidth: true
        ColumnLayout {
            spacing: 2
            Layout.fillWidth: true
            AppText { text: "Streams"; font.weight: Font.Medium; Layout.fillWidth: true }
            AppText { text: "Credentials are added to the URL automatically."; variant: "small"; Layout.fillWidth: true }
        }
        AppButton {
            text: "Add stream"; iconName: "plus"; variant: "outline"; size: "sm"
            onClicked: streams.append({ profile: "stream" + (streams.count + 1), source_url: "", record: false, rtsp_transport: "tcp", existing: false })
        }
    }

    Repeater {
        model: streams
        delegate: Rectangle {
            id: streamBox
            required property int index
            required property string profile
            required property string source_url
            required property bool record
            required property string rtsp_transport
            required property bool existing

            Layout.fillWidth: true
            implicitHeight: box.implicitHeight + 24
            radius: Theme.radius
            color: Theme.alpha(Theme.muted, 0.6)
            border.color: Theme.border

            ColumnLayout {
                id: box
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    AppInput {
                        text: streamBox.profile
                        enabled: !streamBox.existing
                        implicitWidth: 130
                        implicitHeight: 32
                        onTextEdited: streams.setProperty(streamBox.index, "profile", text.toLowerCase())
                    }
                    AppSwitch {
                        text: "Record"
                        checked: streamBox.record
                        onToggled: streams.setProperty(streamBox.index, "record", checked)
                    }
                    Item { Layout.fillWidth: true }
                    AppSelect {
                        implicitWidth: 110
                        implicitHeight: 32
                        options: [{ value: "tcp", label: "TCP" }, { value: "udp", label: "UDP" }, { value: "automatic", label: "Auto" }]
                        value: streamBox.rtsp_transport
                        onPicked: v => streams.setProperty(streamBox.index, "rtsp_transport", v)
                    }
                    AppButton {
                        variant: "ghost"; size: "icon"; iconName: "trash-2"; tip: "Remove stream"
                        onClicked: streams.remove(streamBox.index)
                    }
                }
                AppInput {
                    text: streamBox.source_url
                    placeholderText: "rtsp://192.168.1.64:554/…"
                    font.family: Theme.mono
                    font.pixelSize: Theme.textXs
                    Layout.fillWidth: true
                    onTextEdited: streams.setProperty(streamBox.index, "source_url", text)
                }
                AppText {
                    text: streamBox.record ? "Recorded continuously and available live." : "Live only: connects to the camera when someone watches."
                    variant: "small"
                    font.pixelSize: 11
                }
            }
        }
    }

    // ---------------------------------------------------------------- brand hints
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: hints.implicitHeight + 24
        radius: Theme.radius
        color: Theme.alpha(Theme.info, 0.08)
        border.color: Theme.alpha(Theme.info, 0.3)
        ColumnLayout {
            id: hints
            anchors.fill: parent
            anchors.margins: 12
            spacing: 4
            RowLayout {
                spacing: 6
                Icon { name: "info"; size: 14; color: Theme.info }
                AppText { text: "Common RTSP URLs"; color: Theme.info; font.weight: Font.Medium; font.pixelSize: Theme.textXs }
            }
            Repeater {
                model: Cameras.brandExamples()
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 8
                    AppText { text: modelData.brand; variant: "small"; Layout.preferredWidth: 72 }
                    AppText { text: modelData.url; variant: "mono"; wrapMode: Text.WrapAnywhere; elide: Text.ElideNone; Layout.fillWidth: true }
                }
            }
        }
    }

    // ---------------------------------------------------------------- errors
    Rectangle {
        visible: sheet.errors.length > 0
        Layout.fillWidth: true
        implicitHeight: errorList.implicitHeight + 24
        radius: Theme.radius
        color: Theme.alpha(Theme.danger, 0.1)
        border.color: Theme.alpha(Theme.danger, 0.4)
        ColumnLayout {
            id: errorList
            anchors.fill: parent
            anchors.margins: 12
            spacing: 4
            Repeater {
                model: sheet.errors
                delegate: AppText {
                    required property string modelData
                    text: "• " + modelData
                    color: Theme.danger
                    wrapMode: Text.WordWrap
                    elide: Text.ElideNone
                    Layout.fillWidth: true
                }
            }
        }
    }

    footer: [
        AppButton { text: sheet.camera ? "Save changes" : "Add camera"; onClicked: sheet.save() },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: sheet.close() },
        Item { Layout.fillWidth: true }
    ]

    component FormField: ColumnLayout {
        property string label: ""
        default property alias field: slot.data
        Layout.fillWidth: true
        spacing: 6
        AppText { text: label; font.weight: Font.Medium }
        ColumnLayout { id: slot; Layout.fillWidth: true }
    }
}
