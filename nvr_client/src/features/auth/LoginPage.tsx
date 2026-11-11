import { Loader2, LogIn, Server, ServerOff } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { getEndedReason, login } from "@/lib/auth/session"
import { PRODUCT_LOGO, PRODUCT_NAME } from "@/lib/branding"
import { useSettings } from "@/lib/settings"

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh place-items-center bg-background p-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <img src={PRODUCT_LOGO} alt="" className="size-14 object-contain" />
          <h1 className="text-xl font-semibold tracking-tight">{PRODUCT_NAME}</h1>
        </div>
        {children}
      </div>
    </div>
  )
}

/** The central address can be changed here (a wrong address must not lock the user out of the app). */
function ServerField() {
  const { settings, update } = useSettings()
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState(settings.centralUrl)
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}
        className="mx-auto flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
        <Server className="size-3.5" /> {settings.centralUrl}
      </button>
    )
  }
  return (
    <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); update({ centralUrl: value.trim() }); setOpen(false) }}>
      <Input aria-label="Central server address" value={value} onChange={(e) => setValue(e.target.value)} placeholder="http://192.168.1.3:8000" />
      <Button type="submit" variant="outline">Use</Button>
    </form>
  )
}

export function LoginPage() {
  const { settings } = useSettings()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [remember, setRemember] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(() => getEndedReason())

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(settings.centralUrl, username.trim(), password, remember)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setPassword("")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Shell>
      <Card className="gap-4 p-6">
        <div>
          <h2 className="text-lg font-semibold">Sign in</h2>
          <p className="text-sm text-muted-foreground">Use your organisation account.</p>
        </div>
        <form className="space-y-4" onSubmit={submit}>
          <div className="space-y-1.5">
            <Label htmlFor="login-user">Username</Label>
            <Input id="login-user" autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="login-pass">Password</Label>
            <Input id="login-pass" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={remember} onCheckedChange={setRemember} /> Keep me signed in on this device
          </label>
          {error && <p role="alert" className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm">{error}</p>}
          <Button type="submit" className="w-full" disabled={busy || !username.trim() || !password}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <LogIn className="size-4" />} Sign in
          </Button>
        </form>
      </Card>
      <ServerField />
    </Shell>
  )
}

export function ServerUnreachable({ message, onRetry }: { message: string; onRetry: () => void }) {
  const { settings } = useSettings()
  return (
    <Shell>
      <Card className="gap-3 p-6 text-center">
        <ServerOff className="mx-auto size-8 text-muted-foreground" />
        <h2 className="text-lg font-semibold">Central is not reachable</h2>
        <p className="text-sm text-muted-foreground">{settings.centralUrl} ({message})</p>
        <Button onClick={onRetry}>Try again</Button>
      </Card>
      <ServerField />
    </Shell>
  )
}
