import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const backend = 'http://127.0.0.1:8000'

/**
 * 开发与预览都通过 vite 代理把 /api、/v1 转发到 FastAPI，
 * 因此 axios 里只需要写相对路径，生产部署时交给 Nginx/网关做同样的转发即可。
 */
const proxy = {
  '/api': { target: backend, changeOrigin: true },
  '/v1': { target: backend, changeOrigin: true },
}

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  // 相对路径构建产物：既可由 vite preview 提供，也可直接放进任意静态目录
  base: './',
  server: { host: '127.0.0.1', port: 5173, proxy },
  preview: { host: '127.0.0.1', port: 4173, proxy },
  build: { outDir: 'dist', chunkSizeWarningLimit: 1600 },
})
