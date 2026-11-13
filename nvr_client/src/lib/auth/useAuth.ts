import { createContext, useContext } from "react"
import type { AuthUser } from "./session"

export interface AuthContextValue {
  /** sign-in required by central */
  enabled: boolean
  /** which Auth Server: legacy (password form via central) | oidc (the Auth Server's login page) */
  mode: "legacy" | "oidc"
  user: AuthUser
  /** any one of `perms` (none = any signed-in user) */
  can: (...perms: number[]) => boolean
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider")
  return ctx
}
