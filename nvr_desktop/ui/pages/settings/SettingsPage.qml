import QtQuick
import QtQuick.Layouts
import App
import "../../theme"
import "../../components"

// Port of nvr_client/src/features/settings/SettingsPage.tsx (+ desktop: hardware decoding).
PageScroll {
    id: root

    PageHeader { title: "Settings"; description: "Stored on this computer only." }

    Card {
        Layout.fillWidth: true
        Layout.maximumWidth: 820
        padding: 24
        spacing: 12

        AppText { text: "Central manager"; font.pixelSize: Theme.textLg; font.weight: Font.Medium }
        AppText {
            text: "All data and actions go through this API. Media nodes are reached via the addresses they register."
            variant: "muted"
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
            Layout.fillWidth: true
        }
        AppText { text: "API URL"; font.weight: Font.Medium }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            AppInput {
                id: urlField
                text: Prefs.centralUrl
                placeholderText: "http://192.168.1.3:8000"
                Layout.fillWidth: true
                onAccepted: SettingsPage.saveCentralUrl(text)
            }
            AppButton {
                text: "Test"
                variant: "outline"
                enabled: SettingsPage.testState !== "testing"
                onClicked: SettingsPage.testConnection(urlField.text)
            }
            AppButton {
                text: "Save"
                enabled: urlField.text.replace(/\/+$/, "") !== Prefs.centralUrl
                onClicked: SettingsPage.saveCentralUrl(urlField.text)
            }
        }
        RowLayout {
            visible: SettingsPage.testState !== "idle"
            spacing: 8
            Spinner { visible: SettingsPage.testState === "testing" }
            Icon {
                visible: SettingsPage.testState === "ok" || SettingsPage.testState === "fail"
                name: SettingsPage.testState === "ok" ? "circle-check-big" : "circle-x"
                color: SettingsPage.testState === "ok" ? Theme.success : Theme.danger
            }
            AppText {
                text: SettingsPage.testState === "testing" ? "Testing…" : SettingsPage.testText
                color: SettingsPage.testState === "ok" ? Theme.success : SettingsPage.testState === "fail" ? Theme.danger : Theme.mutedForeground
            }
        }
    }

    Card {
        Layout.fillWidth: true
        Layout.maximumWidth: 820
        padding: 24
        spacing: 20

        AppText { text: "Display"; font.pixelSize: Theme.textLg; font.weight: Font.Medium }

        SettingRow {
            title: "Refresh interval"
            hint: "How often lists and statuses are refreshed."
            AppSelect {
                implicitWidth: 160
                options: [2, 5, 10, 30].map(s => ({ value: s, label: s + " seconds" }))
                value: Prefs.pollSeconds
                onPicked: v => Prefs.pollSeconds = v
            }
        }
        SettingRow {
            title: "Media-node route"
            hint: "Per workstation. Auto uses LAN when reachable, otherwise the node's configured public address. This choice is not shared with other users."
            AppSelect {
                implicitWidth: 220
                options: [
                    { value: "auto", label: "Auto (recommended)" },
                    { value: "lan", label: "Always LAN" },
                    { value: "public", label: "Prefer public" }
                ]
                value: Prefs.nodeAccess
                onPicked: v => Prefs.nodeAccess = v
            }
        }
        SettingRow {
            title: "Live video protocol"
            hint: "RTSP has the lowest delay; LL-HLS works through more networks. Auto tries RTSP first."
            AppSelect {
                implicitWidth: 220
                options: [
                    { value: "auto", label: "Auto (RTSP → LL-HLS)" },
                    { value: "rtsp", label: "RTSP only" },
                    { value: "hls", label: "LL-HLS only" }
                ]
                value: Prefs.liveProtocol
                onPicked: v => Prefs.liveProtocol = v
            }
        }
        SettingRow {
            title: "HLS stability buffer"
            hint: "More buffering absorbs network jitter but increases LL-HLS live delay. RTSP is unaffected."
            AppSelect {
                implicitWidth: 220
                options: [
                    { value: 2, label: "2 seconds" },
                    { value: 3, label: "3 seconds" },
                    { value: 5, label: "5 seconds (recommended)" },
                    { value: 8, label: "8 seconds" },
                    { value: 10, label: "10 seconds" }
                ]
                value: Prefs.hlsBufferSeconds
                onPicked: v => Prefs.hlsBufferSeconds = v
            }
        }
        SettingRow {
            title: "Video rendering"
            hint: "CPU draws video without any graphics card (like a web browser) and is the lightest choice for big grids "
                + "on PCs without a GPU. Auto uses the GPU when a real graphics driver is present. "
                + "Active now: " + Prefs.activeRenderMode.toUpperCase()
                + (Prefs.renderMode !== Prefs.renderModeAtStart ? " · restart the app to apply the change" : "")
            AppSelect {
                implicitWidth: 220
                options: [
                    { value: "auto", label: "Auto (recommended)" },
                    { value: "cpu", label: "CPU" },
                    { value: "gpu", label: "GPU (OpenGL)" }
                ]
                value: Prefs.renderMode
                onPicked: v => Prefs.renderMode = v
            }
        }
        SettingRow {
            title: "Hardware decoding"
            hint: Prefs.activeRenderMode === "cpu"
                ? "CPU rendering decodes on the processor; this applies in GPU rendering only."
                : "Decode video on the GPU (NVIDIA / Intel / AMD). Auto picks the best safe decoder and falls back to the CPU."
            AppSelect {
                enabled: Prefs.activeRenderMode !== "cpu"
                implicitWidth: 220
                options: [
                    { value: "auto-safe", label: "Auto (recommended)" },
                    { value: "nvdec", label: "NVIDIA NVDEC" },
                    { value: "d3d11va-copy", label: "Direct3D 11 (copy)" },
                    { value: "nvdec-copy", label: "NVIDIA NVDEC (copy)" },
                    { value: "no", label: "Off (CPU only)" }
                ]
                value: Prefs.hwdec
                onPicked: v => Prefs.hwdec = v
            }
        }
    }

    AppButton {
        text: "Reset to defaults"
        variant: "outline"
        iconName: "rotate-ccw"
        onClicked: {
            Prefs.reset()
            urlField.text = Prefs.centralUrl
        }
    }

    component SettingRow: RowLayout {
        property string title: ""
        property string hint: ""
        default property alias control: slot.data
        Layout.fillWidth: true
        spacing: 16
        ColumnLayout {
            spacing: 2
            Layout.fillWidth: true
            AppText { text: title; font.weight: Font.Medium }
            AppText { text: hint; variant: "small"; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true }
        }
        Row { id: slot }
    }
}
