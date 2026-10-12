import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react"

export type LiveProtocol = "auto" | "webrtc" | "hls"

export interface ClientSettings {
  centralUrl: string
  pollSeconds: number
  liveProtocol: LiveProtocol
  gridUsesSubstream: boolean
}

const STORAGE_KEY = "shah-nvr.settings"

export const DEFAULT_SETTINGS: ClientSettings = {
  centralUrl: (import.meta.env.VITE_CENTRAL_URL as string | undefined) ?? "http://localhost:8000",
  pollSeconds: 5,
  liveProtocol: "auto",
  gridUsesSubstream: true,
}

/** localStorage can throw (private mode, blocked storage); the app must still work. */
export function readStored<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback
  } catch {
    return fallback
  }
}

export function writeStored(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* ignore */
  }
}

interface SettingsContextValue {
  settings: ClientSettings
  update: (patch: Partial<ClientSettings>) => void
  reset: () => void
}

const SettingsContext = createContext<SettingsContextValue | null>(null)

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<ClientSettings>(() => readStored(STORAGE_KEY, DEFAULT_SETTINGS))

  const update = useCallback((patch: Partial<ClientSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch, centralUrl: (patch.centralUrl ?? prev.centralUrl).replace(/\/+$/, "") }
      writeStored(STORAGE_KEY, next)
      return next
    })
  }, [])

  const reset = useCallback(() => {
    writeStored(STORAGE_KEY, DEFAULT_SETTINGS)
    setSettings(DEFAULT_SETTINGS)
  }, [])

  const value = useMemo(() => ({ settings, update, reset }), [settings, update, reset])
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>
}

export function useSettings(): SettingsContextValue {
  const ctx = useContext(SettingsContext)
  if (!ctx) throw new Error("useSettings must be used inside SettingsProvider")
  return ctx
}
