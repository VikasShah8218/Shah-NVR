import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react"
import { centralClient, unwrap } from "@/api/client"
import { LoginPage, ServerUnreachable } from "@/features/auth/LoginPage"
import { Loading } from "@/components/common"
import { useSettings } from "@/lib/settings"
import { allows, Perm } from "./permissions"
import { type AuthUser, getSession, logout as endAndLogout, subscribe, updateUser } from "./session"
import { AuthContext } from "./useAuth"

/**
 * Sign-in gate (docs/AUTH_INTEGRATION_PLAN.md §7.3). Asks central whether sign-in is required
 * (`/api/v1/auth/config`): when it is off the app works as before (a built-in local admin with every
 * permission); when it is on, nothing renders until the user has signed in.
 */

const LOCAL_ADMIN: AuthUser = {
  id: 0, username: "local", display_name: "Local admin", roles: ["Admin"], is_admin: true, local: true,
  permissions: Object.values(Perm),
}


type Config = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; enabled: boolean }

export function AuthProvider({ children }: { children: ReactNode }) {
  const { settings } = useSettings()
  const centralUrl = settings.centralUrl.replace(/\/+$/, "")
  const queryClient = useQueryClient()
  const session = useSyncExternalStore(subscribe, getSession)
  const [config, setConfig] = useState<Config>({ status: "loading" })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${centralUrl}/api/v1/auth/config`, { signal: controller.signal })
      .then(async (response) => {
        if (response.status === 404) return { enabled: false } // older central without auth
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return (await response.json()) as { enabled: boolean }
      })
      .then((data) => setConfig({ status: "ready", enabled: !!data.enabled }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setConfig({ status: "error", message: error instanceof Error ? error.message : String(error) })
      })
    return () => controller.abort()
  }, [centralUrl, attempt])

  const enabled = config.status === "ready" && config.enabled
  const signedIn = enabled && !!session && session.centralUrl === centralUrl
  const userId = signedIn ? session!.user.id : null

  // permissions may have changed since sign-in: read them once per session
  useEffect(() => {
    if (!signedIn) return
    unwrap<AuthUser>(centralClient(centralUrl).GET("/api/v1/auth/me")).then(updateUser).catch(() => undefined)
  }, [signedIn, userId, centralUrl])

  // another user's cached data must never show
  useEffect(() => {
    queryClient.clear()
  }, [userId, queryClient])

  const user = signedIn ? session!.user : LOCAL_ADMIN
  const can = useCallback((...perms: number[]) => allows(user, perms), [user])
  const logout = useCallback(() => endAndLogout(), [])
  const value = useMemo(() => ({ enabled, user, can, logout }), [enabled, user, can, logout])

  if (config.status === "loading") return <div className="grid h-dvh place-items-center"><Loading label="Connecting to central…" /></div>
  if (config.status === "error") return <ServerUnreachable message={config.message} onRetry={() => setAttempt((a) => a + 1)} />
  if (enabled && !signedIn) return <LoginPage />
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
