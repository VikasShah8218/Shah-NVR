import QtQuick
import QtQuick.Layouts
import "../theme"

// Summary tile: tinted icon box + label, big value, hint (port of KpiCard in common.tsx).
Rectangle {
    id: kpi

    property string iconName: "gauge"
    property string label: ""
    property string value: ""
    property string hint: ""
    property string tone: "info" // info | success | warning | danger

    implicitHeight: 76
    implicitWidth: 200
    color: Theme.card
    radius: Theme.radiusLg
    border.color: Theme.border

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        spacing: 12
        Rectangle {
            width: 40
            height: 40
            radius: Theme.radius
            color: Theme.alpha(Theme.toneColor(kpi.tone), 0.12)
            Icon {
                anchors.centerIn: parent
                name: kpi.iconName
                size: 20
                color: Theme.toneColor(kpi.tone)
            }
        }
        ColumnLayout {
            spacing: 1
            Layout.fillWidth: true
            AppText { text: kpi.label; variant: "small"; Layout.fillWidth: true }
            AppText { text: kpi.value; font.pixelSize: Theme.textXl; font.weight: Font.DemiBold; Layout.fillWidth: true }
            AppText { visible: kpi.hint !== ""; text: kpi.hint; variant: "small"; Layout.fillWidth: true }
        }
    }
}
