/**
 * Sign-in session (docs/AUTH_INTEGRATION_PLAN.md §7.3). Plain module, no React: the API client, media URLs and
 * the React provider all read it.
 *
 * - Login / refresh / logout go to central (`/api/v1/auth/*`), which proxies the Auth Server (decision D5).
 * - Access token lifetime is short (10 min); it is renewed REFRESH_MARGIN_MS before it expires.
 * - Refresh tokens ROTATE and the Auth Server logs the user out when an old one is reused. So exactly one
 *   refresh runs at a time: in this tab (one shared promise) and across tabs (Web Locks + re-reading storage,
 *   where another tab may already have refreshed).
 * - "Remember me" keeps the session in localStorage (shared by tabs, survives restarts); otherwise
 *   sessionStorage (this tab only).
 */

export interface AuthUser {
  id: number
  username: string
  display_name: string
  roles: string[]
  permissions: number[]
  is_admin: boolean
  local?: boolean
}

export interface Session {
  centralUrl: string
  accessToken: string
  refreshToken: string
  /** epoch ms when the access token expires */
  expiresAt: number
  user: AuthUser
  remember: boolean
}

const KEY = "shah-nvr.auth"
const LOCK = "shah-nvr.auth.refresh"
export const REFRESH_MARGIN_MS = 60_000

let session: Session | null = load()
let endedReason: string | null = null
let refreshing: Promise<Session | null> | null = null
const listeners = new Set<() => void>()

function storages(): Storage[] {
  try {
    return [localStorage, sessionStorage]
  } catch {
    return []
  }
}

function load(): Session | null {
  for (const store of storages()) {
    try {
      const raw = store.getItem(KEY)
      if (raw) return JSON.parse(raw) as Session
    } catch {
      /* unreadable: ignore */
    }
  }
  return null
}

function save(next: Session | null): void {
  for (const store of storages()) {
    try {
      store.removeItem(KEY)
    } catch {
      /* ignore */
    }
  }
  if (next) {
    try {
      ;(next.remember ? localStorage : sessionStorage).setItem(KEY, JSON.stringify(next))
    } catch {
      /* private mode: in memory only */
    }
  }
}

function emit(): void {
  listeners.forEach((fn) => fn())
}

function set(next: Session | null): void {
  session = next
  save(next)
  emit()
}

// another tab signed in, refreshed or signed out
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key !== KEY) return
    session = load()
    emit()
  })
}

export function getSession(): Session | null {
  return session
}

/** Why the last session ended (shown on the login screen), cleared by the next login. */
export function getEndedReason(): string | null {
  return endedReason
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function endSession(reason: string | null = null): void {
  endedReason = reason
  set(null)
}

async function post<T>(centralUrl: string, path: string, body?: unknown, token?: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(centralUrl.replace(/\/+$/, "") + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new AuthRequestError(0, "Server unreachable")
  }
  if (!response.ok) {
    let detail = `Request failed (HTTP ${response.status})`
    try {
      const data = await response.json()
      if (typeof data?.detail === "string") detail = data.detail
    } catch {
      /* no body */
    }
    throw new AuthRequestError(response.status, detail)
  }
  return (response.status === 204 ? undefined : await response.json()) as T
}

export class AuthRequestError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

interface TokensOut {
  access_token: string
  refresh_token: string
  expires_in: number
}

export async function login(centralUrl: string, username: string, password: string, remember: boolean): Promise<AuthUser> {
  const data = await post<TokensOut & { user: AuthUser }>(centralUrl, "/api/v1/auth/login", { username, password })
  endedReason = null
  set({
    centralUrl: centralUrl.replace(/\/+$/, ""), accessToken: data.access_token, refreshToken: data.refresh_token,
    expiresAt: Date.now() + data.expires_in * 1000, user: data.user, remember,
  })
  return data.user
}

export async function logout(): Promise<void> {
  const current = session
  endSession(null)
  if (current) {
    await post(current.centralUrl, "/api/v1/auth/logout", undefined, current.accessToken).catch(() => undefined)
  }
}

/** The user details from /auth/me (permissions may have changed since login). */
export function updateUser(user: AuthUser): void {
  if (session && JSON.stringify(session.user) !== JSON.stringify(user)) set({ ...session, user })
}

function fresh(s: Session | null): boolean {
  return !!s && s.expiresAt - Date.now() > REFRESH_MARGIN_MS
}

async function doRefresh(): Promise<Session | null> {
  const before = session
  if (!before) return null
  // another tab (same storage) may have refreshed while we waited for the lock
  const stored = load()
  if (stored && stored.refreshToken !== before.refreshToken && stored.centralUrl === before.centralUrl) {
    session = stored
    emit()
    if (fresh(stored)) return stored
  }
  const current = session!
  try {
    const data = await post<TokensOut>(current.centralUrl, "/api/v1/auth/refresh", { refresh_token: current.refreshToken })
    const next = { ...current, accessToken: data.access_token, refreshToken: data.refresh_token,
      expiresAt: Date.now() + data.expires_in * 1000 }
    set(next)
    return next
  } catch (error) {
    if (error instanceof AuthRequestError && error.status === 401) {
      endSession("Your session ended. Please sign in again.")
      return null
    }
    throw error // network trouble: keep the session, try again later
  }
}

/** One refresh at a time, in this tab and across tabs. */
export function refreshSession(): Promise<Session | null> {
  if (!refreshing) {
    const locks = typeof navigator !== "undefined" ? navigator.locks : undefined
    const run = locks ? locks.request(LOCK, () => doRefresh()) : doRefresh()
    refreshing = run.finally(() => {
      refreshing = null
    })
  }
  return refreshing
}

/** A valid access token for `centralUrl` (refreshed when about to expire), or null when not signed in there. */
export async function accessToken(centralUrl: string): Promise<string | null> {
  const s = session
  if (!s || s.centralUrl !== centralUrl.replace(/\/+$/, "")) return null
  if (fresh(s)) return s.accessToken
  try {
    return (await refreshSession())?.accessToken ?? null
  } catch {
    return s.accessToken // offline: let the request fail normally
  }
}

/** The current access token without waiting (for player / download URLs built during render). */
export function accessTokenNow(centralUrl: string): string | null {
  const s = session
  return s && s.centralUrl === centralUrl.replace(/\/+$/, "") ? s.accessToken : null
}

/** Codes sent by central in X-Auth-Error when a session can no longer be used. */
const SESSION_ENDED = new Set(["token_revoked", "inactive", "no_access", "invalid_token", "wrong_app"])

/** Called on every 401 from central. */
export function handleUnauthorized(code: string | null): void {
  if (!session) return
  if (code === "token_expired") {
    void refreshSession().catch(() => undefined)
    return
  }
  if (code && SESSION_ENDED.has(code)) {
    endSession(code === "no_access" ? "Your account no longer has access to Shah-NVR." : "Your session ended. Please sign in again.")
  }
}
