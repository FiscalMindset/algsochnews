import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/generate': 'http://localhost:8000',
      '/status': 'http://localhost:8000',
      '/outputs': 'http://localhost:8000',
      '/media': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
      '/openapi.json': 'http://localhost:8000',
    },
  },
})
