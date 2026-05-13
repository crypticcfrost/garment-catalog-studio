import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backend = 'http://localhost:8000'

const proxy = {
  '/api': backend,
  '/ws': { target: 'ws://localhost:8000', ws: true },
  '/uploads': backend,
  '/outputs': backend,
  // Same path layout as Vercel experimentalServices (vercel.json)
  '/_/backend': {
    target: backend,
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/_\/backend/, ''),
  },
} as const

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: { ...proxy },
  },
  preview: {
    port: 3000,
    proxy: { ...proxy },
  },
})
