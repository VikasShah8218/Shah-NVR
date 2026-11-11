import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// A page the signed-in user's role does not allow (port of RequirePerm in nvr_client). The server refuses its API
// calls anyway; this avoids a page full of errors.
PageScroll {
    EmptyState {
        objectName: "noAccess"
        Layout.fillWidth: true
        iconName: "shield-x"
        title: "No access"
        text: "Your role does not allow this page. Ask an administrator if you need it."
    }
}
