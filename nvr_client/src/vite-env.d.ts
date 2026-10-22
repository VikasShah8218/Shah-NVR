/// <reference types="vite/client" />

declare const __PRODUCT_NAME__: string
declare const __PRODUCT_LOGO__: string

interface ImportMetaEnv {
  /** Default central manager URL, e.g. http://192.168.1.3:8000, the server's LAN IP (can be changed on the Settings page). */
  readonly VITE_CENTRAL_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
