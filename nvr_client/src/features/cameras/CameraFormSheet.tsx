import { Info, Plus, Trash2 } from "lucide-react"
import { useState } from "react"
import { useCreateCamera, useSyncStreams, useUpdateCamera } from "@/api/queries"
import type { Camera, StreamIn } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"

interface StreamDraft {
  key: number
  profile: string
  source_url: string
  record: boolean
  rtsp_transport: "tcp" | "udp" | "automatic"
  existing: boolean
}

const EXAMPLES = [
  ["Axis", "rtsp://IP:554/axis-media/media.amp?videocodec=h264&resolution=1920x1080"],
  ["Hikvision", "rtsp://IP:554/Streaming/Channels/101  (sub: 102)"],
  ["Dahua", "rtsp://IP:554/cam/realmonitor?channel=1&subtype=0  (sub: subtype=1)"],
]

let keySeq = 0
const draftFromCamera = (c?: Camera): StreamDraft[] =>
  c
    ? c.streams.map((s) => ({
        key: keySeq++,
        profile: s.profile,
        source_url: s.source_url,
        record: s.record,
        rtsp_transport: s.rtsp_transport as StreamDraft["rtsp_transport"],
        existing: true,
      }))
    : [
        { key: keySeq++, profile: "main", source_url: "", record: true, rtsp_transport: "tcp", existing: false },
        { key: keySeq++, profile: "sub", source_url: "", record: false, rtsp_transport: "tcp", existing: false },
      ]

