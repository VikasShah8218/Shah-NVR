import { Copy, Pause, Play, Search } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { useNodeLogs } from "@/api/queries"
import { ErrorState } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { cn } from "@/lib/utils"

type Level = "all" | "warn" | "error"

// Agent lines: "... INFO    node.x: msg"; MediaMTX lines: "2026/10/12 14:46:36 INF [path ...] msg"
const isError = (l: string) => /\b(ERROR|CRITICAL|ERR)\b|Traceback/.test(l)
const isWarn = (l: string) => /\b(WARNING|WAR)\b/.test(l)

export function LogViewer({ apiUrl }: { apiUrl: string }) {
  const [source, setSource] = useState<"agent" | "mediamtx">("agent")
  const [paused, setPaused] = useState(false)
  const [level, setLevel] = useState<Level>("all")
  const [search, setSearch] = useState("")
  const logs = useNodeLogs(apiUrl, source, paused)
  const boxRef = useRef<HTMLDivElement>(null)

  const lines = useMemo(() => {
    const q = search.toLowerCase()
    return (logs.data?.lines ?? []).filter(
      (l) =>
        (level === "all" || (level === "error" ? isError(l) : isError(l) || isWarn(l))) &&
        (!q || l.toLowerCase().includes(q)),
    )
  }, [logs.data, level, search])

  useEffect(() => {
    if (!paused && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight
  }, [lines, paused])

  const copy = () => {
    navigator.clipboard
      .writeText(lines.join("\n"))
      .then(() => toast.success(`Copied ${lines.length} lines`))
      .catch(() => toast.error("Clipboard not available"))
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <ToggleGroup type="single" variant="outline" size="sm" value={source} onValueChange={(v) => v && setSource(v as typeof source)}>
          <ToggleGroupItem value="agent">Agent</ToggleGroupItem>
          <ToggleGroupItem value="mediamtx">MediaMTX</ToggleGroupItem>
        </ToggleGroup>
        <ToggleGroup type="single" variant="outline" size="sm" value={level} onValueChange={(v) => v && setLevel(v as Level)}>
          <ToggleGroupItem value="all">All</ToggleGroupItem>
          <ToggleGroupItem value="warn">Warnings+</ToggleGroupItem>
          <ToggleGroupItem value="error">Errors</ToggleGroupItem>
        </ToggleGroup>
        <div className="relative ml-auto w-56">
          <Search className="absolute top-2 left-2.5 size-4 text-muted-foreground" />
          <Input className="h-8 pl-8" placeholder="Filter…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <Button variant="outline" size="sm" onClick={() => setPaused((p) => !p)}>
          {paused ? <Play className="size-4" /> : <Pause className="size-4" />} {paused ? "Resume" : "Pause"}
        </Button>
        <Button variant="outline" size="sm" onClick={copy}>
          <Copy className="size-4" /> Copy
        </Button>
      </div>
      {logs.error && <ErrorState error={logs.error} />}
      <div
        ref={boxRef}
        className="h-[28rem] overflow-auto rounded-lg border bg-video p-3 font-mono text-[12px] leading-5"
      >
        {lines.length === 0 ? (
          <div className="text-muted-foreground">{logs.isLoading ? "Loading…" : "No log lines."}</div>
        ) : (
          lines.map((l, i) => (
            <div key={i} className={cn("whitespace-pre-wrap break-all", isError(l) ? "text-danger" : isWarn(l) ? "text-warning" : "text-foreground/85")}>
              {l}
            </div>
          ))
        )}
      </div>
      <div className="text-xs text-muted-foreground">
        {lines.length} lines {paused ? "· paused" : "· refreshing every 3 s"}
      </div>
    </div>
  )
}
