/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Default central manager URL, e.g. http://100.64.182.102:8000 (can be changed on the Settings page). */
  readonly VITE_CENTRAL_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
