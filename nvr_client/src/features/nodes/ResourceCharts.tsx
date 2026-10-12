import { useEffect, useState } from "react"
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import type { MediaNode } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { fmtTime } from "@/lib/time"
import { nodeResources } from "./nodeUtils"

interface Point {
  t: number
  cpu: number | null
  mem: number | null
  rx: number | null
  tx: number | null
}

const MAX_POINTS = 240 // ~12 min at 3 s polling
// Kept per node at module level, so the history survives navigating away and back.
const history = new Map<number, Point[]>()

/** Collect a point every time fresh node data arrives. */
export function useNodeHistory(node: MediaNode | undefined, updatedAt: number): Point[] {
  const [points, setPoints] = useState<Point[]>(() => (node ? (history.get(node.id) ?? []) : []))
  useEffect(() => {
    if (!node || !updatedAt) return
    const r = nodeResources(node)
    const list = history.get(node.id) ?? []
    if (list.length && list[list.length - 1].t === updatedAt) return
    const next = [...list, { t: updatedAt, cpu: r.cpuPercent, mem: r.memPercent, rx: r.netRx, tx: r.netTx }].slice(-MAX_POINTS)
    history.set(node.id, next)
    setPoints(next)
  }, [node, updatedAt])
  return points
}

const AXIS = { stroke: "var(--muted-foreground)", fontSize: 11, tickLine: false, axisLine: false }
const TOOLTIP = {
  contentStyle: { background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 },
  labelFormatter: (t: unknown) => fmtTime(Number(t)),
}

export function ResourceCharts({ points }: { points: Point[] }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ChartCard title="CPU & RAM (%)" empty={points.length < 2}>
        <AreaChart data={points} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeOpacity={0.5} vertical={false} />
          <XAxis dataKey="t" tickFormatter={(t) => fmtTime(t)} minTickGap={40} {...AXIS} />
          <YAxis domain={[0, 100]} {...AXIS} />
          <Tooltip {...TOOLTIP} formatter={(v) => `${Number(v).toFixed(1)}%`} />
          <Area type="monotone" dataKey="cpu" name="CPU" stroke="var(--chart-1)" fill="var(--chart-1)" fillOpacity={0.15} strokeWidth={2} isAnimationActive={false} />
          <Area type="monotone" dataKey="mem" name="RAM" stroke="var(--chart-4)" fill="var(--chart-4)" fillOpacity={0.1} strokeWidth={2} isAnimationActive={false} />
        </AreaChart>
      </ChartCard>
      <ChartCard title="Network (Mb/s)" empty={points.length < 2}>
        <AreaChart data={points} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeOpacity={0.5} vertical={false} />
          <XAxis dataKey="t" tickFormatter={(t) => fmtTime(t)} minTickGap={40} {...AXIS} />
          <YAxis {...AXIS} />
          <Tooltip {...TOOLTIP} formatter={(v) => `${Number(v).toFixed(2)} Mb/s`} />
          <Area type="monotone" dataKey="rx" name="In" stroke="var(--chart-2)" fill="var(--chart-2)" fillOpacity={0.15} strokeWidth={2} isAnimationActive={false} />
          <Area type="monotone" dataKey="tx" name="Out" stroke="var(--chart-3)" fill="var(--chart-3)" fillOpacity={0.1} strokeWidth={2} isAnimationActive={false} />
        </AreaChart>
      </ChartCard>
    </div>
  )
}

function ChartCard({ title, empty, children }: { title: string; empty: boolean; children: React.ReactElement }) {
  return (
    <Card className="gap-2 pb-3">
      <CardHeader className="pb-0">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
      </CardHeader>
      <CardContent className="h-48 px-3">
        {empty ? (
          <div className="grid h-full place-items-center text-xs text-muted-foreground">Collecting data…</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            {children}
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  )
}
