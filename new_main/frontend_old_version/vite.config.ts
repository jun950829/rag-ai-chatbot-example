import path from 'path'
import { fileURLToPath } from 'url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: path.resolve(__dirname, 'dist'),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/tools/embedding': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/chat': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/stream': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
