import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react"
import { useLocation } from "react-router"
import { centralClient, unwrap } from "@/api/client"
import { AuthCallback, LoginPage, ServerUnreachable } from "@/features/auth/LoginPage"
import { Loading } from "@/components/common"
import { useSettings } from "@/lib/settings"
import { CALLBACK_PATH, type OidcConfig } from "./oidc"
import { allows, Perm } from "./permissions"
import { type AuthUser, getSession, logout as endAndLogout, subscribe, updateUser } from "./session"
import { AuthContext } from "./useAuth"

/**
 * Sign-in gate (docs/AUTH_INTEGRATION_PLAN.md §7.3). Asks central whether sign-in is required
 * (`/api/v1/auth/config`): when it is off the app works as before (a built-in local admin with every
 * permission); when it is on, nothing renders until the user has signed in.
 */

const LOCAL_ADMIN: AuthUser = {
  id: "0", username: "local", display_name: "Local admin", roles: ["Admin"], is_admin: true, local: true,
  permissions: Object.values(Perm), scope: { all_cameras: true, groups: 0, cameras: 0 },
}


interface ConfigOut {
  enabled: boolean
  mode?: "legacy" | "oidc"
  issuer?: string | null
  web_client_id?: string | null
  scopes?: string | null
}

type Config =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; enabled: boolean; mode: "legacy" | "oidc"; oidc: OidcConfig | null }

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
        if (response.status === 404) return { enabled: false } as ConfigOut // older central without auth
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return (await response.json()) as ConfigOut
      })
      .then((data) => {
        const mode = data.mode === "oidc" ? "oidc" : "legacy"
        const oidc = mode === "oidc" && data.issuer && data.web_client_id
          ? { issuer: data.issuer, clientId: data.web_client_id, scopes: data.scopes || "openid profile email" }
          : null
        setConfig({ status: "ready", enabled: !!data.enabled, mode, oidc })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setConfig({ status: "error", message: error instanceof Error ? error.message : String(error) })
      })
    return () => controller.abort()
  }, [centralUrl, attempt])

  const location = useLocation()
  const enabled = config.status === "ready" && config.enabled
  const mode = config.status === "ready" ? config.mode : "legacy"
  // a session from the other Auth Server (central was switched) is not valid here: sign in again
  const signedIn = enabled && !!session && session.centralUrl === centralUrl && (session.mode ?? "legacy") === mode
  const userId = signedIn ? session!.user.id : null

  // permissions may have changed since sign-in: read them once per session
  useEffect(() => {
    if (!signedIn) return
    unwrap(centralClient(centralUrl).GET("/api/v1/auth/me")).then((me) => updateUser(me as AuthUser)).catch(() => undefined)
  }, [signedIn, userId, centralUrl])

  // another user's cached data must never show
  useEffect(() => {
    queryClient.clear()
  }, [userId, queryClient])

  const user = signedIn ? session!.user : LOCAL_ADMIN
  const can = useCallback((...perms: number[]) => allows(user, perms), [user])
  const logout = useCallback(() => endAndLogout(), [])
  const value = useMemo(() => ({ enabled, mode, user, can, logout }), [enabled, mode, user, can, logout])

  if (config.status === "loading") return <div className="grid h-dvh place-items-center"><Loading label="Connecting to central…" /></div>
  if (config.status === "error") return <ServerUnreachable message={config.message} onRetry={() => setAttempt((a) => a + 1)} />
  if (location.pathname === CALLBACK_PATH) return <AuthCallback />
  if (enabled && !signedIn) return <LoginPage mode={mode} oidc={config.status === "ready" ? config.oidc : null} />
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
