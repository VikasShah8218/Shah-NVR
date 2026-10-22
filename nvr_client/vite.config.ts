import fs from 'node:fs'
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const brandingPath = path.resolve(import.meta.dirname, './branding.json')
const branding = JSON.parse(fs.readFileSync(brandingPath, 'utf8')) as { productName?: unknown; logo?: unknown }
if (typeof branding.productName !== 'string' || !branding.productName.trim()) {
  throw new Error(`${brandingPath}: productName must be a non-empty string`)
}
if (typeof branding.logo !== 'string' || !branding.logo.trim()) {
  throw new Error(`${brandingPath}: logo must be a non-empty public URL`)
}
const productName = branding.productName.trim()
const productLogo = branding.logo.trim()

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]!)
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    {
      name: 'shah-nvr-branding',
      transformIndexHtml: (html) => html
        .replaceAll('__PRODUCT_NAME__', escapeHtml(productName))
        .replaceAll('__PRODUCT_LOGO__', escapeHtml(productLogo)),
    },
    react(),
    tailwindcss(),
  ],
  define: {
    __PRODUCT_NAME__: JSON.stringify(productName),
    __PRODUCT_LOGO__: JSON.stringify(productLogo),
  },
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  // 5180 (not Vite's default 5173) so it does not collide with other local Vite apps.
  server: { port: 5180, strictPort: true, host: true },
})
