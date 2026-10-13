import QtQuick
import QtQuick.Layouts
import "../theme"

// Spinner + label (port of Loading in common.tsx).
RowLayout {
    property string text: "Loading…"

    Layout.fillWidth: true
    Layout.topMargin: 32
    Layout.bottomMargin: 32
    spacing: 8

    Item { Layout.fillWidth: true }
    Spinner {}
    AppText { text: parent.text; variant: "muted" }
    Item { Layout.fillWidth: true }
}
