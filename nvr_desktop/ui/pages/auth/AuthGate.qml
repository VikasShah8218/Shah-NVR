import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Shown instead of the app while nobody is signed in (port of nvr_client LoginPage.tsx + ServerUnreachable).
// Auth.state: checking | unreachable | signed_out (docs/DESKTOP_AUTH_PLAN.md §4, §8).
Rectangle {
    id: gate
    color: Theme.background

    // the editable server address (also on the login form: tokens belong to one server)
    function saveServer(url) {
        const clean = url.trim().replace(/\/+$/, "")
        if (clean !== "" && clean !== Prefs.centralUrl)
            Prefs.centralUrl = clean  // AppContext moves the session to the new server and asks it again
        else
            Auth.retry()
    }

    ColumnLayout {
        anchors.centerIn: parent
        width: 380
        spacing: 20

        // brand
        ColumnLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 10
            Image {
                Layout.alignment: Qt.AlignHCenter
                source: ProductLogo
                sourceSize.width: 112
                sourceSize.height: 112
                width: 56
                height: 56
                Layout.preferredWidth: 56
                Layout.preferredHeight: 56
                fillMode: Image.PreserveAspectFit
                smooth: true
                mipmap: true
            }
            AppText {
                Layout.alignment: Qt.AlignHCenter
                text: ProductName
                variant: "title"
            }
        }

        // checking
        RowLayout {
            visible: Auth.state === "checking"
            Layout.alignment: Qt.AlignHCenter
            spacing: 8
            Spinner {}
            AppText { text: "Connecting to " + Auth.serverUrl + "…"; variant: "muted" }
        }

        // unreachable
        Card {
            visible: Auth.state === "unreachable"
            Layout.fillWidth: true
            padding: 24
            spacing: 12
            RowLayout {
                spacing: 10
                Icon { name: "server-off"; size: 20; color: Theme.danger }
                AppText { text: "Cannot reach the server"; variant: "heading" }
            }
            AppText {
                text: Auth.loginError || ("Central manager at " + Auth.serverUrl + " did not answer.")
                variant: "muted"
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                Layout.fillWidth: true
            }
            AppText { text: "Server address"; font.weight: Font.Medium }
            AppInput {
                id: unreachableUrl
                objectName: "unreachableUrl"
                text: Prefs.centralUrl
                placeholderText: "http://192.168.1.3:8000"
                Layout.fillWidth: true
                onAccepted: gate.saveServer(text)
            }
            AppButton {
                objectName: "retryButton"
                text: "Retry"
                iconName: "refresh-cw"
                Layout.fillWidth: true
                onClicked: gate.saveServer(unreachableUrl.text)
            }
        }

        // login form
        Card {
            id: loginCard
            visible: Auth.state === "signed_out"
            Layout.fillWidth: true
            padding: 24
            spacing: 12

            property bool showPassword: false
            function submit() {
                if (Auth.busy || userField.text.trim() === "" || passField.text === "")
                    return
                const server = serverField.text.trim().replace(/\/+$/, "")
                if (server !== Prefs.centralUrl) {  // a new server: ask it first, then sign in there
                    gate.saveServer(server)
                    return
                }
                Auth.signIn(userField.text, passField.text, rememberBox.checked)
                passField.text = ""  // never kept after an attempt
            }

            AppText { text: "Sign in"; variant: "heading" }
            AppText {
                visible: Auth.endedReason !== ""
                text: Auth.endedReason
                color: Theme.warning
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                Layout.fillWidth: true
            }

            AppText { text: "Username"; font.weight: Font.Medium }
            AppInput {
                id: userField
                objectName: "loginUser"
                // filled once from the last sign-in (not bound: a binding would wipe what the user typed
                // whenever Auth changes, e.g. after a wrong password)
                placeholderText: "Username"
                Layout.fillWidth: true
                enabled: !Auth.busy
                onAccepted: passField.forceActiveFocus()
            }
            AppText { text: "Password"; font.weight: Font.Medium }
            AppInput {
                id: passField
                objectName: "loginPassword"
                placeholderText: "Password"
                echoMode: loginCard.showPassword ? TextInput.Normal : TextInput.Password
                rightPadding: 36
                Layout.fillWidth: true
                enabled: !Auth.busy
                onAccepted: loginCard.submit()
                Icon {
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    name: loginCard.showPassword ? "eye-off" : "eye"
                    size: 16
                    color: Theme.mutedForeground
                    MouseArea {
                        anchors.fill: parent
                        anchors.margins: -4
                        cursorShape: Qt.PointingHandCursor
                        onClicked: loginCard.showPassword = !loginCard.showPassword
                    }
                }
            }
            AppCheckBox {
                id: rememberBox
                objectName: "rememberBox"
                text: Auth.secureStoreSupported ? "Keep me signed in" : "Keep me signed in (not available on this system)"
                enabled: Auth.secureStoreSupported && !Auth.busy
                checked: false
            }
            AppText {
                visible: Auth.loginError !== ""
                objectName: "loginError"
                text: Auth.loginError
                color: Theme.danger
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                Layout.fillWidth: true
            }
            AppButton {
                objectName: "signInButton"
                text: Auth.busy ? "Signing in…" : "Sign in"
                iconName: "lock"
                Layout.fillWidth: true
                enabled: !Auth.busy && userField.text.trim() !== "" && passField.text !== ""
                onClicked: loginCard.submit()
            }

            Separator { Layout.fillWidth: true }
            AppText { text: "Server"; variant: "small" }
            AppInput {
                id: serverField
                objectName: "loginServer"
                text: Prefs.centralUrl
                placeholderText: "http://192.168.1.3:8000"
                Layout.fillWidth: true
                enabled: !Auth.busy
                onAccepted: loginCard.submit()
            }
        }
    }

    // focus the first empty field whenever the form appears
    Connections {
        target: Auth
        function onChanged() {
            if (Auth.state === "signed_out" && !Auth.busy) {
                if (userField.text === "")
                    userField.text = Auth.lastUsername
                Qt.callLater(() => (userField.text === "" ? userField : passField).forceActiveFocus())
            }
        }
    }
    Component.onCompleted: {
        userField.text = Auth.lastUsername
        if (Auth.state === "signed_out")
            (userField.text === "" ? userField : passField).forceActiveFocus()
    }
}
