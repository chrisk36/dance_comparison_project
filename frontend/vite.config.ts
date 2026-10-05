import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // FastAPI backend (uvicorn server.app:app --port 8000)
    proxy: { '/api': 'http://localhost:8000' },
  },
})
