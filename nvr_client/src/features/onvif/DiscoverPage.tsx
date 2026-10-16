import { Loader2, Plus, Radar, ScanSearch } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router"
import { useNodes, useOnvifDiscover } from "@/api/queries"
import type { OnvifDiscovered } from "@/api/types"
import { EmptyState, ErrorState, PageHeader } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { onvifErrorText, profileLabels } from "@/lib/onvif"
import { AddOnvifSheet } from "./AddOnvifSheet"

const ALL = "all"
const ONLINE = ["READY", "ACTIVE", "DRAINING", "CORDONED"]

/** Find ONVIF cameras on the media nodes' LANs and add them without typing RTSP URLs. */
export function DiscoverPage() {
  const nodes = useNodes()
  const discover = useOnvifDiscover()
  const [nodeId, setNodeId] = useState(ALL)
  const [found, setFound] = useState<OnvifDiscovered[] | null>(null)
  const [manual, setManual] = useState<OnvifDiscovered[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [adding, setAdding] = useState<OnvifDiscovered[] | null>(null)
  const [address, setAddress] = useState("")

  const online = (nodes.data ?? []).filter((n) => ONLINE.includes(n.state))
  const rows = [...manual.filter((m) => !(found ?? []).some((f) => f.host === m.host && f.port === m.port)), ...(found ?? [])]
  const selectable = rows.filter((r) => !r.camera_id)
  const picked = rows.filter((r) => selected.has(r.endpoint))

  const scan = () =>
    discover.mutate(
      { node_id: nodeId === ALL ? null : Number(nodeId) },
      {
        onSuccess: (list) => {
          setFound(list)
          setSelected(new Set(list.filter((d) => !d.camera_id).map((d) => d.endpoint)))
        },
      },
    )

  /** Cameras on another subnet do not answer discovery: add them by address. */
  function addByAddress() {
    const m = address.trim().match(/^(?:https?:\/\/)?([^/:\s]+)(?::(\d+))?/)
    const node = nodeId === ALL ? online[0] : online.find((n) => String(n.id) === nodeId)
    if (!m || !node) return
    const port = Number(m[2] ?? 80)
    const dev: OnvifDiscovered = {
      endpoint: `manual:${m[1]}:${port}`,
      host: m[1],
      port,
      xaddr: `http://${m[1]}:${port}/onvif/device_service`,
      name: null,
      hardware: null,
      location: null,
      mac: null,
      profiles: [],
      node_id: node.id,
      node_name: node.name,
      camera_id: null,
      camera_name: null,
    }
    setManual((l) => [dev, ...l.filter((x) => x.endpoint !== dev.endpoint)])
    setSelected((s) => new Set(s).add(dev.endpoint))
    setAddress("")
  }

  const toggle = (endpoint: string) =>
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(endpoint)) n.delete(endpoint)
      else n.add(endpoint)
      return n
    })

  return (
    <div className="pb-16">
      <PageHeader
        title="Discover cameras"
        description="Find ONVIF cameras on the media nodes' networks and add them with their streams filled in."
        actions={
          <>
            <Select value={nodeId} onValueChange={setNodeId}>
              <SelectTrigger className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All online nodes</SelectItem>
                {online.map((n) => (
                  <SelectItem key={n.id} value={String(n.id)}>
                    {n.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button onClick={scan} disabled={discover.isPending || online.length === 0}>
              {discover.isPending ? <Loader2 className="size-4 animate-spin" /> : <Radar className="size-4" />}
              {discover.isPending ? "Scanning…" : "Scan network"}
            </Button>
          </>
        }
      />

      {online.length === 0 && nodes.data && <ErrorState className="mb-4" error="No media node is online: discovery runs on a node." />}
      {discover.error && <ErrorState className="mb-4" error={onvifErrorText(discover.error)} />}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input
          className="w-80"
          placeholder="Not listed? Camera IP, e.g. 192.168.1.64:80"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addByAddress()}
        />
        <Button variant="outline" onClick={addByAddress} disabled={!address.trim() || online.length === 0}>
          <Plus className="size-4" /> Add address
        </Button>
        <span className="text-xs text-muted-foreground">Discovery only reaches cameras on the node's own subnet.</span>
      </div>

      {rows.length === 0 ? (
        <EmptyState icon={ScanSearch} title={found ? "No ONVIF cameras answered" : "Scan to find cameras"}>
          {found
            ? "Check that ONVIF is enabled on the cameras and that they are on the same network as the media node."
            : "The media node sends a WS-Discovery probe on its LAN; cameras answer within a few seconds."}
        </EmptyState>
      ) : (
        <Card className="py-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-10 pl-4">
                  <input
                    type="checkbox"
                    className="size-4 accent-primary"
                    aria-label="Select all new cameras"
                    checked={selectable.length > 0 && selectable.every((r) => selected.has(r.endpoint))}
                    onChange={(e) => setSelected(new Set(e.target.checked ? selectable.map((r) => r.endpoint) : []))}
                  />
                </TableHead>
                <TableHead>Address</TableHead>
                <TableHead>Device</TableHead>
                <TableHead>ONVIF profiles</TableHead>
                <TableHead>Found by</TableHead>
                <TableHead>In Shah-NVR</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((d) => (
                <TableRow key={d.endpoint} className={d.camera_id ? "opacity-70" : undefined}>
                  <TableCell className="pl-4">
                    <input
                      type="checkbox"
                      className="size-4 accent-primary"
                      disabled={!!d.camera_id}
                      checked={selected.has(d.endpoint)}
                      onChange={() => toggle(d.endpoint)}
                      aria-label={`Select ${d.host}`}
                    />
                  </TableCell>
                  <TableCell className="font-mono text-sm">
                    {d.host}
                    {d.port !== 80 && <span className="text-muted-foreground">:{d.port}</span>}
                  </TableCell>
                  <TableCell>
                    <div>{d.name || d.hardware || (d.endpoint.startsWith("manual:") ? "Added by address" : "ONVIF device")}</div>
                    {d.name && d.hardware && d.hardware !== d.name && <div className="text-xs text-muted-foreground">{d.hardware}</div>}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      {profileLabels(d.profiles).map((p) => (
                        <span key={p} className="rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium" title={`ONVIF Profile ${p}`}>
                          {p}
                        </span>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{d.node_name}</TableCell>
                  <TableCell>
                    {d.camera_id ? (
                      <Link to={`/cameras/${d.camera_id}`} className="text-sm text-primary hover:underline">
                        {d.camera_name}
                      </Link>
                    ) : (
                      <span className="text-sm text-muted-foreground">New</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      {picked.length > 0 && (
        <div className="fixed right-6 bottom-6 z-20 flex items-center gap-3 rounded-xl border bg-card px-4 py-3 shadow-lg">
          <span className="text-sm">
            <b>{picked.length}</b> selected
          </span>
          <Button onClick={() => setAdding(picked)}>
            <Plus className="size-4" /> Add {picked.length > 1 ? `${picked.length} cameras` : "camera"}…
          </Button>
        </div>
      )}

      {adding && (
        <AddOnvifSheet
          devices={adding}
          open
          onOpenChange={(o) => {
            if (!o) {
              setAdding(null)
              setSelected(new Set())
              if (found) scan() // refresh "In Shah-NVR"
            }
          }}
        />
      )}
    </div>
  )
}
