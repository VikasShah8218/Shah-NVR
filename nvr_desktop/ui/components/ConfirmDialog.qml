import QtQuick
import QtQuick.Layouts

// "Are you sure?" dialog. Put extra controls (e.g. a "force" switch) inside it as children.
AppDialog {
    id: confirm

    property string confirmLabel: "Confirm"
    property bool destructive: false
    signal confirmed()

    footer: [
        Item { Layout.fillWidth: true },
        AppButton { text: "Cancel"; variant: "outline"; onClicked: confirm.close() },
        AppButton {
            text: confirm.confirmLabel
            variant: confirm.destructive ? "destructive" : "default"
            onClicked: {
                confirm.close()
                confirm.confirmed()
            }
        }
    ]
}
