import QtQuick
import "../theme"

// Text with theme defaults. variant: body | muted | small | title | heading | mono
Text {
    property string variant: "body"

    color: variant === "muted" || variant === "small" ? Theme.mutedForeground : Theme.foreground
    font.family: variant === "mono" ? Theme.mono : Theme.font
    font.pixelSize: ({ title: Theme.textXl, heading: Theme.textLg, small: Theme.textXs, mono: Theme.textXs })[variant] ?? Theme.textSm
    font.weight: variant === "title" ? Font.DemiBold : variant === "heading" ? Font.Medium : Font.Normal
    elide: Text.ElideRight
    textFormat: Text.PlainText
    verticalAlignment: Text.AlignVCenter
}
