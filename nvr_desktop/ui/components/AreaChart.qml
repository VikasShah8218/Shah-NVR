import QtQuick
import "../theme"

// Small time-series area chart (port of ResourceCharts.tsx, recharts AreaChart).
// points: [{t: epochMs, <key>: number|null, ...}]   series: [{key, color, label}]
Canvas {
    id: chart

    property var points: []
    property var series: []
    property var yMax: null // fixed max (e.g. 100 for %), or null to fit the data
    property string unit: ""

    readonly property int leftPad: 36
    readonly property int bottomPad: 18

    onPointsChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    function maxValue() {
        if (yMax !== null)
            return yMax
        let m = 0
        for (const p of points)
            for (const s of series)
                if (p[s.key] !== null && p[s.key] !== undefined)
                    m = Math.max(m, p[s.key])
        return m > 0 ? m * 1.15 : 1
    }

    function clock(t) {
        const d = new Date(t)
        return d.toTimeString().slice(0, 8)
    }

    onPaint: {
        const ctx = getContext("2d")
        ctx.reset()
        const w = width - leftPad - 8
        const h = height - bottomPad - 6
        if (points.length < 2) {
            ctx.fillStyle = Theme.mutedForeground
            ctx.font = "12px " + Theme.font
            ctx.textAlign = "center"
            ctx.fillText("Collecting data…", width / 2, height / 2)
            return
        }
        const t0 = points[0].t
        const t1 = points[points.length - 1].t
        const top = maxValue()
        const x = t => leftPad + (t - t0) / Math.max(1, t1 - t0) * w
        const y = v => 6 + h - (v / top) * h

        // grid + y labels
        ctx.strokeStyle = Theme.alpha(Theme.border, 0.5)
        ctx.fillStyle = Theme.mutedForeground
        ctx.font = "11px " + Theme.font
        ctx.textAlign = "right"
        ctx.lineWidth = 1
        for (let i = 0; i <= 4; i++) {
            const v = top * i / 4
            const yy = y(v)
            ctx.beginPath(); ctx.moveTo(leftPad, yy); ctx.lineTo(leftPad + w, yy); ctx.stroke()
            ctx.fillText(v >= 10 ? Math.round(v) : v.toFixed(1), leftPad - 6, yy + 4)
        }
        // x labels
        ctx.textAlign = "center"
        for (let i = 0; i <= 3; i++) {
            const t = t0 + (t1 - t0) * i / 3
            ctx.fillText(clock(t), Math.min(Math.max(x(t), leftPad + 24), leftPad + w - 24), height - 4)
        }
        // series
        for (const s of series) {
            ctx.beginPath()
            let started = false
            for (const p of points) {
                const v = p[s.key]
                if (v === null || v === undefined) continue
                if (!started) { ctx.moveTo(x(p.t), y(v)); started = true } else ctx.lineTo(x(p.t), y(v))
            }
            if (!started) continue
            ctx.strokeStyle = s.color
            ctx.lineWidth = 2
            ctx.stroke()
            ctx.lineTo(x(t1), y(0))
            ctx.lineTo(x(t0), y(0))
            ctx.closePath()
            ctx.fillStyle = Theme.alpha(Qt.color(s.color), 0.13)
            ctx.fill()
        }
    }
}
