import { DatabaseBackup, Loader2, RefreshCw } from "lucide-react"
import { useEffect, useState } from "react"
import { useBackfill, useBackfillJobs, useCreateBackfillJob, useProbeBackfill, useUpdateBackfill } from "@/api/queries"
import type { Camera } from "@/api/types"
import { ErrorState, Field } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Progress } from "@/components/ui/progress"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { fmtDateTime } from "@/lib/time"

const ACTIVE = new Set(["QUEUED", "CLAIMED", "DOWNLOADING", "INDEXING"])

export function BackfillTab({ camera: c, active }: { camera: Camera; active: boolean }) {
  const config = useBackfill(c.id, active)
  const jobs = useBackfillJobs(c.id, active)
  const probe = useProbeBackfill()
  const update = useUpdateBackfill()
  const create = useCreateBackfillJob()
  const [mode, setMode] = useState<"off" | "manual" | "automatic">("off")
  const [profile, setProfile] = useState("main")
  const [recordingToken, setRecordingToken] = useState("")
  const [start, setStart] = useState("")
  const [end, setEnd] = useState("")

  useEffect(() => {
    if (config.data) {
      setMode(config.data.mode)
      setProfile(config.data.profile)
      setRecordingToken(config.data.recording_token ?? "")
    }
  }, [config.data])

  const save = () => update.mutate({ cameraId: c.id, body: { mode, profile, recording_token: recordingToken || null } })
  const queue = () => create.mutate({
    cameraId: c.id,
    body: { start_time: new Date(start).toISOString(), end_time: new Date(end).toISOString(), profile },
  })
  const d = config.data

  return (
    <div className="space-y-4">
      {(config.error || jobs.error) && <ErrorState error={config.error ?? jobs.error!} />}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <DatabaseBackup className="size-4" /> Camera SD storage
          </CardTitle>
          <Button variant="outline" size="sm" onClick={() => probe.mutate(c.id)} disabled={probe.isPending}>
            {probe.isPending ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
            Test camera storage
          </Button>
        </CardHeader>
        <CardContent className="grid gap-5 lg:grid-cols-2">
          <div>
            <Field label="Profile G capability">{d?.capability ?? "unknown"}</Field>
            <Field label="Camera recording">{d?.recording_token ?? "Not selected"}</Field>
            <Field label="Stored from">{d?.earliest ? fmtDateTime(new Date(d.earliest)) : "—"}</Field>
            <Field label="Stored until">{d?.latest ? fmtDateTime(new Date(d.latest)) : "—"}</Field>
            <Field label="Last tested">{d?.checked_at ? fmtDateTime(new Date(d.checked_at)) : "Never"}</Field>
            {d?.error && <p className="mt-2 text-sm text-danger">{d.error}</p>}
          </div>
          <div className="space-y-3">
            <div className="grid gap-1.5">
              <Label htmlFor="backfill-mode">Recovery mode</Label>
              <select id="backfill-mode" className="h-9 rounded-md border bg-background px-3 text-sm" value={mode}
                onChange={(event) => setMode(event.target.value as typeof mode)}>
                <option value="off">Off</option>
                <option value="manual" disabled={d?.capability !== "supported"}>Manual</option>
                <option value="automatic" disabled={d?.capability !== "supported"}>Automatic</option>
              </select>
            </div>
            {(probe.data?.recordings.length ?? 0) > 1 && (
              <div className="grid gap-1.5">
                <Label htmlFor="backfill-recording">Camera recording</Label>
                <select id="backfill-recording" className="h-9 rounded-md border bg-background px-3 text-sm"
                  value={recordingToken} onChange={(event) => setRecordingToken(event.target.value)}>
                  <option value="">Select a recording</option>
                  {probe.data!.recordings.map((recording) => (
                    <option key={recording.token} value={recording.token} disabled={!recording.replay_available}>
                      {recording.source_id ?? recording.token}{recording.replay_available ? "" : " (not replayable)"}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div className="grid gap-1.5">
              <Label htmlFor="backfill-profile">Shah-NVR recording profile</Label>
              <select id="backfill-profile" className="h-9 rounded-md border bg-background px-3 text-sm" value={profile}
                onChange={(event) => setProfile(event.target.value)}>
                {c.streams.filter((stream) => stream.record).map((stream) => (
                  <option key={stream.profile} value={stream.profile}>{stream.profile}</option>
                ))}
              </select>
            </div>
            <Button onClick={save} disabled={!d || update.isPending}>{update.isPending && <Loader2 className="size-4 animate-spin" />} Save</Button>
            <p className="text-xs text-muted-foreground">
              Manual mode imports requested gaps. Automatic mode checks the latest 24 hours and recovers one bounded gap at a time.
              Video is copied without transcoding and stored under normal retention rules.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">Request manual backfill</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5"><Label htmlFor="backfill-start">Start</Label><Input id="backfill-start" type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} /></div>
            <div className="grid gap-1.5"><Label htmlFor="backfill-end">End</Label><Input id="backfill-end" type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} /></div>
          </div>
          <Button onClick={queue} disabled={d?.mode === "off" || create.isPending || !start || !end}>
            {create.isPending && <Loader2 className="size-4 animate-spin" />} Queue missing interval
          </Button>
          <p className="text-xs text-muted-foreground">Each request is limited to 15 minutes and must be at least five minutes old.</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">Backfill jobs</CardTitle></CardHeader>
        <CardContent>
          {!jobs.data?.length ? <p className="text-sm text-muted-foreground">No jobs yet.</p> : (
            <Table>
              <TableHeader><TableRow><TableHead>Range</TableHead><TableHead>Status</TableHead><TableHead>Progress</TableHead><TableHead>Imported</TableHead><TableHead>Detail</TableHead></TableRow></TableHeader>
              <TableBody>{jobs.data.map((job) => (
                <TableRow key={job.id}>
                  <TableCell className="text-xs">{fmtDateTime(new Date(job.start_time))}<br />to {fmtDateTime(new Date(job.end_time))}</TableCell>
                  <TableCell className={job.state === "FAILED" ? "text-danger" : ACTIVE.has(job.state) ? "text-warning" : "text-success"}>{job.state}</TableCell>
                  <TableCell className="min-w-32"><Progress value={job.progress_percent} /><span className="text-xs text-muted-foreground">{job.progress_percent.toFixed(0)}%</span></TableCell>
                  <TableCell>{job.imported_seconds ? `${job.imported_seconds.toFixed(1)} s` : "—"}</TableCell>
                  <TableCell className="max-w-64 text-xs text-muted-foreground">{job.error_message ?? `Attempt ${job.attempt_count}`}</TableCell>
                </TableRow>
              ))}</TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
