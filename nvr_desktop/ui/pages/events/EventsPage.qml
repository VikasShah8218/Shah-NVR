import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Every event the user may see (port of nvr_client features/events/EventsPage.tsx). A click opens Playback at
// that camera, from the camera's pre-event seconds.
PageScroll {
    id: root
    objectName: "eventsPage"

    Component.onCompleted: { Events.setScope("all"); Events.setActive(true); Events.refreshList() }
    Component.onDestruction: Events.setActive(false)

    PageHeader {
        title: "Events"
        description: "Camera events (motion, analytics…), marked events and video loss, newest first. Click one to play it."
        AppButton { text: "Refresh"; variant: "outline"; iconName: "refresh-cw"; onClicked: Events.refreshList() }
    }

    EventsPanel {
        Layout.fillWidth: true
        allCameras: true
        maxListHeight: 0
        onOpened: row => Router.go("playback", 0, { camera: row.camera_id, t: row.seekMs })
    }
}
