import path from 'path'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // Same CONDUIT_* vars as the container: read from the repo-root .env, overridable from the shell
  const env = { ...loadEnv(mode, path.resolve(__dirname, '..'), 'CONDUIT_'), ...process.env }
  const apiPort = env.CONDUIT_API_PORT || '8000'

  return {
    plugins: [react()],
    base: '/',
    resolve: {
      alias: { '@': path.resolve(__dirname, './src') },
    },
    server: {
      proxy: {
        '/api': { target: `http://127.0.0.1:${apiPort}`, changeOrigin: true },
      },
    },
  }
})
