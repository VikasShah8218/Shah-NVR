/**
 * Sign-in on the new Auth Server's own page (docs/AUTH_V2_PLAN.md): OAuth 2.1 Authorization Code + PKCE (S256).
 * Central never sees the password; it only checks the access token this returns.
 *
 *   startSignIn()   -> browser goes to {issuer}/oauth/authorize (the Auth Server login page, 2FA, passkeys)
 *   /auth/callback  -> completeSignIn(): checks state + iss, swaps the code for tokens at {issuer}/oauth/token,
 *                      asks central who that is (/auth/me), then starts the session (session.ts).
 *
 * The verifier and state live in sessionStorage only for the round trip (this tab, cleared on use).
 */

import { type AuthUser, startOidcSession } from "./session"

export interface OidcConfig {
  issuer: string
  clientId: string
  scopes: string
}

interface Pending {
  state: string
  verifier: string
  centralUrl: string
  issuer: string
  clientId: string
  remember: boolean
  returnTo: string
}

const PENDING = "shah-nvr.auth.pending"
export const CALLBACK_PATH = "/auth/callback"

function b64url(bytes: Uint8Array): string {
  let s = ""
  bytes.forEach((b) => (s += String.fromCharCode(b)))
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")
}

function random(bytes = 32): string {
  return b64url(crypto.getRandomValues(new Uint8Array(bytes)))
}

async function challenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))
  return b64url(new Uint8Array(digest))
}

export function redirectUri(): string {
  return `${window.location.origin}${CALLBACK_PATH}`
}

/** Leave for the Auth Server's login page. `forceLogin` after a sign-out, so the next person must type a password. */
export async function startSignIn(centralUrl: string, cfg: OidcConfig, remember: boolean, forceLogin = false): Promise<void> {
  if (!crypto?.subtle) throw new Error("This page must be opened over https or on localhost to sign in.")
  const pending: Pending = {
    state: random(), verifier: random(48), centralUrl: centralUrl.replace(/\/+$/, ""),
    issuer: cfg.issuer.replace(/\/+$/, ""), clientId: cfg.clientId, remember,
    returnTo: window.location.pathname === CALLBACK_PATH ? "/" : window.location.pathname + window.location.search,
  }
  sessionStorage.setItem(PENDING, JSON.stringify(pending))
  const params = new URLSearchParams({
    response_type: "code", client_id: cfg.clientId, redirect_uri: redirectUri(), scope: cfg.scopes,
    state: pending.state, code_challenge: await challenge(pending.verifier), code_challenge_method: "S256",
  })
  if (forceLogin) params.set("prompt", "login")
  window.location.assign(`${pending.issuer}/oauth/authorize?${params}`)
}

const ERRORS: Record<string, string> = {
  access_denied: "Your account has no role in Shah-NVR. Ask an administrator for access.",
  login_required: "Please sign in.",
  invalid_scope: "The Auth Server refused the requested scopes (check the snvr-web client).",
}

/** Finish the round trip on /auth/callback. Returns where to go next. */
export async function completeSignIn(search: string): Promise<string> {
  const params = new URLSearchParams(search)
  let pending: Pending | null = null
  try {
    pending = JSON.parse(sessionStorage.getItem(PENDING) ?? "null") as Pending | null
  } catch {
    pending = null
  }
  sessionStorage.removeItem(PENDING)
  const error = params.get("error")
  if (error) throw new Error(ERRORS[error] ?? params.get("error_description") ?? `Sign-in failed (${error})`)
  if (!pending || params.get("state") !== pending.state) throw new Error("This sign-in link is stale. Please sign in again.")
  const iss = params.get("iss")
  if (iss && iss.replace(/\/+$/, "") !== pending.issuer) throw new Error("The answer came from another Auth Server.")
  const code = params.get("code")
  if (!code) throw new Error("The Auth Server sent no authorization code.")

  const tokens = await tokenRequest(pending.issuer, {
    grant_type: "authorization_code", code, redirect_uri: redirectUri(), code_verifier: pending.verifier,
    client_id: pending.clientId,
  })
  if (!tokens.refresh_token) throw new Error("The Auth Server sent no refresh token.")
  const me = await fetch(`${pending.centralUrl}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${tokens.access_token}` } })
  if (!me.ok) {
    let detail = `HTTP ${me.status}`
    try {
      const body = await me.json()
      if (typeof body?.detail === "string") detail = body.detail
    } catch {
      /* no body */
    }
    throw new Error(`Central refused the sign-in: ${detail}`)
  }
  startOidcSession({
    centralUrl: pending.centralUrl, issuer: pending.issuer, clientId: pending.clientId,
    accessToken: tokens.access_token, refreshToken: tokens.refresh_token,
    expiresAt: Date.now() + tokens.expires_in * 1000, user: (await me.json()) as AuthUser, remember: pending.remember,
  })
  return pending.returnTo || "/"
}

export interface TokenResponse {
  access_token: string
  refresh_token?: string
  expires_in: number
}

export class OAuthError extends Error {
  readonly status: number
  readonly code: string
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

/** POST {issuer}/oauth/token (form-encoded, public client: client_id in the body). */
export async function tokenRequest(issuer: string, form: Record<string, string>): Promise<TokenResponse> {
  let response: Response
  try {
    response = await fetch(`${issuer}/oauth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(form),
    })
  } catch {
    throw new OAuthError(0, "unreachable", "The Auth Server is not reachable (or it does not allow this page's address: CORS).")
  }
  if (!response.ok) {
    let code = "error"
    let message = `Auth Server error (HTTP ${response.status})`
    try {
      const body = await response.json()
      code = String(body?.error ?? body?.detail?.code ?? code)
      message = String(body?.error_description ?? body?.detail?.message ?? code)
    } catch {
      /* no body */
    }
    throw new OAuthError(response.status, code, message)
  }
  return (await response.json()) as TokenResponse
}

/** End this device's login at the Auth Server: revoke the refresh token family, then the login itself. */
export async function endAuthServerLogin(issuer: string, clientId: string, accessToken: string, refreshToken: string): Promise<void> {
  const quiet = (p: Promise<unknown>) => p.catch(() => undefined)
  await quiet(fetch(`${issuer}/oauth/logout`, { method: "POST", headers: { Authorization: `Bearer ${accessToken}` } }))
  await quiet(fetch(`${issuer}/oauth/revoke`, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ token: refreshToken, client_id: clientId }),
  }))
}