/** Add (camera undefined) or edit a camera. Mount it only while open so it starts fresh. */
export function CameraFormSheet({
  camera,
  open,
  onOpenChange,
}: {
  camera?: Camera
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const create = useCreateCamera()
  const update = useUpdateCamera()
  const syncStreams = useSyncStreams()

  const [name, setName] = useState(camera?.name ?? "")
  const [description, setDescription] = useState(camera?.description ?? "")
  const [username, setUsername] = useState(camera?.username ?? "")
  const [password, setPassword] = useState("")
  const [retention, setRetention] = useState(String(camera?.retention_days ?? 7))
  // null retention = keep recordings until storage is full
  const [untilFull, setUntilFull] = useState(camera ? camera.retention_days == null : false)
  const [enabled, setEnabled] = useState(camera?.enabled ?? true)
  const [streams, setStreams] = useState<StreamDraft[]>(() => draftFromCamera(camera))
  const [errors, setErrors] = useState<string[]>([])

  const setStream = (key: number, patch: Partial<StreamDraft>) =>
    setStreams((list) => list.map((s) => (s.key === key ? { ...s, ...patch } : s)))

  const validate = (): string[] => {
    const errs: string[] = []
    const used = streams.filter((s) => s.source_url.trim() || s.existing)
    if (!name.trim()) errs.push("Name is required.")
    if (!used.length) errs.push("Add at least one stream URL.")
    const profiles = used.map((s) => s.profile)
    if (new Set(profiles).size !== profiles.length) errs.push("Stream profiles must be unique.")
    for (const s of used) {
      if (!/^[a-z0-9_-]{1,32}$/.test(s.profile)) errs.push(`Profile "${s.profile}": use lowercase letters, digits, - or _.`)
      if (!/^(rtsps?|rtmp|srt|https?):\/\//i.test(s.source_url.trim())) errs.push(`Profile "${s.profile}": URL must start with rtsp://`)
    }
    const r = Number(retention)
    if (!untilFull && (!Number.isInteger(r) || r < 1)) errs.push("Retention must be a whole number of days (1 or more).")
    return errs
  }

  const submit = async () => {
    const errs = validate()
    setErrors(errs)
    if (errs.length) return
    const used = streams.filter((s) => s.source_url.trim() || s.existing)
    const toIn = (s: StreamDraft): StreamIn => ({
      profile: s.profile,
      source_url: s.source_url.trim(),
      record: s.record,
      rtsp_transport: s.rtsp_transport,
    })

    try {
      await save(used, toIn)
    } catch {
      return // the mutation hook already showed the server's error message
    }
    onOpenChange(false)
  }

  const save = async (used: StreamDraft[], toIn: (s: StreamDraft) => StreamIn) => {
    if (!camera) {
      await create.mutateAsync({
        name: name.trim(),
        description: description.trim() || null,
        username: username.trim() || null,
        password: password || null,
        retention_days: untilFull ? null : Number(retention),
        enabled,
        streams: used.map(toIn),
      })
    } else {
      await update.mutateAsync({
        id: camera.id,
        body: {
          name: name.trim(),
          description: description.trim() || null,
          username: username.trim() || null,
          retention_days: untilFull ? null : Number(retention),
          enabled,
          ...(password ? { password } : {}),
        },
      })
      const original = new Map(camera.streams.map((s) => [s.profile, s]))
      const keep = new Set(used.filter((s) => s.existing).map((s) => s.profile))
      await syncStreams.mutateAsync({
        id: camera.id,
        add: used.filter((s) => !s.existing).map(toIn),
        update: used
          .filter((s) => s.existing)
          .filter((s) => {
            const o = original.get(s.profile)!
            return o.source_url !== s.source_url.trim() || o.record !== s.record || o.rtsp_transport !== s.rtsp_transport
          })
          .map((s) => ({ profile: s.profile, body: { source_url: s.source_url.trim(), record: s.record, rtsp_transport: s.rtsp_transport } })),
        remove: camera.streams.map((s) => s.profile).filter((p) => !keep.has(p)),
      })
    }
  }

  const busy = create.isPending || update.isPending || syncStreams.isPending

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto pb-[env(safe-area-inset-bottom)] data-[side=right]:sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>{camera ? `Edit ${camera.name}` : "Add camera"}</SheetTitle>
          <SheetDescription>
            The scheduler assigns the camera to a media node within a few seconds; recorded streams start recording right away.
          </SheetDescription>
        </SheetHeader>

        <div className="grid gap-4 px-4">
          <div className="grid gap-1.5">
            <Label htmlFor="name">Name</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Gate camera" />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="desc">Description</Label>
            <Textarea id="desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional" />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="user">Username</Label>
              <Input id="user" autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="admin" />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="pass">Password</Label>
              <Input
                id="pass"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={camera?.has_password ? "•••••• (unchanged)" : ""}
              />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="ret">Keep recordings</Label>
            <div className="flex flex-col items-start gap-3 min-[420px]:flex-row min-[420px]:items-center">
              <div className="flex items-center gap-2">
                <Input
                  id="ret"
                  type="number"
                  min={1}
                  className="w-28"
                  disabled={untilFull}
                  value={retention}
                  onChange={(e) => setRetention(e.target.value)}
                />
                <span className={untilFull ? "text-sm text-muted-foreground" : "text-sm"}>days</span>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <Switch checked={untilFull} onCheckedChange={setUntilFull} /> Until storage is full
              </label>
            </div>
            <span className="text-xs text-muted-foreground">
              {untilFull
                ? "Recordings are never deleted by age; the oldest are replaced only when all storage is full."
                : "Days count back from the camera's latest recording, so a stopped camera keeps its history. When all storage is full the oldest recordings are always replaced."}
            </span>
          </div>
          <label className="flex items-center justify-between rounded-md border px-3 py-2.5 text-sm">
            <span>
              Camera enabled
              <span className="block text-xs text-muted-foreground">Off: the camera is not pulled; no live view, no new recording.</span>
            </span>
            <Switch checked={enabled} onCheckedChange={setEnabled} />
          </label>

          <Separator />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-medium">Streams</div>
              <div className="text-xs text-muted-foreground">Credentials are added to the URL automatically.</div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setStreams((l) => [...l, { key: keySeq++, profile: `stream${l.length + 1}`, source_url: "", record: false, rtsp_transport: "tcp", existing: false }])
              }
            >
              <Plus className="size-4" /> Add stream
            </Button>
          </div>

          {streams.map((s) => (
            <div key={s.key} className="space-y-2.5 rounded-lg border bg-muted/40 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  className="h-10 min-w-24 flex-1 sm:h-8 sm:w-32 sm:flex-none"
                  value={s.profile}
                  disabled={s.existing}
                  onChange={(e) => setStream(s.key, { profile: e.target.value.toLowerCase() })}
                  title="Profile name, e.g. main / sub"
                />
                <label className="flex items-center gap-2 text-xs">
                  <Switch checked={s.record} onCheckedChange={(v) => setStream(s.key, { record: v })} /> Record
                </label>
                <Select value={s.rtsp_transport} onValueChange={(v) => setStream(s.key, { rtsp_transport: v as StreamDraft["rtsp_transport"] })}>
                  <SelectTrigger size="sm" className="ml-auto w-28">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="tcp">TCP</SelectItem>
                    <SelectItem value="udp">UDP</SelectItem>
                    <SelectItem value="automatic">Auto</SelectItem>
                  </SelectContent>
                </Select>
                <Button variant="ghost" size="icon" className="size-8" onClick={() => setStreams((l) => l.filter((x) => x.key !== s.key))} title="Remove stream">
                  <Trash2 className="size-4" />
                </Button>
              </div>
              <Input
                className="font-mono text-xs"
                value={s.source_url}
                onChange={(e) => setStream(s.key, { source_url: e.target.value })}
                placeholder="rtsp://192.168.1.64:554/…"
              />
              <div className="text-[11px] text-muted-foreground">
                {s.record ? "Recorded continuously and available live." : "Live only: connects to the camera when someone watches."}
              </div>
            </div>
          ))}

          <div className="rounded-lg border border-info/30 bg-info/8 p-3 text-xs">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-info">
              <Info className="size-3.5" /> Common RTSP URLs
            </div>
            {EXAMPLES.map(([brand, url]) => (
              <div key={brand} className="flex gap-2">
                <span className="w-20 shrink-0 text-muted-foreground">{brand}</span>
                <code className="break-all">{url}</code>
              </div>
            ))}
          </div>

          {errors.length > 0 && (
            <ul className="list-inside list-disc rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
        </div>

        <SheetFooter className="sticky bottom-0 border-t bg-popover pb-[calc(1rem+env(safe-area-inset-bottom))]">
          <Button onClick={submit} disabled={busy}>
            {camera ? "Save changes" : "Add camera"}
          </Button>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
