import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Port of nvr_client/src/features/audit/AuditPage.tsx: sign-ins, video access, changes and refused requests.
PageScroll {
    id: root

    readonly property var columns: [
        { title: "Time", width: 170 }, { title: "User", width: 130 }, { title: "Action", width: 220 },
        { title: "Camera", width: 80 }, { title: "Result", width: 90 }, { title: "Details", width: 0 }, { title: "IP", width: 130 }
    ]

    Component.onCompleted: AuditLog.refresh()

    PageHeader {
        title: "Audit log"
        description: "Who signed in, watched, exported or changed what, and every refused request. Kept for one year."
        AppButton { text: "Refresh"; variant: "outline"; iconName: "refresh-cw"; onClicked: AuditLog.refresh() }
    }

    Flow {
        Layout.fillWidth: true
        spacing: 8
        AppInput {
            objectName: "auditUser"
            width: 180
            iconName: "user"
            placeholderText: "User"
            text: AuditLog.username
            onEditingFinished: AuditLog.setUsername(text)
        }
        AppInput {
            objectName: "auditAction"
            width: 220
            iconName: "search"
            placeholderText: "Action (e.g. auth, cameras)"
            text: AuditLog.action
            onEditingFinished: AuditLog.setAction(text)
        }
        AppSelect {
            implicitWidth: 150
            options: [{ value: "", label: "Any result" }, { value: "ok", label: "OK" },
                      { value: "denied", label: "Denied" }, { value: "failed", label: "Failed" }]
            value: AuditLog.status
            onPicked: v => AuditLog.setStatus(v)
        }
        AppSelect {
            implicitWidth: 160
            options: [{ value: "24h", label: "Last 24 hours" }, { value: "7d", label: "Last 7 days" },
                      { value: "30d", label: "Last 30 days" }, { value: "all", label: "Everything" }]
            value: AuditLog.timeRange
            onPicked: v => AuditLog.setRange(v)
        }
    }

    LoadingState { visible: AuditLog.loading && AuditLog.error === "" && AuditLog.listModel.count === 0 }
    ErrorState { text: AuditLog.error }
    EmptyState {
        visible: !AuditLog.loading && AuditLog.error === "" && AuditLog.total === 0
        iconName: "scroll-text"
        title: "No events"
        text: "Nothing matches these filters."
    }

    Rectangle {
        visible: AuditLog.listModel.count > 0
        Layout.fillWidth: true
        implicitHeight: table.implicitHeight
        radius: Theme.radiusLg
        color: Theme.card
        border.color: Theme.border
        clip: true

        ColumnLayout {
            id: table
            width: parent.width
            spacing: 0
            TableHeader { columns: root.columns }
            Repeater {
                model: AuditLog.listModel
                delegate: TableRow {
                    required property var model
                    AppText { text: Fmt.dateTime(model.at); variant: "small"; Layout.preferredWidth: 170 }
                    AppText { text: model.username || "—"; Layout.preferredWidth: 130 }
                    AppText { text: model.action; font.family: Theme.mono; font.pixelSize: Theme.textXs; Layout.preferredWidth: 220 }
                    AppText { text: model.camera_id ? "#" + model.camera_id : "—"; variant: "small"; Layout.preferredWidth: 80 }
                    AppText {
                        text: model.status
                        color: model.status === "ok" ? Theme.success : model.status === "denied" ? Theme.warning : Theme.danger
                        Layout.preferredWidth: 90
                    }
                    AppText {
                        text: model.detailText || (model.method ? model.method + " " + model.path : "")
                        variant: "small"
                        Layout.fillWidth: true
                        AppToolTip { visible: detailHover.hovered && parent.truncated; text: parent.text }
                        HoverHandler { id: detailHover }
                    }
                    AppText { text: model.ip || "—"; variant: "small"; Layout.preferredWidth: 130 }
                }
            }
        }
    }

    Pager {
        Layout.fillWidth: true
        store: AuditLog
        sizes: [25, 50, 100]
    }
}
